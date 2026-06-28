"""LLM contradiction detection: conflicts preserved as first-class objects."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.models import (
    Claim,
    Contradiction,
    ContradictionStatus,
    EpistemicStatus,
    SemanticState,
)
from spc_state.operators import LLMContradictionOperator
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths

NOW = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)


def _clock() -> FixedClock:
    return FixedClock([NOW + dt.timedelta(seconds=10 * i) for i in range(20)])


def _state(*claims: Claim, contradictions=()) -> SemanticState:
    base = bootstrap_state(state_id="sr", project_id="p", name="n", now=NOW)
    return base.model_copy(
        update={
            "state_version": 1,
            "claims": {c.id: c for c in claims},
            "contradictions": {k.id: k for k in contradictions},
        }
    )


def _c(cid: str, text: str) -> Claim:
    return Claim(
        id=cid, text=text, epistemic_status=EpistemicStatus.OBSERVED, confidence=0.8
    )


def _run(root: Path, state: SemanticState, script: list[str]):
    provider = MockProvider(script, provider="fake", model="m")
    runtime = Runtime(paths=RunPaths(root=root, run_id="contra"), clock=_clock())
    return runtime.run(
        initial_state=state,
        operators=[LLMContradictionOperator(provider, clock=_clock())],
    )


PAIR = {
    "contradictions": [
        {
            "claim_a": "claim_001",
            "claim_b": "claim_002",
            "conflict": "Revenue cannot both rise and fall in the same quarter.",
            "type": "factual_conflict",
            "severity": "high",
            "resolution_options": ["Re-measure", "Scope by quarter"],
        }
    ]
}


# The verifier (second pass) confirms candidate 1 as a genuine contradiction.
KEEP = {"keep": [1]}
DROP: dict = {"keep": []}


def test_detects_and_commits_contradiction(tmp_path: Path) -> None:
    state = _state(
        _c("claim_001", "Revenue rose in Q3."),
        _c("claim_002", "Revenue fell in Q3."),
    )
    final = _run(tmp_path, state, [json.dumps(PAIR), json.dumps(KEEP)]).final_state
    assert final.state_version == 2
    assert len(final.contradictions) == 1
    k = next(iter(final.contradictions.values()))
    assert {k.claim_a, k.claim_b} == {"claim_001", "claim_002"}
    assert k.status == ContradictionStatus.UNRESOLVED
    assert k.resolution_options == ["Re-measure", "Scope by quarter"]


def test_verifier_rejects_spurious_pair(tmp_path: Path) -> None:
    # Detection proposes a pair; the adversarial verifier judges they can
    # coexist and drops it — nothing is committed.
    state = _state(
        _c("claim_001", "The court issued ruling A."),
        _c("claim_002", "The court issued ruling B."),
    )
    final = _run(tmp_path, state, [json.dumps(PAIR), json.dumps(DROP)]).final_state
    assert len(final.contradictions) == 0


def test_ignores_unknown_and_self_pairs(tmp_path: Path) -> None:
    state = _state(_c("claim_001", "A."), _c("claim_002", "B."))
    bad = {
        "contradictions": [
            {"claim_a": "claim_001", "claim_b": "claim_999"},  # unknown
            {"claim_a": "claim_002", "claim_b": "claim_002"},  # self
        ]
    }
    final = _run(tmp_path, state, [json.dumps(bad)]).final_state
    assert len(final.contradictions) == 0


def test_does_not_duplicate_existing_contradiction(tmp_path: Path) -> None:
    existing = Contradiction(id="contradiction_x", claim_a="claim_002", claim_b="claim_001")
    state = _state(
        _c("claim_001", "X up."),
        _c("claim_002", "X down."),
        contradictions=(existing,),
    )
    # Model reports the same pair (order flipped) — must not be re-added.
    final = _run(tmp_path, state, [json.dumps(PAIR)]).final_state
    assert len(final.contradictions) == 1


def test_no_conflicts_commits_noop(tmp_path: Path) -> None:
    state = _state(_c("claim_001", "A."), _c("claim_002", "B."))
    final = _run(tmp_path, state, [json.dumps({"contradictions": []})]).final_state
    assert final.state_version == 2
    assert len(final.contradictions) == 0


def test_pair_without_justification_is_dropped(tmp_path: Path) -> None:
    # Two valid, distinct claims but no `conflict` sentence -> the model could
    # not justify the incompatibility, so it is not committed (precision gate).
    state = _state(_c("claim_001", "X up."), _c("claim_002", "Y down."))
    unjustified = {
        "contradictions": [
            {"claim_a": "claim_001", "claim_b": "claim_002", "type": "tension"}
        ]
    }
    final = _run(tmp_path, state, [json.dumps(unjustified)]).final_state
    assert len(final.contradictions) == 0
