"""LLM-backed Planner and Critic: full pipeline on an arbitrary document.

Injected `MockProvider` scripts (no network) drive extract -> plan -> critique
end to end, and isolate the planner/critic behaviours: id filtering, the
hypothesis requirement, confidence updates read from committed state, and
projection-honest critique.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.models import SemanticState
from spc_state.operators import (
    LLMExtractOperator,
    LLMPlannerOperator,
    LLMReviewCriticOperator,
)
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths

DOCUMENT = (
    "A six-month four-day-week pilot cut burnout 20% with flat revenue, though "
    "the pilot ran during a slow quarter."
)

EXTRACTION = {
    "claims": [
        {
            "text": "The four-day week reduced burnout.",
            "epistemic_status": "observed",
            "confidence": 0.85,
            "evidence_quote": "burnout 20%",
            "assumption": None,
        },
        {
            "text": "Revenue neutrality may not generalize.",
            "epistemic_status": "inferred",
            "confidence": 0.6,
            "evidence_quote": "the pilot ran during a slow quarter",
            "assumption": "seasonality drives revenue",
            "assumption_impact": "high",
        },
    ]
}

PLAN = {
    "hypothesis": {
        "text": "Adopt the four-day week permanently with revenue monitoring.",
        "confidence": 0.7,
        "supporting_claims": ["claim_001", "claim_999"],  # 999 is a ghost
    },
    "questions": [
        {
            "text": "Will revenue hold in a busy quarter?",
            "priority": "high",
            "linked_claims": ["claim_002"],
        }
    ],
    "dependencies": [{"claim": "claim_002", "assumption": "assumption_001"}],
}

CRITIQUE = {
    "confidence_updates": [
        {"claim": "claim_002", "new_confidence": 0.45, "reason": "slow-quarter sample"},
        {"claim": "claim_001", "new_confidence": 0.5, "reason": "not in scope"},  # not weak
    ],
    "questions": [
        {
            "text": "Is the burnout effect durable?",
            "priority": "medium",
            "challenges_claim": "claim_002",
        }
    ],
}


def _clock() -> FixedClock:
    start = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=15 * i) for i in range(40)])


def _extracted(root: Path) -> SemanticState:
    """Run the LLM extract to a committed v1 and return it."""
    clock = _clock()
    provider = MockProvider([json.dumps(EXTRACTION)], provider="fake", model="m")
    runtime = Runtime(paths=RunPaths(root=root, run_id="base"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr", project_id="p", name="n", now=clock.now()
        ),
        operators=[LLMExtractOperator(provider, input_text=DOCUMENT, clock=clock)],
        input_text=DOCUMENT,
    )
    return result.final_state


def _run_op(root: Path, state: SemanticState, op, run_id: str):
    runtime = Runtime(paths=RunPaths(root=root, run_id=run_id), clock=_clock())
    return runtime.run(initial_state=state, operators=[op])


def test_full_pipeline_commits_through_critique(tmp_path: Path) -> None:
    clock = _clock()
    # One provider, scripted in call order: extract, plan, critique.
    provider = MockProvider(
        [json.dumps(EXTRACTION), json.dumps(PLAN), json.dumps(CRITIQUE)],
        provider="fake",
        model="m",
    )
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="full"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr", project_id="p", name="n", now=clock.now()
        ),
        operators=[
            LLMExtractOperator(provider, input_text=DOCUMENT, clock=clock),
            LLMPlannerOperator(provider, clock=clock),
            LLMReviewCriticOperator(provider, clock=clock),
        ],
        input_text=DOCUMENT,
    )
    final = result.final_state
    assert final.state_version == 3
    assert len(final.claims) == 2
    assert len(final.hypotheses) == 1
    # The planner question and the critic question both survive.
    assert {"q_plan_001", "q_crit_001"} <= set(final.questions)
    # The critic lowered the weak claim's confidence.
    assert final.claims["claim_002"].confidence == 0.45


def test_planner_drops_unknown_supporting_claims(tmp_path: Path) -> None:
    base = _extracted(tmp_path)
    provider = MockProvider([json.dumps(PLAN)], provider="fake", model="m")
    result = _run_op(tmp_path, base, LLMPlannerOperator(provider, clock=_clock()), "plan")
    hyp = result.final_state.hypotheses["hyp_001"]
    assert hyp.supporting_claims == ["claim_001"]  # ghost claim_999 dropped
    # The dependency relation links the claim to its assumption.
    preds = {(r.source, r.predicate, r.target) for r in result.final_state.relations}
    assert ("claim_002", "depends_on", "assumption_001") in preds


def test_planner_without_hypothesis_does_not_commit(tmp_path: Path) -> None:
    # Hypothesis-less but valid JSON assembles to no patch -> the operator
    # returns that JSON, which fails L1 schema -> REJECT (not a recoverable
    # JSON_DECODE), so nothing commits and the pipeline keeps the prior state.
    base = _extracted(tmp_path)
    no_hyp = json.dumps({"questions": [], "dependencies": []})
    provider = MockProvider([no_hyp], provider="fake", model="m")
    result = _run_op(tmp_path, base, LLMPlannerOperator(provider, clock=_clock()), "p2")
    assert result.final_state.state_version == base.state_version  # nothing committed
    assert result.steps[0].decision.value == "REJECT"


def test_critic_updates_from_committed_confidence(tmp_path: Path) -> None:
    base = _extracted(tmp_path)
    provider = MockProvider([json.dumps(CRITIQUE)], provider="fake", model="m")
    result = _run_op(
        tmp_path, base, LLMReviewCriticOperator(provider, clock=_clock()), "crit"
    )
    final = result.final_state
    # claim_002 (weak, 0.60) is lowered; claim_001 (not in the weak slice) is not.
    assert final.claims["claim_002"].confidence == 0.45
    assert final.claims["claim_001"].confidence == 0.85
    record = final.transform_log[-1]
    change = next(c for c in record.confidence_changes if c.object_id == "claim_002")
    assert change.from_value == 0.6
    assert change.to_value == 0.45


def test_critic_empty_review_commits_noop(tmp_path: Path) -> None:
    base = _extracted(tmp_path)
    empty = json.dumps({"confidence_updates": [], "questions": []})
    provider = MockProvider([empty], provider="fake", model="m")
    result = _run_op(
        tmp_path, base, LLMReviewCriticOperator(provider, clock=_clock()), "crit2"
    )
    # A clean review still commits a new version recording that it ran.
    assert result.final_state.state_version == base.state_version + 1
    assert result.final_state.claims["claim_002"].confidence == 0.6
