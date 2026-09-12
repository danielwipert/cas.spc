"""T14 — the extractor derives reliability, and the Retriever acts on it.

`tests/test_source_types.py` pins the taxonomy. This pins the wiring: that
`LLMExtractOperator` stamps the declared source's reliability on every span it
commits, on both routes in; that a model asserting `high` for its own
extraction no longer gets it; and that the downstream consequence — the
Retriever asking what stronger source would confirm an under-confident claim —
actually follows from the declaration.

That last one is the point of the whole change. On a live run over a corporate
press release the model rated all ten of its own spans `high`, the Retriever
found no gaps, and the memo recommended proceeding at 90%. Declaring the
document for what it is now produces the questions instead.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spc_state.models import Reliability
from spc_state.operators import LLMExtractOperator, RetrieverOperator
from spc_state.operators.extract_llm import _SCHEMA_HINT
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.source_types import SourceType
from spc_state.store import RunPaths

DOCUMENT = (
    "TitanCorp announces record quarterly results. Revenue grew 41% year over "
    "year, the strongest quarter in the company's history. Management expects "
    "the momentum to continue through the next fiscal year."
)

QUOTE = "Revenue grew 41% year over year"
SECOND_QUOTE = "Management expects the momentum to continue"


def _payload(*, reliability: str = "high") -> str:
    """An extraction the model graded `high`, under-confident on both claims.

    Under-confident on purpose: the Retriever only opens a gap for a claim
    below the weak-confidence threshold, so this is the case where the
    reliability of its evidence decides whether a question gets asked.
    """
    return json.dumps(
        {
            "claims": [
                {
                    "text": "TitanCorp's revenue grew sharply.",
                    "claim_type": "factual_claim",
                    "epistemic_status": "observed",
                    "confidence": 0.6,
                    "evidence_quote": QUOTE,
                    "evidence_reliability": reliability,
                    "assumption": None,
                },
                {
                    "text": "The growth will continue next year.",
                    "claim_type": "predictive_claim",
                    "epistemic_status": "inferred",
                    "confidence": 0.55,
                    "evidence_quote": SECOND_QUOTE,
                    "evidence_reliability": reliability,
                    "assumption": None,
                },
            ]
        }
    )


def _full_patch(*, reliability: str = "high") -> str:
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
                        "epistemic_status": "observed",
                        "confidence": 0.6,
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
                        "reliability": reliability,
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


def _clock() -> FixedClock:
    start = dt.datetime(2026, 9, 12, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(20)])


def _extract(tmp_path: Path, payload: str, source_type: SourceType | str | None):
    """Run extraction alone and return the committed state."""
    clock = _clock()
    kwargs = {} if source_type is None else {"source_type": source_type}
    operator = LLMExtractOperator(
        MockProvider([payload], provider="fake", model="fake-extract-v0"),
        input_text=DOCUMENT,
        clock=clock,
        **kwargs,
    )
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="reliability"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_x", project_id="p", name="TitanCorp", now=clock.now()
        ),
        operators=[operator],
        input_text=DOCUMENT,
    )
    assert result.final_state.state_version == 1, "the extraction must have committed"
    return result.final_state


# ---------------------------------------------------------------------------
# the declaration decides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        (SourceType.PRESS_RELEASE, Reliability.LOW),
        (SourceType.NEWS_REPORT, Reliability.MEDIUM),
        (SourceType.REGULATORY_FILING, Reliability.HIGH),
    ],
    ids=["press_release", "news_report", "regulatory_filing"],
)
def test_declared_source_sets_the_reliability_of_every_span(
    tmp_path: Path, source_type: SourceType, expected: Reliability
) -> None:
    state = _extract(tmp_path, _payload(), source_type)
    assert state.evidence
    assert {e.reliability for e in state.evidence.values()} == {expected}
    assert {e.source_type for e in state.evidence.values()} == {source_type.value}


def test_an_undeclared_document_is_medium(tmp_path: Path) -> None:
    """No declaration is not a reason to distrust — but it is not a promotion."""
    state = _extract(tmp_path, _payload(), None)
    assert {e.reliability for e in state.evidence.values()} == {Reliability.MEDIUM}
    assert {e.source_type for e in state.evidence.values()} == {"unclassified"}


def test_the_models_own_grade_is_ignored(tmp_path: Path) -> None:
    """The regression this change exists for.

    The payload asserts `high` for both spans, as the live press-release run
    really did. The declared source decides instead, so the extraction cannot
    exempt itself from scrutiny — and the same payload read as a filing is not
    dragged down either.
    """
    low = _extract(tmp_path / "a", _payload(reliability="high"), SourceType.PRESS_RELEASE)
    assert {e.reliability for e in low.evidence.values()} == {Reliability.LOW}

    high = _extract(tmp_path / "b", _payload(reliability="low"), SourceType.COURT_RECORD)
    assert {e.reliability for e in high.evidence.values()} == {Reliability.HIGH}


def test_the_model_is_no_longer_asked_to_grade_its_own_source(tmp_path: Path) -> None:
    """Asking for a field we discard would waste tokens and mislead a reader."""
    assert "evidence_reliability" not in _SCHEMA_HINT


def test_a_model_authored_patch_cannot_keep_its_own_high(tmp_path: Path) -> None:
    """The passthrough route is the same rule, the other way in.

    A full patch skips assembly, so without this it would carry whatever
    reliability the model wrote — the one route where self-promotion still
    worked.
    """
    state = _extract(tmp_path, _full_patch(reliability="high"), SourceType.PRESS_RELEASE)
    evidence = next(iter(state.evidence.values()))
    assert evidence.reliability is Reliability.LOW
    assert evidence.source_type == SourceType.PRESS_RELEASE.value
    assert evidence.quote_or_span == QUOTE, "only the weighting changed"


# ---------------------------------------------------------------------------
# the consequence: the Retriever wakes up
# ---------------------------------------------------------------------------


def _gap_questions(tmp_path: Path, source_type: SourceType) -> list[str]:
    """Extract under `source_type`, then run the Retriever over what committed."""
    clock = _clock()
    operators = [
        LLMExtractOperator(
            MockProvider([_payload()], provider="fake", model="fake-extract-v0"),
            input_text=DOCUMENT,
            clock=clock,
            source_type=source_type,
        ),
        RetrieverOperator(clock=clock),
    ]
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="gaps"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_x", project_id="p", name="TitanCorp", now=clock.now()
        ),
        operators=operators,
        input_text=DOCUMENT,
    )
    final = result.final_state
    assert final.claims, "the extraction must have committed claims to question"
    return [q.text for q in final.questions.values()]


def test_a_press_release_wakes_the_retriever(tmp_path: Path) -> None:
    """Under-confident claims on an interested source get questioned."""
    questions = _gap_questions(tmp_path, SourceType.PRESS_RELEASE)
    assert len(questions) == 2
    assert all("stronger source" in q for q in questions)


def test_the_same_claims_from_a_filing_are_not_questioned(tmp_path: Path) -> None:
    """The contrast that proves the declaration is doing the work.

    Identical document, identical model output, identical confidences — only
    the declared source differs, and it decides whether the pipeline goes
    looking for corroboration.
    """
    assert _gap_questions(tmp_path, SourceType.REGULATORY_FILING) == []


def test_an_undeclared_document_is_still_questioned(tmp_path: Path) -> None:
    """Silence must be the cautious answer, not the permissive one.

    Before this change the model's self-assigned `high` silenced these same
    questions. Saying nothing must not buy that silence back.
    """
    assert len(_gap_questions(tmp_path, SourceType.UNCLASSIFIED)) == 2
