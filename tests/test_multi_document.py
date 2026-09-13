"""T18 — several sources, one semantic state.

A run could only ever hold one document, which quietly capped what the whole
pipeline could do. The verifier looked for contradictions inside a single press
release, where a company does not contradict itself. T14's reliability tiers
never arbitrated anything, because every span in a run shared one source type.
And nothing could ever emit `VERIFIED`, since corroboration needs a second
source to corroborate *with*.

The blocker was mechanical: the extractor mints `claim_001`, `ev_001`,
`assumption_001` per run, and L2 rejects a second extraction into the same
state with `L2.DUPLICATE_OBJECT_ID` — correctly. Each extraction now mints in
its own namespace, and everything downstream reads the combined state without
changing at all.

This is the plumbing only. Recognising that a claim from one source and a claim
from another assert *the same thing* is a separate operator and a harder
problem; these tests pin what must be true before it can be written.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.analyze import SourceDocument, build_analysis_operators, run_analysis
from spc_state.models import Reliability
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock
from spc_state.source_types import SourceType
from spc_state.store import RunPaths

RELEASE = (
    "TitanCorp announces the acquisition of Harbor Systems. Revenue grew 41% "
    "year over year. The transaction is not subject to any conditions."
)
DETERMINATION = (
    "The Division has completed its review of the proposed acquisition of "
    "Harbor Systems by TitanCorp. The transaction remains subject to state "
    "regulatory clearance."
)


def _clock() -> FixedClock:
    start = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=10 * i) for i in range(60)])


def _extraction(text: str, quote: str, confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "text": text,
                    "claim_type": "factual_claim",
                    "epistemic_status": "reported",
                    "confidence": confidence,
                    "evidence_quote": quote,
                    "assumption": None,
                }
            ]
        }
    )


def _run(tmp_path: Path, *, extras: list[SourceDocument], source_type: SourceType):
    """Two extractions only — the later stages are exercised elsewhere."""
    script = [
        _extraction("TitanCorp is acquiring Harbor Systems.", "Revenue grew 41%"),
        _extraction(
            "The acquisition still needs state clearance.",
            "The transaction remains subject to state regulatory clearance",
        ),
    ]
    return run_analysis(
        MockProvider(script, provider="fake", model="fake-extract-v0"),
        RELEASE,
        RunPaths(root=tmp_path, run_id="multi"),
        clock=_clock(),
        source_type=source_type,
        extract_only=True,
        extra_documents=extras,
    )


# ---------------------------------------------------------------------------
# the mechanics
# ---------------------------------------------------------------------------


def test_a_second_document_commits_into_the_same_state(tmp_path: Path) -> None:
    """Two extractions, one state, two committed versions."""
    result = _run(
        tmp_path,
        extras=[
            SourceDocument(DETERMINATION, SourceType.REGULATORY_DETERMINATION)
        ],
        source_type=SourceType.PRESS_RELEASE,
    )
    final = result.run.final_state
    assert final.state_version == 2, "one committed patch per source"
    assert len(final.claims) == 2
    assert len(final.evidence) == 2


def test_each_source_mints_ids_in_its_own_namespace(tmp_path: Path) -> None:
    """The mechanical blocker, and the reason L2 was refusing the second pass.

    `claim_001` is taken the moment the first document commits, so without a
    namespace the second extraction is rejected as a duplicate id — correctly.
    """
    final = _run(
        tmp_path,
        extras=[
            SourceDocument(DETERMINATION, SourceType.REGULATORY_DETERMINATION)
        ],
        source_type=SourceType.PRESS_RELEASE,
    ).run.final_state

    assert set(final.claims) == {"claim_001", "d2_claim_001"}
    assert set(final.evidence) == {"ev_001", "d2_ev_001"}


def test_each_source_keeps_its_own_weight(tmp_path: Path) -> None:
    """The point of the exercise: reliability is now per document.

    Until this existed a run declared one source type for everything, so T14's
    tiers never actually arbitrated between two sources — which is the only
    place they mean anything.
    """
    final = _run(
        tmp_path,
        extras=[
            SourceDocument(DETERMINATION, SourceType.REGULATORY_DETERMINATION)
        ],
        source_type=SourceType.PRESS_RELEASE,
    ).run.final_state

    assert final.evidence["ev_001"].reliability is Reliability.LOW
    assert final.evidence["ev_001"].source_type == "press_release"
    assert final.evidence["d2_ev_001"].reliability is Reliability.HIGH
    assert final.evidence["d2_ev_001"].source_type == "regulatory_determination"


def test_each_source_is_separately_attributable(tmp_path: Path) -> None:
    """An auditor must be able to say which document a span came from."""
    final = _run(
        tmp_path,
        extras=[
            SourceDocument(DETERMINATION, SourceType.REGULATORY_DETERMINATION)
        ],
        source_type=SourceType.PRESS_RELEASE,
    ).run.final_state

    assert final.evidence["ev_001"].source_id == "doc_001"
    assert final.evidence["d2_ev_001"].source_id == "doc_002"
    transforms = [t.id for t in final.transform_log]
    assert transforms == ["transform_extract_001", "transform_extract_002"]


def test_provenance_is_checked_against_the_right_document(tmp_path: Path) -> None:
    """Each extraction verifies its quote against *its own* source (T8).

    The second document's quote is not in the first, and vice versa. If the
    operators shared one input text, one of them would reject a faithful span.
    """
    final = _run(
        tmp_path,
        extras=[
            SourceDocument(DETERMINATION, SourceType.REGULATORY_DETERMINATION)
        ],
        source_type=SourceType.PRESS_RELEASE,
    ).run.final_state

    first = final.evidence["ev_001"]
    second = final.evidence["d2_ev_001"]
    assert RELEASE[int(first.location["start"]) : int(first.location["end"])] == (
        first.quote_or_span
    )
    assert DETERMINATION[
        int(second.location["start"]) : int(second.location["end"])
    ] == second.quote_or_span


# ---------------------------------------------------------------------------
# the stages that get it for free, and the one that does not
# ---------------------------------------------------------------------------


def test_the_later_stages_are_unchanged_and_see_every_source(tmp_path: Path) -> None:
    """No downstream operator needed touching — they read committed state.

    One extract stage per document, then the same six-stage tail as before.
    """
    operators = build_analysis_operators(
        MockProvider(["unused"], provider="fake", model="m"),
        RELEASE,
        clock=_clock(),
        source_type=SourceType.PRESS_RELEASE,
        extra_documents=[
            SourceDocument(DETERMINATION, SourceType.REGULATORY_DETERMINATION),
            SourceDocument("A third source.", SourceType.NEWS_REPORT),
        ],
    )
    names = [op.name for op in operators]
    assert names == [
        "llm_extract_transform",
        "llm_extract_transform",
        "llm_extract_transform",
        "corroboration_transform",
        "llm_planner_transform",
        "llm_critic_transform",
        "retriever_transform",
        "contradiction_transform",
        "calibration_transform",
    ]


def test_a_single_document_run_is_completely_unchanged(tmp_path: Path) -> None:
    """The default path must not move: no prefix, no extra stage, same ids.

    Every committed cassette and every earlier run depends on this.
    """
    operators = build_analysis_operators(
        MockProvider(["unused"], provider="fake", model="m"),
        RELEASE,
        clock=_clock(),
        source_type=SourceType.PRESS_RELEASE,
    )
    assert sum(op.name == "llm_extract_transform" for op in operators) == 1

    final = _run(tmp_path, extras=[], source_type=SourceType.PRESS_RELEASE).run.final_state
    assert set(final.claims) == {"claim_001"}
    assert final.state_version == 1
