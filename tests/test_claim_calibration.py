"""T16 — a claim is not certain because the document says so.

T14 stopped the model grading its own sources; T15 stopped it grading its own
recommendation. The extractor still set `Claim.confidence` itself, and across
five real runs **32 of 48 claims committed at exactly 1.00**. The mechanism was
one confusion, visible in the data: in every cassette the claims marked
`observed` and the claims at 1.00 were the *same set*. The model was reading "I
can quote this" as "this is certain" — but a verbatim span establishes that the
**document** says so.

`CalibrationOperator` now damps a claim by the source under it, using the same
factors it already applies one layer up. These tests pin that, and they pin the
decision that change forced: the damping happens **once**. The recommendation
must come out exactly where T15 alone put it, not discounted twice by two rules
that never agreed to meet.

`tests/test_calibration.py` covers the recommendation half.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from spc_state.analyze import run_analysis
from spc_state.models import (
    Claim,
    EpistemicStatus,
    Evidence,
    Hypothesis,
    Reliability,
    SemanticState,
    StateStatus,
)
from spc_state.operators import CalibrationOperator
from spc_state.operators.calibration import RELIABILITY_FACTOR
from spc_state.providers import ReplayProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.source_types import SourceType
from spc_state.store import RunPaths

NOW = dt.datetime(2026, 9, 12, tzinfo=dt.UTC)

FIXTURES = Path(__file__).parent / "fixtures"
DOCUMENT_PATH = FIXTURES / "live_document.txt"
CASSETTE_PATH = FIXTURES / "cassettes" / "analyze_five_stage.json"


def _clock() -> FixedClock:
    return FixedClock([NOW + dt.timedelta(seconds=10 * i) for i in range(40)])


def _state(claims: list[Claim], evidence: list[Evidence]) -> SemanticState:
    """A committed v1 state holding claims and the spans they cite.

    No hypothesis: these tests are about the claim layer on its own.
    """
    base = bootstrap_state(state_id="sr", project_id="p", name="n", now=NOW)
    return base.model_copy(
        update={
            "state_version": 1,
            "status": StateStatus.ACTIVE,
            "claims": {c.id: c for c in claims},
            "evidence": {e.id: e for e in evidence},
        }
    )


def _claim(cid: str, confidence: float, evidence: list[str]) -> Claim:
    return Claim(
        id=cid,
        # The status the model reaches for whenever it can quote something —
        # and, before T16, always at 1.00.
        text=f"Claim {cid}.",
        epistemic_status=EpistemicStatus.OBSERVED,
        confidence=confidence,
        supporting_evidence=evidence,
    )


def _evidence(eid: str, reliability: Reliability) -> Evidence:
    return Evidence(
        id=eid,
        source_type="press_release",
        source_id="doc",
        quote_or_span=f"span {eid}",
        reliability=reliability,
    )


def _calibrate(root: Path, state: SemanticState):
    runtime = Runtime(paths=RunPaths(root=root, run_id="claims"), clock=_clock())
    return runtime.run(
        initial_state=state, operators=[CalibrationOperator(clock=_clock())]
    )


# ---------------------------------------------------------------------------
# a claim is no more certain than its source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reliability", "expected"),
    [(Reliability.HIGH, 1.0), (Reliability.MEDIUM, 0.8), (Reliability.LOW, 0.6)],
    ids=["filing", "news_report", "press_release"],
)
def test_certainty_survives_only_where_the_source_can_carry_it(
    tmp_path: Path, reliability: Reliability, expected: float
) -> None:
    """The defect, as a test: 1.00 off a press release cannot stand.

    Same claim, same proposed confidence, three sources. A filing can carry
    certainty; a press release cannot, whatever the model said.
    """
    state = _state(
        [_claim("claim_001", 1.0, ["ev_001"])], [_evidence("ev_001", reliability)]
    )
    final = _calibrate(tmp_path, state).final_state
    assert final.claims["claim_001"].confidence == expected


def test_an_accountable_source_leaves_a_claim_alone(tmp_path: Path) -> None:
    """`HIGH` carries a claim intact, so a filing's claims are never touched."""
    state = _state(
        [_claim("claim_001", 0.4, ["ev_001"])], [_evidence("ev_001", Reliability.HIGH)]
    )
    result = _calibrate(tmp_path, state)
    assert result.final_state.claims["claim_001"].confidence == 0.4
    assert result.final_state.transform_log[-1].write_set == []


