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
from collections.abc import Sequence
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


def documents_digest(documents: Sequence[str]) -> str:
    """The same hash, over every document a run reads (T25).

    A multi-source run has no single document to pin, so the cassette pins all of
    them in order. Joined on a NUL, which cannot occur in the text files this
    reads, so two documents cannot be split differently and collide.

    For one document this is **exactly** `text_digest`, since joining a
    one-element sequence returns it unchanged — so every cassette recorded before
    multi-source runs existed keeps validating against its own document.
    """
    return text_digest("\x00".join(documents))


class SourceSpec(BaseModel):
    """One document a recording read, and how the caller declared it.

    The `path` is repo-relative, because that is what makes it resolvable from
    a clean clone — the fixtures a cassette reads are committed beside it.
    """

    path: str
    source_type: str
    derives_from: str | None = None

    model_config = ConfigDict(extra="forbid")


class RunSpec(BaseModel):
    """How a recording was *declared* — the half a digest cannot pin.

    A cassette has always pinned the documents it read (`document_sha256`), so
    replaying it against the wrong material is refused. It pinned nothing about
    how those documents were **declared**, and that is the more dangerous half:
    `source_type` and `derives_from` are the caller's facts, which the model
    never sees (T14), so they reach no prompt. Replay one with a different
    `--source-type` and every request still matches its recording — zero drift,
    a clean run, and a **different memo**. Nothing could catch it.

    So the recorder writes down what it was told. `spc-demo replay --cassette X`
    then needs no other argument, and a caller who overrides a declaration is
    told they have deviated from the recording.

    **Regions are deliberately absent.** A region is resolved after the model
    has answered, changing neither the prompts nor the calls, so one cassette
    must replay with regions declared and without — that is T27's controlled
    experiment and the reason `--region` stays a command-line-only flag.

    Optional on `Cassette` rather than required: a cassette recorded before
    this existed, or written by hand, still replays from explicit arguments.
    """

    #: The decision question the run was given.
    #:
    #: Worth knowing what this does *not* do: it reaches no prompt.
    #: `build_analysis_operators` does not take it, so no operator sees it —
    #: it is the heading on the projected memo and receipt and nothing else.
    #: Recorded here because it is part of the output a reader opens, not
    #: because it steers the analysis. (That it *cannot* steer the analysis is
    #: a live defect, not a design: see HANDOFF.md.)
    question: str
    #: Every source in reading order. The first is `doc_001`, the primary
    #: document; the rest are the `--also-input`s, in the order given.
    sources: list[SourceSpec] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def deviations(
        self,
        *,
        question: str,
        source_types: Sequence[str],
        lineage: Sequence[str | None],
    ) -> list[str]:
        """Where a caller's declarations differ from the recording's.

        Returned rather than raised. A deviation is not automatically wrong —
        asking *"what would this memo say if I had called it a press release?"*
        is a legitimate experiment, and one that costs nothing because the
        declaration reaches no prompt. It is only dangerous when unnoticed, so
        the caller is told and decides.

        Paths are not compared: the cassette's `document_sha256` already
        refuses material the recording never saw, and it does it on content
        rather than on a filename that may have moved.
        """
        found: list[str] = []
        if question != self.question:
            # Flagged, but flagged for what it is: the question is the memo's
            # heading and reaches no prompt, so this changes the rendered
            # output and not one step of the analysis behind it.
            found.append(
                f"question (memo heading only): recorded {self.question!r}, "
                f"given {question!r}"
            )
        if len(source_types) != len(self.sources):
            found.append(
                f"source count: recorded {len(self.sources)}, "
                f"given {len(source_types)}"
            )
            return found
        for i, (spec, given) in enumerate(
            zip(self.sources, source_types, strict=True), start=1
        ):
            if given != spec.source_type:
                found.append(
                    f"doc_{i:03d} source type: recorded {spec.source_type}, "
                    f"given {given}"
                )
        # Lineage is declared only for the extra documents, so it is offset by
        # one: the primary document is `doc_001` and cannot derive from
        # anything read after it.
        for i, (spec, given_parent) in enumerate(
            zip(self.sources[1:], lineage, strict=True), start=2
        ):
            if given_parent != spec.derives_from:
                found.append(
                    f"doc_{i:03d} derives from: recorded "
                    f"{spec.derives_from or 'nothing'}, "
                    f"given {given_parent or 'nothing'}"
                )
        return found


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
    #: How the run was declared, when the recorder knew (see `RunSpec`).
    run_spec: RunSpec | None = None
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
        document: str | None = None,
        documents: Sequence[str] | None = None,
        provider: str = "openrouter",
        model: str = "unknown",
        note: str = "",
        run_spec: RunSpec | None = None,
    ) -> None:
        """Record against one document, or `documents` for a multi-source run.

        Exactly one of the two: passing both is a caller that has not decided
        which documents the recording covers, and a cassette pinned to the wrong
        set would replay against material it never saw.
        """
        if (document is None) == (documents is None):
            raise CassetteError(
                "RecordingProvider needs exactly one of `document` or "
                "`documents` — the cassette pins what the run actually read."
            )
        self.inner = inner
        self._document_sha256 = documents_digest(
            [document] if document is not None else list(documents or ())
        )
        self._provider = provider
        self._model = model
        self._note = note
        self._run_spec = run_spec
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
            run_spec=self._run_spec,
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
    def from_path(
        cls,
        path: Path,
        *,
        document: str | None = None,
        documents: Sequence[str] | None = None,
    ) -> ReplayProvider:
        """Load a cassette, optionally proving it belongs to these documents.

        `documents` is the multi-source form; for a single document the two are
        interchangeable, since `documents_digest` of one document is its own
        `text_digest`.
        """
        if document is not None and documents is not None:
            raise CassetteError(
                "ReplayProvider.from_path takes `document` or `documents`, not both."
            )
        cassette = Cassette.load(path)
        given = [document] if document is not None else documents
        if given is not None and documents_digest(list(given)) != cassette.document_sha256:
            raise CassetteError(
                f"Cassette {path} was recorded against different source material. "
                "Re-record it, or replay it against the documents it captured."
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
    "RunSpec",
    "SourceSpec",
    "request_digest",
    "text_digest",
]
