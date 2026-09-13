"""T19 — what two sources independently say.

T18 put two documents in one state and the result specified this operator. The
Retriever asked "what stronger source would confirm this?" about a claim the
regulator's determination in the same state answered at 0.95, and nothing
connected them.

The design decision these tests exist to pin: **the operator never touches
confidence**. T15 and T16 hold that calibration only ever lowers, because
raising a number on the strength of its own support is how a pipeline invents
certainty. Corroboration needs no exception — it changes what a claim *rests
on*, and the calibrator's existing rule reprices it. `test_the_calibrator_then_
reprices_the_corroborated_claim` is the one that proves the composition; the
rest guard the pieces.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.models import EpistemicStatus
from spc_state.operators import (
    CalibrationOperator,
    LLMCorroborationOperator,
    LLMExtractOperator,
)
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.source_types import SourceType
from spc_state.store import RunPaths

RELEASE = (
    "TitanCorp announces its acquisition of Harbor Systems. The deal may face "
    "risks from regulatory clearance. Revenue grew 41% year over year."
)
DETERMINATION = (
    "The Division has completed its review and cleared the acquisition of "
    "Harbor Systems by TitanCorp. No further conditions apply."
)


def _clock() -> FixedClock:
    start = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=10 * i) for i in range(80)])


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


def _pairs(*pairs: tuple[str, str]) -> str:
    return json.dumps(
        {
            "corroborations": [
                {
                    "claim_a": a,
                    "claim_b": b,
                    "basis": "both state that the acquisition has cleared review",
                }
                for a, b in pairs
            ]
        }
    )


def _keep(*numbers: int) -> str:
    return json.dumps({"keep": list(numbers)})


def _run(
    tmp_path: Path,
    *,
    corroboration: list[str],
    second_source: SourceType = SourceType.REGULATORY_DETERMINATION,
    first_confidence: float = 0.9,
    calibrate: bool = False,
):
    """Extract two documents, then corroborate (optionally calibrate after)."""
    clock = _clock()
    script = [
        _extraction(
            "The acquisition of Harbor Systems may face regulatory risk.",
            "The deal may face risks from regulatory clearance",
            first_confidence,
        ),
        _extraction(
            "The acquisition of Harbor Systems has cleared regulatory review.",
            "cleared the acquisition of Harbor Systems by TitanCorp",
        ),
        *corroboration,
    ]
    provider = MockProvider(script, provider="fake", model="fake-v0")
    operators = [
        LLMExtractOperator(
            provider,
            input_text=RELEASE,
            clock=clock,
            source_type=SourceType.PRESS_RELEASE,
        ),
        LLMExtractOperator(
            provider,
            input_text=DETERMINATION,
            clock=clock,
            source_type=second_source,
            patch_id="patch_extract_002",
            transform_id="transform_extract_002",
            source_id="doc_002",
            id_prefix="d2_",
        ),
        LLMCorroborationOperator(provider, clock=clock),
    ]
    if calibrate:
        operators.append(CalibrationOperator(clock=clock))
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="corrob"), clock=clock)
    return runtime.run(
        initial_state=bootstrap_state(
            state_id="sr", project_id="p", name="n", now=clock.now()
        ),
        operators=operators,
        input_text=RELEASE,
    )


# ---------------------------------------------------------------------------
# the link
# ---------------------------------------------------------------------------


def test_a_cross_source_pair_is_linked_and_recorded(tmp_path: Path) -> None:
    """The gap T18 found: the answer is now attached to the question's claim."""
    final = _run(
        tmp_path, corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep(1)]
    ).final_state

    relations = [r for r in final.relations if r.predicate == "corroborates"]
    assert len(relations) == 1
    # The better-sourced claim corroborates the weaker, never the reverse: the
    # other direction adds a span that cannot raise anything.
    assert (relations[0].source, relations[0].target) == ("d2_claim_001", "claim_001")

    # The corroborating span now supports the press-release claim.
    assert "d2_ev_001" in final.claims["claim_001"].supporting_evidence
    assert "ev_001" not in final.claims["d2_claim_001"].supporting_evidence


