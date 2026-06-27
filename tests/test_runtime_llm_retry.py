"""Phase 6 exit gate — the mock LLM critic produces valid and invalid patches;
the runtime commits one, rejects/retries the others.

These tests drive `Runtime.run` with a `MockLLMCriticOperator` backed by a
`MockProvider` whose script lands on each outcome. The operator never mutates
state — the runtime validates the provider's raw output and decides.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from spc_state.models import RouterDecision, SemanticState
from spc_state.operators import MockLLMCriticOperator
from spc_state.providers import (
    PROSE_RESPONSE,
    MockProvider,
    build_invalid_critic_payload,
    build_valid_critic_payload,
)
from spc_state.runtime import FixedClock, Runtime
from spc_state.store import RunPaths

NOW = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "semantic_state_v001.json"


def _state() -> SemanticState:
    return SemanticState.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _runtime(tmp_path: Path, run_id: str) -> Runtime:
    paths = RunPaths(root=tmp_path / "runs", run_id=run_id)
    clock = FixedClock([NOW + dt.timedelta(seconds=i) for i in range(64)])
    return Runtime(paths=paths, clock=clock)


# ---------------------------------------------------------------------------
# COMMIT — a clean patch.
# ---------------------------------------------------------------------------


def test_valid_patch_commits(tmp_path: Path) -> None:
    state = _state()
    provider = MockProvider([build_valid_critic_payload(state, now=NOW)])
    operator = MockLLMCriticOperator(provider)
    runtime = _runtime(tmp_path, "commit")

    result = runtime.run(initial_state=state, operators=[operator])
    step = result.steps[0]

    assert step.decision is RouterDecision.COMMIT
    assert step.attempts == 1
    assert provider.call_count == 1
    # State advanced and the critic's question landed.
    assert result.final_state.state_version == 2
    assert "q_llm_001" in result.final_state.questions
    # claim_001's confidence was lowered by the committed patch.
    assert result.final_state.claims["claim_001"].confidence == 0.62


def test_commit_records_the_model_fingerprint(tmp_path: Path) -> None:
    state = _state()
    provider = MockProvider([build_valid_critic_payload(state, now=NOW)])
    runtime = _runtime(tmp_path, "fingerprint")

    result = runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])

    fp = result.steps[0].patch.transform_record.model_fingerprint
    assert fp is not None
    assert fp.provider == "mock"
    # And it survives into the committed state's transform log.
    assert result.final_state.transform_log[-1].model_fingerprint.provider == "mock"


# ---------------------------------------------------------------------------
# REJECT — a structurally valid patch that fails referential validation.
# ---------------------------------------------------------------------------


def test_invalid_patch_is_rejected(tmp_path: Path) -> None:
    state = _state()
    provider = MockProvider([build_invalid_critic_payload(state, now=NOW)])
    runtime = _runtime(tmp_path, "reject")

    result = runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])
    step = result.steps[0]

    assert step.decision is RouterDecision.REJECT
    assert step.attempts == 1
    # State did not advance; nothing committed.
    assert result.final_state.state_version == 1
    assert "q_llm_001" not in result.final_state.questions
    assert any(i.code == "L2.UNRESOLVED_UPDATE_TARGET" for i in step.report.issues)


# ---------------------------------------------------------------------------
# RETRY — prose first, then a repaired patch on the feedback loop.
# ---------------------------------------------------------------------------


def test_prose_then_valid_retries_then_commits(tmp_path: Path) -> None:
    state = _state()
    provider = MockProvider([PROSE_RESPONSE, build_valid_critic_payload(state, now=NOW)])
    runtime = _runtime(tmp_path, "retry_commit")

    result = runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])
    step = result.steps[0]

    assert step.attempts == 2  # one prose attempt, one repaired attempt
    assert provider.call_count == 2
    assert step.decision is RouterDecision.COMMIT
    assert result.final_state.state_version == 2
    assert "q_llm_001" in result.final_state.questions


def test_retry_loop_stops_at_the_hard_cap(tmp_path: Path) -> None:
    state = _state()
    provider = MockProvider([PROSE_RESPONSE])  # always prose
    operator = MockLLMCriticOperator(provider, max_attempts=3)
    runtime = _runtime(tmp_path, "retry_exhausted")

    result = runtime.run(initial_state=state, operators=[operator])
    step = result.steps[0]

    assert step.attempts == 3  # hard cap honoured
    assert provider.call_count == 3
    assert step.decision is RouterDecision.RETRY  # never resolved
    assert step.next_state is None
    assert result.final_state.state_version == 1  # nothing committed


def test_retry_passes_validation_feedback_back_to_the_operator(tmp_path: Path) -> None:
    """The second prompt should carry the first attempt's validation errors."""
    seen_feedback: list[list[str]] = []
    state = _state()

    class _SpyCritic(MockLLMCriticOperator):
        def build_request(self, view, feedback):
            seen_feedback.append(list(feedback))
            return super().build_request(view, feedback)

    provider = MockProvider([PROSE_RESPONSE, build_valid_critic_payload(state, now=NOW)])
    runtime = _runtime(tmp_path, "feedback")
    runtime.run(initial_state=state, operators=[_SpyCritic(provider)])

    assert seen_feedback[0] == []  # first attempt has no feedback
    assert any("L1.JSON_DECODE" in msg for msg in seen_feedback[1])  # second does
