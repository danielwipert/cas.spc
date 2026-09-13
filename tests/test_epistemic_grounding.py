"""T17 — reading a document is not observing the world.

`EpistemicStatus.OBSERVED` was doing two jobs. Reading a press release
establishes **that the press release says so**; it establishes nothing about
the merger. The extractor only ever has the first, and was committing the
second: across five real runs the claims marked `observed` and the claims at
confidence 1.00 were the same set, and among them "Paramount **will acquire**
Warner Bros. Discovery" — a future event contingent on approvals, recorded as
something someone saw.

`REPORTED` is the honest label, and it is **derived**, not asked for: the
prompt no longer offers `observed`, and a model that says it anyway is
corrected rather than believed. `OBSERVED` stays in the vocabulary for an
operator that genuinely sees the thing itself, and `VERIFIED` for a future
corroboration step.

The consequence is in the artifact a human reads. A memo line that says
`_(confidence 60%, observed)_` over a company's promise about itself is not a
hedge a reader can discount — it is a false statement about where the claim
came from.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spc_state.analyze import run_analysis
from spc_state.models import EpistemicStatus
from spc_state.operators import LLMExtractOperator
from spc_state.operators.extract_llm import _SCHEMA_HINT, ground_status
from spc_state.projection.builder import is_weak_claim
from spc_state.providers import ReplayProvider
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.source_types import SourceType
from spc_state.store import RunPaths

DOCUMENT = (
    "TitanCorp announces record quarterly results. Revenue grew 41% year over "
    "year. Management expects the momentum to continue through next year."
)
QUOTE = "Revenue grew 41% year over year"

FIXTURES = Path(__file__).parent / "fixtures"
DOCUMENT_PATH = FIXTURES / "live_document.txt"
CASSETTE_PATH = FIXTURES / "cassettes" / "analyze_five_stage.json"


def _clock() -> FixedClock:
    start = dt.datetime(2026, 9, 12, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=10 * i) for i in range(40)])


def _payload(status: str | None) -> str:
    claim: dict[str, object] = {
        "text": "TitanCorp's revenue grew sharply.",
        "claim_type": "factual_claim",
        "confidence": 0.9,
        "evidence_quote": QUOTE,
        "assumption": None,
    }
    if status is not None:
        claim["epistemic_status"] = status
    return json.dumps({"claims": [claim]})


def _full_patch(status: str) -> str:
    """The other way in: a complete patch the model wrote itself."""
    now = "2026-09-12T00:00:00Z"
    return json.dumps(
        {
            "patch_id": "patch_001",
            "base_state_id": "sr_x",
            "base_state_version": 0,
            "proposed_by": "llm_extract_transform@0.1.0",
            "created_at": now,
            "read_set": [],
            "add_objects": {
                "claims": [
                    {
                        "id": "claim_001",
                        "object_type": "claim",
                        "text": "TitanCorp's revenue grew sharply.",
                        "claim_type": "factual_claim",
                        "epistemic_status": status,
                        "confidence": 0.9,
                        "status": "active",
                        "supporting_evidence": ["ev_001"],
                        "assumptions": [],
                        "extracted_by": "transform_extract_001",
                    }
                ],
                "evidence": [
                    {
                        "id": "ev_001",
                        "object_type": "evidence",
                        "source_type": "input_document",
                        "source_id": "doc_001",
                        "quote_or_span": QUOTE,
                        "reliability": "high",
                        "status": "active",
                        "extracted_by": "transform_extract_001",
                    }
                ],
            },
            "transform_record": {
                "id": "transform_extract_001",
                "transform_type": "extract",
                "operator": "llm_extract_transform",
                "operator_version": "llm_extract_transform@0.1.0",
                "input_state_version": 0,
                "output_state_version": None,
                "read_set": [],
                "write_set": ["claim_001", "ev_001"],
                "confidence_changes": [],
                "started_at": now,
                "finished_at": now,
            },
            "status": "proposed",
        }
    )


def _extract(tmp_path: Path, payload: str, source_type: SourceType):
    clock = _clock()
    operator = LLMExtractOperator(
        MockProvider([payload], provider="fake", model="fake-extract-v0"),
        input_text=DOCUMENT,
        clock=clock,
        source_type=source_type,
    )
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="grounding"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_x", project_id="p", name="TitanCorp", now=clock.now()
        ),
        operators=[operator],
        input_text=DOCUMENT,
    )
    assert result.final_state.state_version == 1, "the extraction must have committed"
    return next(iter(result.final_state.claims.values()))


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("claimed", "expected"),
    [
        (EpistemicStatus.OBSERVED, EpistemicStatus.REPORTED),
        (EpistemicStatus.VERIFIED, EpistemicStatus.REPORTED),
        (EpistemicStatus.INFERRED, EpistemicStatus.INFERRED),
        (EpistemicStatus.ASSUMED, EpistemicStatus.ASSUMED),
        (EpistemicStatus.SPECULATIVE, EpistemicStatus.SPECULATIVE),
        (EpistemicStatus.CONTRADICTED, EpistemicStatus.CONTRADICTED),
    ],
)
def test_only_the_statuses_a_reader_cannot_reach_are_rewritten(
    claimed: EpistemicStatus, expected: EpistemicStatus
) -> None:
    """`observed` and `verified` are the two nobody gets from reading.

    Everything else is a claim about the reader's own reasoning, which reading
    really does establish, so it passes through untouched.
    """
    assert ground_status(claimed) is expected


def test_the_model_is_not_offered_observed(tmp_path: Path) -> None:
    """Asking for a value we always overwrite would waste tokens and mislead."""
    assert '"reported | inferred | assumed | speculative"' in _SCHEMA_HINT
    assert "observed |" not in _SCHEMA_HINT


def test_a_model_claiming_observation_is_corrected(tmp_path: Path) -> None:
    """The regression this exists for, on the assembled path.

    The model said it observed TitanCorp's revenue growth. It read a press
    release about TitanCorp's revenue growth.
    """
    claim = _extract(tmp_path, _payload("observed"), SourceType.PRESS_RELEASE)
    assert claim.epistemic_status is EpistemicStatus.REPORTED


def test_a_model_authored_patch_cannot_smuggle_observation_through(
    tmp_path: Path,
) -> None:
    """The second way in, which T8 and T14 both had to close as well."""
    claim = _extract(tmp_path, _full_patch("observed"), SourceType.PRESS_RELEASE)
    assert claim.epistemic_status is EpistemicStatus.REPORTED
    assert claim.confidence == 0.9, "only the status changed"


def test_an_omitted_status_defaults_to_reported(tmp_path: Path) -> None:
    """Silence must land on the honest label, not a stronger or weaker guess.

    It was `inferred`, which says the extractor worked something out. Usually
    it did not — the document said so.
    """
    claim = _extract(tmp_path, _payload(None), SourceType.NEWS_REPORT)
    assert claim.epistemic_status is EpistemicStatus.REPORTED


def test_inference_still_reads_as_inference(tmp_path: Path) -> None:
    """The distinction the model *can* draw is kept, not flattened away."""
    claim = _extract(tmp_path, _payload("inferred"), SourceType.NEWS_REPORT)
    assert claim.epistemic_status is EpistemicStatus.INFERRED


def test_a_reported_claim_is_grounded_not_weak(tmp_path: Path) -> None:
    """The deliberate non-change, pinned so it is a decision and not a drift.

    Groundedness is about provenance, and a reported claim has some: a named
    source says it and the span is on record. How much that source is worth is
    already priced in by T14 and T16, so the projection filter must not
    re-litigate it — relabelling must not quietly reclassify every extracted
    claim as weak.
    """
    claim = _extract(tmp_path, _payload("observed"), SourceType.REGULATORY_FILING)
    assert claim.epistemic_status is EpistemicStatus.REPORTED
    assert claim.confidence >= 0.75
    assert not is_weak_claim(claim)


# ---------------------------------------------------------------------------
# against real recorded output, and in the document a human reads
# ---------------------------------------------------------------------------


def _replay(tmp_path: Path):
    document = DOCUMENT_PATH.read_text(encoding="utf-8")
    provider = ReplayProvider.from_path(CASSETTE_PATH, document=document)
    return run_analysis(
        provider,
        document,
        RunPaths(root=tmp_path, run_id="replay"),
        clock=_clock(),
        source_type=SourceType.PRESS_RELEASE,
    )


def test_no_claim_extracted_from_a_document_commits_as_observed(
    tmp_path: Path,
) -> None:
    """Held against output a real model produced, not a hand-written payload."""
    result = _replay(tmp_path)
    claims = result.run.final_state.claims
    assert claims

    statuses = {c.epistemic_status for c in claims.values()}
    assert EpistemicStatus.OBSERVED not in statuses
    assert EpistemicStatus.REPORTED in statuses, (
        "this recording must really contain claims the model stated as fact, "
        "or the guard proves nothing"
    )


def test_the_memo_tells_the_reader_the_source_said_it(tmp_path: Path) -> None:
    """Where this change actually lands: the document a human reads.

    "observed" over a company's promise about itself is not a hedge a reader
    can discount — it is a false statement about where the claim came from.
    """
    result = _replay(tmp_path)
    assert result.memo_path is not None
    memo = result.memo_path.read_text(encoding="utf-8")

    assert ", reported)" in memo
    assert ", observed)" not in memo


def test_the_deterministic_demo_extractor_is_untouched() -> None:
    """The rule is scoped to the path where a model is the author.

    `ExtractOperator`'s claims are hand-written against a fixture and its
    artifacts are a release gate (`DEMO.md` byte-stability), so it keeps its
    own values. Pinned so that a future edit "for consistency" has to be
    deliberate about breaking the demo.
    """
    from spc_state.operators.extract import ExtractOperator

    source = Path(ExtractOperator.__module__.replace(".", "/") + ".py")
    assert "EpistemicStatus.OBSERVED" in (Path("src") / source).read_text(
        encoding="utf-8"
    )