def test_an_accountable_source_promotes_the_claim_to_verified(
    tmp_path: Path,
) -> None:
    """What T17 kept `VERIFIED` in the vocabulary for."""
    final = _run(
        tmp_path, corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep(1)]
    ).final_state
    assert final.claims["claim_001"].epistemic_status is EpistemicStatus.VERIFIED
    assert final.claims["d2_claim_001"].epistemic_status is EpistemicStatus.REPORTED


def test_two_interested_parties_agreeing_is_not_verification(tmp_path: Path) -> None:
    """The rule that keeps `VERIFIED` meaning something.

    Two press releases telling the same story is two interested parties telling
    the same story. The link is still recorded — it is a real fact about
    provenance — but nothing is promoted.
    """
    final = _run(
        tmp_path,
        corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep(1)],
        second_source=SourceType.PRESS_RELEASE,
    ).final_state

    assert [r.predicate for r in final.relations] == ["corroborates"]
    assert all(
        c.epistemic_status is EpistemicStatus.REPORTED for c in final.claims.values()
    )


def test_the_operator_never_touches_confidence(tmp_path: Path) -> None:
    """T15/T16's invariant survives intact — no exception was needed for this."""
    result = _run(
        tmp_path, corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep(1)]
    )
    record = result.final_state.transform_log[-1]
    assert record.transform_type == "corroborate"
    assert record.confidence_changes == []

    before = result.steps[1].next_state
    assert before is not None
    assert {cid: c.confidence for cid, c in result.final_state.claims.items()} == {
        cid: c.confidence for cid, c in before.claims.items()
    }


# ---------------------------------------------------------------------------
# the composition — why no new arithmetic was needed
# ---------------------------------------------------------------------------


def test_the_calibrator_then_reprices_the_corroborated_claim(
    tmp_path: Path,
) -> None:
    """The whole design, in one assertion.

    A press-release claim stated at 0.90 carries 0.54 — T16 discounts it by the
    only source it cites. Once a regulator's span genuinely supports it, the
    best evidence it cites is `HIGH` and the *same untouched rule* lets it carry
    0.90. Corroboration raised nothing; it changed what the claim rests on.
    """
    uncorroborated = _run(
        tmp_path / "a", corroboration=[_pairs(), _keep()], calibrate=True
    ).final_state
    assert uncorroborated.claims["claim_001"].confidence == 0.54

    corroborated = _run(
        tmp_path / "b",
        corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep(1)],
        calibrate=True,
    ).final_state
    assert corroborated.claims["claim_001"].confidence == 0.9


# ---------------------------------------------------------------------------
# precision: what the operator refuses
# ---------------------------------------------------------------------------


def test_the_skeptic_pass_can_reject_every_candidate(tmp_path: Path) -> None:
    """A false corroboration lends one source's authority to another's claim.

    So the second pass defaults to "different claims" — and when it keeps
    nothing, nothing is linked and nothing is promoted.
    """
    final = _run(
        tmp_path, corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep()]
    ).final_state
    assert [r for r in final.relations if r.predicate == "corroborates"] == []
    assert final.claims["claim_001"].epistemic_status is EpistemicStatus.REPORTED


