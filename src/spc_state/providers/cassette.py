"""Record a real provider exchange once; replay it offline forever.

Every LLM-path test in this repo drives the pipeline with `MockProvider` and a
hand-written payload — which is, by construction, already well-formed. Real
model output is not: it arrives wrapped in markdown fences, with typographic
quotes, with a terminal period added to a bullet that has none, with fields in
an order nobody chose. The T8 provenance bug was found by running one real
document by hand, because nothing in the suite could have found it.

A cassette closes that gap. `RecordingProvider` wraps a live provider and
captures each completion verbatim; `ReplayProvider` feeds those captured
completions back in order, with no key and no network, so CI can regression-test
the whole pipeline against genuine model output.

**What replay does and does not prove.** It proves the pipeline still handles
real output correctly — assembly, validation, routing, provenance, projection.
It does not re-check the *model*: the responses are fixed, so a cassette
recorded against one prompt keeps replaying even after that prompt changes.
Each exchange therefore stores a hash of the request it answered, and
`ReplayProvider.drifted_calls` reports which no longer match what the code
sends today. Drift is deliberately **not** an error — a contributor without an
API key must still be able to run the suite — but it does mean the cassette
has stopped reflecting live behavior and should be re-recorded
(`tools/record_cassette.py`, `--check` to inspect drift without a network).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..models import ModelFingerprint, TokenUsage
from .base import LLMProvider, ProviderRequest, ProviderResponse

#: Bumped when the on-disk shape changes incompatibly.
CASSETTE_VERSION = 1


class CassetteError(RuntimeError):
    """A cassette could not be loaded, or ran out of recorded exchanges."""


def request_digest(request: ProviderRequest) -> str:
    """A stable hash of everything an operator asked for.

    Covers the system prompt, the user prompt (which embeds the document) and
    any retry feedback, so a changed prompt is visible as drift.
    """
    payload = json.dumps(
        {
            "system": request.system,
            "user": request.user,
            "feedback": list(request.feedback),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_digest(text: str) -> str:
    """A stable hash of a document, so replay can prove it has the right one."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Exchange(BaseModel):
    """One captured request/response pair."""

    request_sha256: str
    response_text: str
    fingerprint: ModelFingerprint
    usage: TokenUsage | None = None

    model_config = ConfigDict(extra="forbid")


class Cassette(BaseModel):
    """An ordered recording of one run's provider exchanges."""

    version: int = CASSETTE_VERSION
    recorded_at: dt.datetime
    provider: str
    model: str
    document_sha256: str
    note: str = ""
    exchanges: list[Exchange] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def load(cls, path: Path) -> Cassette:
        try:
            cassette = cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CassetteError(f"Could not load cassette {path}: {exc}") from exc
        if cassette.version != CASSETTE_VERSION:
            raise CassetteError(
                f"Cassette {path} is version {cassette.version}; this build reads "
                f"version {CASSETTE_VERSION}. Re-record it."
            )
        if not cassette.exchanges:
            raise CassetteError(f"Cassette {path} recorded no exchanges.")
        return cassette

    def save(self, path: Path) -> None:
        """Write the cassette as pretty JSON with a trailing newline."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(self.model_dump_json())
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


class RecordingProvider(LLMProvider):
    """Delegates to a live provider and captures every exchange verbatim.

    The captured `response_text` is the model's raw completion — never
    reformatted, so replay reproduces exactly what the runtime had to cope
    with.
    """

    def __init__(
        self,
        inner: LLMProvider,
        *,
        document: str,
        provider: str = "openrouter",
        model: str = "unknown",
        note: str = "",
    ) -> None:
        self.inner = inner
        self._document_sha256 = text_digest(document)
        self._provider = provider
        self._model = model
        self._note = note
        self._exchanges: list[Exchange] = []

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        response = self.inner.complete(request)
        self._exchanges.append(
            Exchange(
                request_sha256=request_digest(request),
                response_text=response.text,
                fingerprint=response.fingerprint,
                usage=response.usage,
            )
        )
        return response

    def cassette(self, *, now: dt.datetime | None = None) -> Cassette:
        """The recording so far."""
        return Cassette(
            recorded_at=now or dt.datetime.now(tz=dt.UTC),
            provider=self._provider,
            model=self._model,
            document_sha256=self._document_sha256,
            note=self._note,
            exchanges=list(self._exchanges),
        )

    @property
    def call_count(self) -> int:
        return len(self._exchanges)


class ReplayProvider(LLMProvider):
    """Replays a cassette's exchanges in order. No key, no network.

    Running out of exchanges raises rather than repeating the last one: a
    pipeline that suddenly makes an extra call is a real change, and silently
    handing it a stale completion would hide it.
    """

    def __init__(self, cassette: Cassette) -> None:
        self.cassette = cassette
        self._index = 0
        self._drifted: list[int] = []

    @classmethod
    def from_path(cls, path: Path, *, document: str | None = None) -> ReplayProvider:
        """Load a cassette, optionally proving it belongs to `document`."""
        cassette = Cassette.load(path)
        if document is not None and text_digest(document) != cassette.document_sha256:
            raise CassetteError(
                f"Cassette {path} was recorded against a different document. "
                "Re-record it, or replay it against the document it captured."
            )
        return cls(cassette)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        if self._index >= len(self.cassette.exchanges):
            raise CassetteError(
                f"Cassette exhausted after {len(self.cassette.exchanges)} exchange(s): "
                "the pipeline asked for another completion. Either a step was added "
                "or retry behaviour changed — re-record the cassette."
            )
        exchange = self.cassette.exchanges[self._index]
        if request_digest(request) != exchange.request_sha256:
            # Not an error: replay still exercises the pipeline against real
            # output. It does mean this cassette predates the current prompts.
            self._drifted.append(self._index)
        self._index += 1
        return ProviderResponse(
            text=exchange.response_text,
            fingerprint=exchange.fingerprint,
            usage=exchange.usage,
        )

    @property
    def call_count(self) -> int:
        return self._index

    @property
    def drifted_calls(self) -> list[int]:
        """Indices of replayed calls whose request no longer matches the recording."""
        return list(self._drifted)

    @property
    def exhausted(self) -> bool:
        """True when every recorded exchange has been replayed."""
        return self._index >= len(self.cassette.exchanges)


__all__ = [
    "CASSETTE_VERSION",
    "Cassette",
    "CassetteError",
    "Exchange",
    "RecordingProvider",
    "ReplayProvider",
    "request_digest",
    "text_digest",
]
