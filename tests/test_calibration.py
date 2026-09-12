"""T15 — a recommendation is held to the confidence its support can carry.

The Planner writes a `Hypothesis` at a confidence the model chose, and until
this operator existed nothing re-derived it. The Critic runs next and adjusts
*claims*, but the `CRITIC` projection carries no hypotheses, so the
recommendation was the one object in committed state no operator scrutinised —
and it went stale precisely when the Critic did its job.

The unit tests pin the rule (weakest link, only ever downward, every change
carrying a reason) and the constants, so changing a factor is a deliberate edit
rather than a drift. The replay tests hold it against real recorded output, and
against the contrast that proves the T14 declaration is load-bearing here: the
same run declared a filing keeps its confidence, declared a press release does
not.
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


def _claim(cid: str, confidence: float, evidence: list[str]) -> Claim:
    return Claim(
        id=cid,
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


def _state(
    *,
    hypothesis_confidence: float,
    claims: list[Claim],
    evidence: list[Evidence],
    supporting: list[str] | None = None,
) -> SemanticState:
    """A committed v1 state holding one recommendation and what it cites."""
    hypothesis = Hypothesis(
        id="hyp_001",
        text="Proceed with the transaction.",
        confidence=hypothesis_confidence,
        supporting_claims=[c.id for c in claims] if supporting is None else supporting,
    )
    base = bootstrap_state(state_id="sr", project_id="p", name="n", now=NOW)
    return base.model_copy(
        update={
            "state_version": 1,
            "status": StateStatus.ACTIVE,
            "claims": {c.id: c for c in claims},
            "evidence": {e.id: e for e in evidence},
            "hypotheses": {hypothesis.id: hypothesis},
        }
    )


def _calibrate(root: Path, state: SemanticState):
    """Run the operator through the runtime, as the pipeline does."""
    runtime = Runtime(paths=RunPaths(root=root, run_id="calib"), clock=_clock())
    return runtime.run(
        initial_state=state, operators=[CalibrationOperator(clock=_clock())]
    )


def _lead(state: SemanticState) -> Hypothesis:
    return state.hypotheses["hyp_001"]


def _hypothesis_change(record):
    """The one confidence change on a hypothesis.

    Since T16 the same patch also caps claims, so a caller after *the
    recommendation's* change has to say so rather than unpacking a singleton.
    """
    changes = [c for c in record.confidence_changes if c.object_id.startswith("hyp_")]
    assert len(changes) == 1, f"expected one hypothesis cap, got {len(changes)}"
    return changes[0]


# ---------------------------------------------------------------------------
# the rule: weakest link, damped by the evidence under it
# ---------------------------------------------------------------------------


def test_the_ceiling_is_the_weakest_link_not_an_average(tmp_path: Path) -> None:
    """The design decision, stated as a test.

    Four confident restatements of a press release must not outvote the one
    claim that was actually questioned. An average here would read 0.79 and the
    recommendation would keep its 0.9; the weakest link reads 0.39.
    """
    claims = [
        _claim("claim_001", 1.0, ["ev_low"]),
        _claim("claim_002", 1.0, ["ev_low"]),
        _claim("claim_003", 1.0, ["ev_low"]),
        _claim("claim_004", 0.65, ["ev_low"]),  # the one the critic lowered
    ]
    state = _state(
        hypothesis_confidence=0.9,
        claims=claims,
        evidence=[_evidence("ev_low", Reliability.LOW)],
    )
    final = _calibrate(tmp_path, state).final_state
    # 0.65 * 0.6, floored to two places — not mean(1.0, 1.0, 1.0, 0.65) * 0.6.
    assert _lead(final).confidence == 0.39


@pytest.mark.parametrize(
    ("reliability", "expected"),
    [(Reliability.HIGH, 0.8), (Reliability.MEDIUM, 0.64), (Reliability.LOW, 0.48)],
    ids=["high", "medium", "low"],
)
def test_evidence_reliability_damps_the_ceiling(
    tmp_path: Path, reliability: Reliability, expected: float
) -> None:
    """The T14 link: what a claim is worth depends on where it came from.

    Same claim, same confidence, three sources. Pinned numerically so changing
    a factor in `RELIABILITY_FACTOR` is a deliberate edit.
    """
    state = _state(
        hypothesis_confidence=1.0,
        claims=[_claim("claim_001", 0.8, ["ev_001"])],
        evidence=[_evidence("ev_001", reliability)],
    )
    final = _calibrate(tmp_path, state).final_state
    assert _lead(final).confidence == expected


def test_the_factors_are_ordered_and_only_high_is_lossless() -> None:
    """A weaker source must never be worth more, and never more than the claim."""
    assert RELIABILITY_FACTOR[Reliability.HIGH] == 1.0
    assert (
        RELIABILITY_FACTOR[Reliability.LOW]
        < RELIABILITY_FACTOR[Reliability.MEDIUM]
        < RELIABILITY_FACTOR[Reliability.HIGH]
    )


def test_the_best_span_grounds_a_claim_even_beside_a_weak_one(tmp_path: Path) -> None:
    """Across claims the weakest wins; within a claim the strongest does.

    One solid source is enough to ground a claim — a second, weaker span
    alongside it is corroboration, not contamination.
    """
    state = _state(
        hypothesis_confidence=1.0,
        claims=[_claim("claim_001", 0.9, ["ev_low", "ev_high"])],
        evidence=[
            _evidence("ev_low", Reliability.LOW),
            _evidence("ev_high", Reliability.HIGH),
        ],
    )
    final = _calibrate(tmp_path, state).final_state
    assert _lead(final).confidence == 0.9, "the HIGH span carries it, undamped"


def test_a_claim_with_no_evidence_is_treated_as_the_lowest_tier(
    tmp_path: Path,
) -> None:
    """Unsourced is not worse than sourced-to-an-interested-party.

    Three buckets cannot honestly express a finer distinction, and the
    Retriever already opens a *high* priority gap for exactly these claims.
    """
    state = _state(
        hypothesis_confidence=1.0,
        claims=[_claim("claim_001", 0.5, [])],
        evidence=[],
    )
    final = _calibrate(tmp_path, state).final_state
    assert _lead(final).confidence == 0.3  # 0.5 * the LOW factor


def test_a_recommendation_citing_nothing_gets_zero(tmp_path: Path) -> None:
    """Grounded in nothing should not read as a finding."""
    state = _state(
        hypothesis_confidence=0.95,
        claims=[_claim("claim_001", 1.0, ["ev_001"])],
        evidence=[_evidence("ev_001", Reliability.HIGH)],
        supporting=[],
    )
    final = _calibrate(tmp_path, state).final_state
    assert _lead(final).confidence == 0.0


def test_a_claim_outside_committed_state_grounds_nothing(tmp_path: Path) -> None:
    """A limb the operator cannot resolve is a limb it cannot vouch for."""
    state = _state(
        hypothesis_confidence=0.9,
        claims=[_claim("claim_001", 1.0, ["ev_001"])],
        evidence=[_evidence("ev_001", Reliability.HIGH)],
        supporting=["claim_001", "claim_gone"],
    )
    result = _calibrate(tmp_path, state)
    assert _lead(result.final_state).confidence == 0.0
    change = result.final_state.transform_log[-1].confidence_changes[0]
    assert "claim_gone" in (change.reason or "")


# ---------------------------------------------------------------------------
# it only ever lowers, and always says why
# ---------------------------------------------------------------------------


def test_confidence_is_never_raised(tmp_path: Path) -> None:
    """The rule that holds whatever the constants become.

    Strong support is not a licence to invent certainty — that is the failure
    mode this operator exists to fix, not a second thing for it to do.
    """
    state = _state(
        hypothesis_confidence=0.2,
        claims=[_claim("claim_001", 1.0, ["ev_001"])],
        evidence=[_evidence("ev_001", Reliability.HIGH)],
    )
    result = _calibrate(tmp_path, state)
    assert _lead(result.final_state).confidence == 0.2
    assert result.final_state.transform_log[-1].confidence_changes == []


def test_a_hypothesis_already_within_its_ceiling_is_untouched(
    tmp_path: Path,
) -> None:
    """Exactly at the ceiling is within it — no cosmetic rewrite.

    The claim beneath it is capped in the same patch (T16: 1.00 on a low
    -reliability span cannot stand), which is what sets the hypothesis's
    ceiling at 0.6 — and having reached it, the hypothesis is left alone.
    """
    state = _state(
        hypothesis_confidence=0.6,
        claims=[_claim("claim_001", 1.0, ["ev_001"])],
        evidence=[_evidence("ev_001", Reliability.LOW)],
    )
    result = _calibrate(tmp_path, state)
    assert _lead(result.final_state).confidence == 0.6
    assert result.final_state.transform_log[-1].write_set == ["claim_001"]


def test_every_cap_records_the_claim_that_bound_it(tmp_path: Path) -> None:
    """A number that moves without a reason in the receipt is the thing this
    repo exists not to do."""
    state = _state(
        hypothesis_confidence=0.9,
        claims=[
            _claim("claim_001", 1.0, ["ev_high"]),
            _claim("claim_002", 0.65, ["ev_low"]),
        ],
        evidence=[
            _evidence("ev_high", Reliability.HIGH),
            _evidence("ev_low", Reliability.LOW),
        ],
    )
    result = _calibrate(tmp_path, state)
    record = result.final_state.transform_log[-1]

    change = _hypothesis_change(record)
    assert change.from_value == 0.9
    assert change.to_value == 0.39
    reason = change.reason or ""
    assert "claim_002" in reason, "the binding claim is named, not just the number"
    assert "low-reliability evidence" in reason
    assert "claim_001" not in reason, "the claims that did not bind it are not blamed"

    # The update is on the record as a patch field too, not only as a tally.
    update = next(
        u for u in result.steps[0].patch.update_objects if u.object_id == "hyp_001"
    )
    assert update.field == "confidence"
    assert (update.from_value, update.to_value) == (0.9, 0.39)


def test_the_operator_reads_only_its_projection(tmp_path: Path) -> None:
    """Every id it declares having read must be one the slice really holds."""
    state = _state(
        hypothesis_confidence=0.9,
        claims=[_claim("claim_001", 0.8, ["ev_001"])],
        evidence=[_evidence("ev_001", Reliability.MEDIUM)],
        supporting=["claim_001", "claim_gone"],
    )
    record = _calibrate(tmp_path, state).final_state.transform_log[-1]
    assert record.read_set == ["claim_001", "ev_001", "hyp_001"]
    assert "claim_gone" not in record.read_set


def test_it_costs_nothing_and_replays_identically(tmp_path: Path) -> None:
    """Deterministic and model-free, like the Retriever: no fingerprint, no spend."""
    first = _calibrate(tmp_path / "a", _state(
        hypothesis_confidence=0.9,
        claims=[_claim("claim_001", 0.7, ["ev_001"])],
        evidence=[_evidence("ev_001", Reliability.LOW)],
    ))
    second = _calibrate(tmp_path / "b", _state(
        hypothesis_confidence=0.9,
        claims=[_claim("claim_001", 0.7, ["ev_001"])],
        evidence=[_evidence("ev_001", Reliability.LOW)],
    ))
    assert first.final_state.model_dump_json(
        by_alias=True
    ) == second.final_state.model_dump_json(by_alias=True)

    step = first.steps[0]
    assert step.usage is None and step.fingerprint is None


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


def test_a_press_release_recommendation_commits_below_what_was_proposed(
    tmp_path: Path,
) -> None:
    """The whole point, on output a real model produced.

    The planner proposed 0.85 over a merger press release. Every span under it
    is low-reliability (T14), so the recommendation cannot carry that — and the
    memo now opens with the capped number rather than the proposed one.
    """
    result = _replay(tmp_path, SourceType.PRESS_RELEASE)
    calibrate = result.run.steps[-1]
    assert calibrate.patch is not None
    change = _hypothesis_change(calibrate.patch.transform_record)

    assert change.to_value < change.from_value == 0.85
    assert change.to_value == 0.6
    final = max(
        result.run.final_state.hypotheses.values(), key=lambda h: h.confidence
    )
    assert final.confidence == 0.6

    assert result.memo_path is not None
    assert "_Confidence: 60%._" in result.memo_path.read_text(encoding="utf-8")


def test_the_same_run_declared_a_filing_keeps_its_confidence(
    tmp_path: Path,
) -> None:
    """The contrast that proves the declaration is doing the work.

    Identical document, identical recorded completions, identical claims — only
    the declared source differs. Read as a filing, the support carries 0.85 and
    the operator leaves it alone.
    """
    result = _replay(tmp_path, SourceType.REGULATORY_FILING)
    calibrate = result.run.steps[-1]
    assert calibrate.patch is not None
    assert calibrate.patch.transform_record.confidence_changes == []

    final = max(
        result.run.final_state.hypotheses.values(), key=lambda h: h.confidence
    )
    assert final.confidence == 0.85


def test_the_cap_is_visible_in_the_reasoning_receipt(tmp_path: Path) -> None:
    """An auditor must see the number move, and be able to find out why.

    The receipt renders the transform and the delta; the reason it recorded is
    in committed state beside it. A confidence that changed with neither on the
    record would be exactly the unaccountable number this operator exists to
    remove.
    """
    result = _replay(tmp_path, SourceType.PRESS_RELEASE)
    assert result.artifacts is not None
    receipt = result.artifacts.receipt_path.read_text(encoding="utf-8")

    assert "**calibration_transform** (calibrate)" in receipt
    assert "**changed hypothesis `hyp_001`:** `confidence` 0.85 → 0.6" in receipt

    record = result.run.final_state.transform_log[-1]
    assert record.operator == "calibration_transform"
    assert "Capped at 0.60" in (_hypothesis_change(record).reason or "")
