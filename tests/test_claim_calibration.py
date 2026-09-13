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
import math
from pathlib import Path

import pytest

from spc_state.analyze import run_analysis
from spc_state.models import (
    Claim,
    EpistemicStatus,
    Evidence,
    Hypothesis,
    Perspective,
    Reliability,
    SemanticState,
    StateStatus,
)
from spc_state.operators import CalibrationOperator
from spc_state.operators.calibration import (
    GROUNDING_FACTOR,
    RELIABILITY_FACTOR,
    _claim_reason,
    claim_ceiling,
    claim_factor,
)
from spc_state.projection import build_projection, resolve_view
from spc_state.projection.view import ProjectionView
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


def test_the_same_recording_read_as_a_filing_is_discounted_least(
    tmp_path: Path,
) -> None:
    """The contrast that proves the declaration is doing the work.

    Before T21 this asserted that a filing "keeps its certainty" — calibration
    changed nothing, and claims committed at 1.00. That was the defect: a run
    over two real SEC filings committed 17 of 17 claims at 1.00 and recommended
    proceeding with a contested merger at 100%.

    A filing is still worth more than a press release, and that is what this
    test is for. What it no longer buys is certainty: the claim was *read*, not
    seen, so it carries at most `GROUNDING_FACTOR[REPORTED]` however accountable
    the source. The discount is the grounding one, not the source one — pinned
    here, because a filing falling to the `LOW` factor would be a different and
    much worse bug than the one T21 fixed.
    """
    result = _replay(tmp_path, SourceType.REGULATORY_FILING)
    state = result.run.final_state
    # The state calibration was handed — after the critic, which legitimately
    # adjusts claims of its own and is not what this test is about.
    before = result.run.steps[-2].next_state
    assert before is not None

    grounding = GROUNDING_FACTOR[EpistemicStatus.REPORTED]
    for cid, claim in state.claims.items():
        if claim.epistemic_status is not EpistemicStatus.REPORTED:
            continue
        expected = math.floor(before.claims[cid].confidence * grounding * 100) / 100
        assert claim.confidence == expected, (
            f"{cid}: a reported claim on a filing is damped by grounding alone"
        )

    assert not any(c.confidence == 1.0 for c in state.claims.values()), (
        "nothing read out of a document commits at certainty — the whole of T21"
    )

    reasons = " ".join(
        c.reason or ""
        for c in state.transform_log[-1].confidence_changes
        if c.object_id.startswith("claim_")
    )
    assert "reported" in reasons, "the receipt must say what bound the number"
    assert "high-reliability" not in reasons, (
        "the source did not bind it; saying so would misdirect an auditor"
    )


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


# ---------------------------------------------------------------------------
# T21 — an accountable source is not a certain one
# ---------------------------------------------------------------------------


def _view_of(claim: Claim, evidence: list[Evidence]) -> ProjectionView:
    state = SemanticState(
        state_id="sr",
        project_id="p",
        name="n",
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        claims={claim.id: claim},
        evidence={e.id: e for e in evidence},
    )
    projection = build_projection(
        state, perspective=Perspective.VERIFIER, goal="calibrate"
    )
    return resolve_view(projection, state)


def _ev(eid: str, reliability: Reliability) -> Evidence:
    return Evidence(
        id=eid,
        source_type="input_document",
        source_id="doc_001",
        quote_or_span=f"span {eid}",
        reliability=reliability,
    )


def _c(status: EpistemicStatus, confidence: float, evidence: list[str]) -> Claim:
    return Claim(
        id="claim_001",
        text="A claim.",
        epistemic_status=status,
        confidence=confidence,
        supporting_evidence=evidence,
    )


def test_a_reported_claim_on_an_accountable_source_cannot_be_certain() -> None:
    """The defect T21 exists for, at its smallest.

    17 of 17 claims at 1.00 over two SEC filings, and a 100% recommendation on a
    contested merger, all reduce to this one line being 1.0 before.
    """
    claim = _c(EpistemicStatus.REPORTED, 1.0, ["ev_001"])
    view = _view_of(claim, [_ev("ev_001", Reliability.HIGH)])
    assert claim_ceiling(claim, view) == GROUNDING_FACTOR[EpistemicStatus.REPORTED]
    assert claim_ceiling(claim, view) < 1.0