def test_an_already_modest_claim_is_still_discounted(tmp_path: Path) -> None:
    """The design decision, stated where it can be argued with.

    A claim at 0.40 on a press release commits at 0.24, not 0.40 on the
    grounds that it was already below the factor. The two numbers measure
    independent things — the model's confidence is about the *content* ("will
    these synergies materialise?"), the factor is about the *source* ("who is
    telling us, and do they benefit?") — so they compose rather than one
    clipping the other. A company's own estimate of an uncertain outcome is
    worth less than a disinterested party's identical estimate.

    The cost is that every claim from a non-`HIGH` source moves, not only the
    overconfident ones. That is the trade this rule takes.
    """
    state = _state(
        [_claim("claim_001", 0.4, ["ev_001"])], [_evidence("ev_001", Reliability.LOW)]
    )
    final = _calibrate(tmp_path, state).final_state
    assert final.claims["claim_001"].confidence == 0.24


def test_claim_confidence_is_never_raised(tmp_path: Path) -> None:
    """A well-sourced claim the model was modest about stays modest.

    Inventing certainty is the failure mode this removes, not a second thing
    for it to do.
    """
    state = _state(
        [_claim("claim_001", 0.3, ["ev_001"])], [_evidence("ev_001", Reliability.HIGH)]
    )
    final = _calibrate(tmp_path, state).final_state
    assert final.claims["claim_001"].confidence == 0.3


def test_an_unsourced_claim_is_damped_like_the_weakest_source(
    tmp_path: Path,
) -> None:
    """Citing nothing is treated as the lowest tier, not as zero."""
    state = _state([_claim("claim_001", 1.0, [])], [])
    final = _calibrate(tmp_path, state).final_state
    assert final.claims["claim_001"].confidence == 0.6


def test_the_best_span_a_claim_cites_decides_its_ceiling(tmp_path: Path) -> None:
    """One solid source grounds a claim; a weaker one beside it is not a taint."""
    state = _state(
        [_claim("claim_001", 1.0, ["ev_low", "ev_high"])],
        [
            _evidence("ev_low", Reliability.LOW),
            _evidence("ev_high", Reliability.HIGH),
        ],
    )
    final = _calibrate(tmp_path, state).final_state
    assert final.claims["claim_001"].confidence == 1.0


def test_every_claim_cap_records_the_source_that_bound_it(tmp_path: Path) -> None:
    """The same accountability the recommendation cap carries.

    A number that moves with no reason in the receipt is the thing this repo
    exists not to do — and the reason has to say what bound it, not merely
    that something did.
    """
    state = _state(
        [_claim("claim_001", 1.0, ["ev_001"])], [_evidence("ev_001", Reliability.LOW)]
    )
    result = _calibrate(tmp_path, state)
    record = result.final_state.transform_log[-1]

    (change,) = record.confidence_changes
    assert change.object_id == "claim_001"
    assert (change.from_value, change.to_value) == (1.0, 0.6)
    reason = change.reason or ""
    assert "low-reliability evidence" in reason
    assert "1.00" in reason, "the number it was stated at is on the record too"
    assert "60%" in reason, "and the factor that moved it"

    (update,) = result.steps[0].patch.update_objects
    assert (update.object_id, update.field) == ("claim_001", "confidence")


def test_claims_are_capped_independently_of_each_other(tmp_path: Path) -> None:
    """Each claim answers for its own source, not for the worst in the state."""
    state = _state(
        [
            _claim("claim_weak", 1.0, ["ev_low"]),
            _claim("claim_solid", 1.0, ["ev_high"]),
        ],
        [
            _evidence("ev_low", Reliability.LOW),
            _evidence("ev_high", Reliability.HIGH),
        ],
    )
    final = _calibrate(tmp_path, state).final_state
    assert final.claims["claim_weak"].confidence == 0.6
    assert final.claims["claim_solid"].confidence == 1.0


# ---------------------------------------------------------------------------
# the decision T16 forced: damp once, not twice
# ---------------------------------------------------------------------------


def _with_hypothesis(claims: list[Claim], evidence: list[Evidence]) -> SemanticState:
    hypothesis = Hypothesis(
        id="hyp_001",
        text="Proceed.",
        confidence=0.95,
        supporting_claims=[c.id for c in claims],
    )
    state = _state(claims, evidence)
    return state.model_copy(update={"hypotheses": {hypothesis.id: hypothesis}})


def test_the_reliability_discount_is_applied_exactly_once(tmp_path: Path) -> None:
    """The arithmetic the "damp once" decision settles.

    A claim stated at 1.00 on a press release carries 0.60, and a
    recommendation resting on it carries 0.60 — not 0.36. Applying the factor
    at both layers would be two rules meeting by accident rather than a
    position anyone took.
    """
    state = _with_hypothesis(
        [_claim("claim_001", 1.0, ["ev_001"])], [_evidence("ev_001", Reliability.LOW)]
    )
    final = _calibrate(tmp_path, state).final_state
    assert final.claims["claim_001"].confidence == 0.6
    assert final.hypotheses["hyp_001"].confidence == 0.6


