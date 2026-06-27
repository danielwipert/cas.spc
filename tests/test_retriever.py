"""Retriever operator: flag evidence gaps as open questions (spec §8.3 p4)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from spc_state.models import (
    Claim,
    EpistemicStatus,
    Evidence,
    PatchStatus,
    Reliability,
    SemanticState,
    StateStatus,
)
from spc_state.operators import RetrieverOperator
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.runtime.commit import commit_patch
from spc_state.store import RunPaths

NOW = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)


def _clock() -> FixedClock:
    return FixedClock([NOW + dt.timedelta(seconds=10 * i) for i in range(20)])


def _state_with_claims() -> SemanticState:
    """v1 with: a well-evidenced claim, a no-evidence claim, a weak/low-rel claim."""
    base = bootstrap_state(state_id="sr", project_id="p", name="n", now=NOW)
    grounded = Claim(
        id="claim_solid",
        text="Strongly grounded claim.",
        epistemic_status=EpistemicStatus.OBSERVED,
        confidence=0.9,
        supporting_evidence=["ev_high"],
    )
    bare = Claim(
        id="claim_bare",
        text="Claim with no evidence at all.",
        epistemic_status=EpistemicStatus.INFERRED,
        confidence=0.6,
        supporting_evidence=[],
    )
    weak = Claim(
        id="claim_weak",
        text="Under-confident claim on a weak source.",
        epistemic_status=EpistemicStatus.INFERRED,
        confidence=0.55,
        supporting_evidence=["ev_low"],
    )
    ev_high = Evidence(
        id="ev_high",
        source_type="input_document",
        source_id="doc",
        quote_or_span="solid quote",
        reliability=Reliability.HIGH,
    )
    ev_low = Evidence(
        id="ev_low",
        source_type="input_document",
        source_id="doc",
        quote_or_span="shaky quote",
        reliability=Reliability.LOW,
    )
    return base.model_copy(
        update={
            "state_version": 1,
            "status": StateStatus.ACTIVE,
            "claims": {c.id: c for c in (grounded, bare, weak)},
            "evidence": {ev_high.id: ev_high, ev_low.id: ev_low},
        }
    )


def _run(root: Path, state: SemanticState):
    runtime = Runtime(paths=RunPaths(root=root, run_id="retr"), clock=_clock())
    return runtime.run(initial_state=state, operators=[RetrieverOperator(clock=_clock())])


def test_flags_gaps_but_not_grounded_claims(tmp_path: Path) -> None:
    result = _run(tmp_path, _state_with_claims())
    final = result.final_state
    assert final.state_version == 2
    # The grounded claim is not questioned; the two gaps are.
    needs = {
        (r.source, r.target)
        for r in final.relations
        if r.predicate == "needs_evidence"
    }
    flagged = {target for _src, target in needs}
    assert flagged == {"claim_bare", "claim_weak"}
    assert "claim_solid" not in flagged


def test_no_evidence_claim_is_high_priority(tmp_path: Path) -> None:
    final = _run(tmp_path, _state_with_claims()).final_state
    # Find the question linked to the no-evidence claim.
    q = next(
        q for q in final.questions.values() if "claim_bare" in q.linked_objects
    )
    assert q.priority.value == "high"
    assert "no supporting evidence" in q.text


def test_clean_state_flags_nothing(tmp_path: Path) -> None:
    # A state whose only claim is well-grounded yields no gap questions.
    base = bootstrap_state(state_id="s", project_id="p", name="n", now=NOW)
    claim = Claim(
        id="claim_ok",
        text="Solid.",
        epistemic_status=EpistemicStatus.OBSERVED,
        confidence=0.9,
        supporting_evidence=["ev"],
    )
    ev = Evidence(
        id="ev",
        source_type="input_document",
        source_id="doc",
        quote_or_span="q",
        reliability=Reliability.HIGH,
    )
    state = base.model_copy(
        update={
            "state_version": 1,
            "claims": {claim.id: claim},
            "evidence": {ev.id: ev},
        }
    )
    final = _run(tmp_path, state).final_state
    assert not any(r.predicate == "needs_evidence" for r in final.relations)


def test_retriever_does_not_mutate_state(tmp_path: Path) -> None:
    # Proposing a patch must not touch the input state object.
    state = _state_with_claims()
    before = state.model_dump_json()
    op = RetrieverOperator(clock=_clock())
    from spc_state.projection import build_projection

    projection = build_projection(state, perspective=op.perspective, goal=op.goal)
    patch = op.propose(state, projection)
    assert state.model_dump_json() == before  # unchanged
    assert patch.status == PatchStatus.PROPOSED
    # And the patch applies cleanly to produce the next version.
    nxt = commit_patch(state, patch.model_copy(update={"status": PatchStatus.COMMITTED}), now=NOW)
    assert nxt.state_version == 2