def test_an_observed_claim_on_the_same_source_is_untouched() -> None:
    """`OBSERVED` is first-hand, so nothing about *reading* discounts it.

    The contrast that shows T21 is a grounding rule and not a blanket haircut.
    """
    claim = _c(EpistemicStatus.OBSERVED, 1.0, ["ev_001"])
    view = _view_of(claim, [_ev("ev_001", Reliability.HIGH)])
    assert claim_ceiling(claim, view) == 1.0


def test_the_two_rules_compose_by_min_and_not_by_product() -> None:
    """The decision T16 settled, re-settled where T21 could have broken it.

    A reported claim on a press release is damped **once**, by the source —
    0.90 x 0.60, not 0.90 x 0.60 x 0.90. Multiplying would drop it to 0.48 for
    no considered reason, which is the double discount T16 ruled out.
    """
    claim = _c(EpistemicStatus.REPORTED, 0.90, ["ev_001"])
    view = _view_of(claim, [_ev("ev_001", Reliability.LOW)])
    low = RELIABILITY_FACTOR[Reliability.LOW]
    assert claim_ceiling(claim, view) == round(0.90 * low, 2)
    assert claim_factor(claim, view) == (low, "source")


@pytest.mark.parametrize(
    ("reliability", "binds"),
    [
        (Reliability.HIGH, "grounding"),
        (Reliability.MEDIUM, "source"),
        (Reliability.LOW, "source"),
    ],
)
def test_the_harder_of_the_two_rules_binds(
    reliability: Reliability, binds: str
) -> None:
    """Only the `HIGH` tier changed, which is the tier that was wrong."""
    claim = _c(EpistemicStatus.REPORTED, 1.0, ["ev_001"])
    view = _view_of(claim, [_ev("ev_001", reliability)])
    factor, bound_by = claim_factor(claim, view)
    assert bound_by == binds
    assert factor == min(
        RELIABILITY_FACTOR[reliability], GROUNDING_FACTOR[EpistemicStatus.REPORTED]
    )


def test_the_grounding_factor_is_pinned() -> None:
    """A constant with no principled derivation, so changing it is deliberate."""
    assert GROUNDING_FACTOR[EpistemicStatus.REPORTED] == 0.9
    assert GROUNDING_FACTOR[EpistemicStatus.OBSERVED] == 1.0


def test_every_epistemic_status_has_a_grounding_factor() -> None:
    """Adding a member to the axis must force a decision, not default silently."""
    assert set(GROUNDING_FACTOR) == set(EpistemicStatus)


def test_the_receipt_names_which_rule_bound_the_number() -> None:
    """An auditor must be able to tell a source cap from a grounding cap."""
    claim = _c(EpistemicStatus.REPORTED, 1.0, ["ev_001"])
    view = _view_of(claim, [_ev("ev_001", Reliability.HIGH)])
    reason = _claim_reason(claim, view, claim_ceiling(claim, view))
    assert "reported" in reason
    assert "high-reliability" not in reason


@pytest.mark.parametrize(
    "source_type",
    [SourceType.REGULATORY_FILING, SourceType.PRESS_RELEASE, SourceType.UNCLASSIFIED],
)
def test_no_committed_claim_reaches_certainty_on_any_source(
    tmp_path: Path, source_type: SourceType
) -> None:
    """The one assertion that would have caught `verify_001`.

    Against real recorded output rather than a hand-built claim: whatever the
    model proposed and whatever the document was declared to be, nothing read
    out of it commits at 1.00 — and neither does the recommendation that rests
    on it. Before T21 a filing produced exactly that, seventeen times over.
    """
    state = _replay(tmp_path, source_type).run.final_state

    certain = [
        cid
        for cid, c in state.claims.items()
        if c.confidence >= 1.0 and c.epistemic_status is EpistemicStatus.REPORTED
    ]
    assert certain == [], f"{source_type.value}: reported claims at certainty"
    assert all(h.confidence < 1.0 for h in state.hypotheses.values()), (
        "a recommendation resting on read claims cannot be certain either"
    )