def test_a_same_source_pair_is_dropped_by_the_operator(tmp_path: Path) -> None:
    """A document agreeing with itself corroborates nothing.

    Two *distinct* claims, both from the press release — so the id check that
    rejects self-pairs does not catch this, and only the source check does. The
    instruction tells the model not to; the operator enforces it, because what
    counts as an independent source is not the model's call.
    """
    clock = _clock()
    two_claims = json.dumps(
        {
            "claims": [
                {
                    "text": "The acquisition of Harbor Systems may face regulatory risk.",
                    "claim_type": "factual_claim",
                    "epistemic_status": "reported",
                    "confidence": 0.9,
                    "evidence_quote": "The deal may face risks from regulatory clearance",
                    "assumption": None,
                },
                {
                    "text": "Regulatory clearance is a risk to the Harbor deal.",
                    "claim_type": "factual_claim",
                    "epistemic_status": "reported",
                    "confidence": 0.9,
                    "evidence_quote": "TitanCorp announces its acquisition of Harbor Systems",
                    "assumption": None,
                },
            ]
        }
    )
    provider = MockProvider(
        [
            two_claims,
            _extraction(
                "The acquisition of Harbor Systems has cleared regulatory review.",
                "cleared the acquisition of Harbor Systems by TitanCorp",
            ),
            _pairs(("claim_001", "claim_002")),
            _keep(1),
        ],
        provider="fake",
        model="fake-v0",
    )
    operators = [
        LLMExtractOperator(
            provider,
            input_text=RELEASE,
            clock=clock,
            source_type=SourceType.PRESS_RELEASE,
        ),
        LLMExtractOperator(
            provider,
            input_text=DETERMINATION,
            clock=clock,
            source_type=SourceType.REGULATORY_DETERMINATION,
            patch_id="patch_extract_002",
            transform_id="transform_extract_002",
            source_id="doc_002",
            id_prefix="d2_",
        ),
        LLMCorroborationOperator(provider, clock=clock),
    ]
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="same"), clock=clock)
    final = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr", project_id="p", name="n", now=clock.now()
        ),
        operators=operators,
        input_text=RELEASE,
    ).final_state

    assert {"claim_001", "claim_002"} <= set(final.claims), "both from one source"
    assert [r for r in final.relations if r.predicate == "corroborates"] == []
    assert all(
        c.epistemic_status is EpistemicStatus.REPORTED for c in final.claims.values()
    )


def test_unknown_ids_and_unjustified_pairs_are_dropped(tmp_path: Path) -> None:
    """Only pairs that name real claims and say what they share survive."""
    payload = json.dumps(
        {
            "corroborations": [
                {"claim_a": "claim_001", "claim_b": "claim_999", "basis": "both agree"},
                {"claim_a": "claim_001", "claim_b": "d2_claim_001", "basis": "yes"},
            ]
        }
    )
    final = _run(tmp_path, corroboration=[payload, _keep(1, 2)]).final_state
    assert [r for r in final.relations if r.predicate == "corroborates"] == []


def test_both_calls_are_billed(tmp_path: Path) -> None:
    """The skeptic pass is a real second call (T5) and reaches the ledger."""
    result = _run(
        tmp_path, corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep(1)]
    )
    step = result.steps[-1]
    assert step.usage is not None
    assert step.usage.prompt_tokens > 0


def test_a_typed_field_update_commits_as_its_real_type(tmp_path: Path) -> None:
    """A defect this task found in `commit`, not in the operator.

    A patch arrives as JSON, so an `UpdateObject.to_value` for a typed field is
    whatever JSON could carry — here the string "verified". `model_copy` assigns
    without validating, so committed state held a raw string where an
    `EpistemicStatus` belongs: it compared unequal to the enum, and only a
    pydantic serializer warning much later hinted at it. No operator had
    updated an enum field before, so nothing had caught it.
    """
    final = _run(
        tmp_path, corroboration=[_pairs(("claim_001", "d2_claim_001")), _keep(1)]
    ).final_state
    status = final.claims["claim_001"].epistemic_status
    assert isinstance(status, EpistemicStatus), "not the raw string it arrived as"
    assert status is EpistemicStatus.VERIFIED

    # It survives the round trip state is actually stored through.
    reloaded = type(final).model_validate_json(final.model_dump_json(by_alias=True))
    assert reloaded.claims["claim_001"].epistemic_status is EpistemicStatus.VERIFIED