def test_the_recommendation_reads_the_capped_claim_not_the_proposed_one(
    tmp_path: Path,
) -> None:
    """Order inside the patch is load-bearing, so it is asserted.

    The weakest claim is capped from 0.90 to 0.54; the recommendation must take
    0.54, the value after that cap. Reading the pre-cap 0.90 would leave the
    recommendation above what the state now holds.
    """
    state = _with_hypothesis(
        [
            _claim("claim_001", 1.0, ["ev_high"]),
            _claim("claim_002", 0.9, ["ev_low"]),
        ],
        [
            _evidence("ev_high", Reliability.HIGH),
            _evidence("ev_low", Reliability.LOW),
        ],
    )
    result = _calibrate(tmp_path, state)
    final = result.final_state
    assert final.claims["claim_002"].confidence == 0.54
    assert final.hypotheses["hyp_001"].confidence == 0.54

    reason = next(
        c.reason
        for c in final.transform_log[-1].confidence_changes
        if c.object_id == "hyp_001"
    )
    assert "claim_002" in (reason or "")
    assert "0.54" in (reason or ""), "the reason quotes the calibrated value"


# ---------------------------------------------------------------------------
# against real recorded output
# ---------------------------------------------------------------------------


def _replay(tmp_path: Path, source_type: SourceType):
    document = DOCUMENT_PATH.read_text(encoding="utf-8")
    provider = ReplayProvider.from_path(CASSETTE_PATH, document=document)
    return run_analysis(
        provider,
        document,
        RunPaths(root=tmp_path, run_id="replay"),
        clock=_clock(),
        source_type=source_type,
    )


def test_no_claim_from_a_press_release_commits_at_certainty(tmp_path: Path) -> None:
    """The measured defect, held against output a real model produced.

    Six of this recording's twelve claims were proposed at exactly 1.00, every
    one of them `observed`. None of them can commit there.
    """
    result = _replay(tmp_path, SourceType.PRESS_RELEASE)
    claims = result.run.final_state.claims
    assert claims

    proposed = result.run.steps[0].next_state
    assert proposed is not None
    assert any(c.confidence == 1.0 for c in proposed.claims.values()), (
        "this fixture must really contain the 1.00 spike, or it proves nothing"
    )
    # Derived from the factor, not written down: the strongest a low-reliability
    # claim can reach, whatever the model proposed this recording.
    ceiling = RELIABILITY_FACTOR[Reliability.LOW]
    assert max(c.confidence for c in claims.values()) <= ceiling
    assert not any(c.confidence == 1.0 for c in claims.values())


def test_the_same_recording_read_as_a_filing_keeps_its_certainty(
    tmp_path: Path,
) -> None:
    """The contrast that proves the declaration is doing the work.

    A regulatory filing can carry a claim at 1.00, and the operator leaves
    those alone — so this is a source-sensitive cap, not a blanket haircut.
    """
    result = _replay(tmp_path, SourceType.REGULATORY_FILING)
    state = result.run.final_state
    # The state calibration was handed — after the critic, which legitimately
    # adjusts claims of its own and is not what this test is about.
    before = result.run.steps[-2].next_state
    assert before is not None

    # Calibration changed nothing: every claim commits at what it arrived with.
    assert {cid: c.confidence for cid, c in state.claims.items()} == {
        cid: c.confidence for cid, c in before.claims.items()
    }
    assert any(c.confidence == 1.0 for c in state.claims.values()), (
        "a filing must really carry certainty here, or the contrast proves nothing"
    )
    claim_caps = [
        c
        for c in state.transform_log[-1].confidence_changes
        if c.object_id.startswith("claim_")
    ]
    assert claim_caps == [], "nothing to correct on an accountable source"


@pytest.mark.parametrize(
    "source_type",
    [SourceType.PRESS_RELEASE, SourceType.REGULATORY_FILING],
    ids=["press_release", "regulatory_filing"],
)
def test_the_factor_reaches_the_recommendation_exactly_once(
    tmp_path: Path, source_type: SourceType
) -> None:
    """The no-double-discount guard, stated as the invariant rather than a number.

    The committed recommendation must be exactly the weakest committed claim it
    cites. If the reliability factor were applied at both layers it would land
    below that — 0.36 where the claims say 0.60 — and this fails.

    Written this way on purpose: the earlier version pinned 0.60 and 0.85, which
    said nothing about the rule and broke on the next re-record.
    """
    state = _replay(tmp_path, source_type).run.final_state
    lead = state.hypotheses["hyp_001"]
    assert lead.supporting_claims

    weakest = min(state.claims[cid].confidence for cid in lead.supporting_claims)
    assert lead.confidence == weakest
