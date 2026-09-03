"""The LLM path must leave the same audit trail as the deterministic one.

`Runtime.step` persists a patch *before* validation judges it, so a rejected
proposal stays on the record (AGENTS.md §III). `Runtime.step_llm` must do the
same — and because a model may return something that is not a patch at all,
it must also keep the raw completion verbatim, plus one validation report per
retry attempt rather than overwriting a single file.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.models import PatchStatus, RouterDecision, SemanticState
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


def _runtime(tmp_path: Path, run_id: str) -> tuple[Runtime, RunPaths]:
    paths = RunPaths(root=tmp_path / "runs", run_id=run_id)
    clock = FixedClock([NOW + dt.timedelta(seconds=i) for i in range(64)])
    return Runtime(paths=paths, clock=clock), paths


def _audit_events(paths: RunPaths) -> list[dict]:
    lines = paths.audit_log().read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# A rejected patch stays on the record.
# ---------------------------------------------------------------------------


def test_rejected_llm_patch_is_still_persisted(tmp_path: Path) -> None:
    """A REJECTed proposal must not vanish — the run tree keeps it."""
    state = _state()
    provider = MockProvider([build_invalid_critic_payload(state, now=NOW)])
    runtime, _ = _runtime(tmp_path, "reject")

    result = runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])

    assert result.steps[0].decision is RouterDecision.REJECT
    assert result.final_state.state_version == 1  # nothing committed

    persisted = runtime.patch_store.read(1)
    assert persisted.patch_id == "patch_llm_critic_bad"
    assert persisted.status is PatchStatus.PROPOSED  # proposed, never committed


def test_rejected_patch_still_names_the_model_that_proposed_it(tmp_path: Path) -> None:
    """A proposal nobody can attribute is a weak record (spec §10.6)."""
    state = _state()
    provider = MockProvider([build_invalid_critic_payload(state, now=NOW)])
    runtime, _ = _runtime(tmp_path, "reject_fingerprint")

    runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])

    fingerprint = runtime.patch_store.read(1).transform_record.model_fingerprint
    assert fingerprint is not None
    assert fingerprint.provider == "mock"


def test_unparseable_output_is_preserved_verbatim(tmp_path: Path) -> None:
    """Prose parses into no patch at all, so the raw completion is the record."""
    state = _state()
    provider = MockProvider([PROSE_RESPONSE])
    operator = MockLLMCriticOperator(provider, max_attempts=1)
    runtime, paths = _runtime(tmp_path, "prose")

    result = runtime.run(initial_state=state, operators=[operator])

    assert result.steps[0].decision is RouterDecision.RETRY
    assert not paths.patch_file(1).exists()  # nothing parsed, so no patch file
    assert paths.patch_attempt_file(1, 1).read_text(encoding="utf-8") == PROSE_RESPONSE


def test_llm_step_emits_patch_proposed(tmp_path: Path) -> None:
    """Audit parity with the deterministic path, which logs `patch.proposed`."""
    state = _state()
    provider = MockProvider([build_invalid_critic_payload(state, now=NOW)])
    runtime, paths = _runtime(tmp_path, "audit")

    runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])

    proposed = [e for e in _audit_events(paths) if e["event"] == "patch.proposed"]
    assert len(proposed) == 1
    assert proposed[0]["patch_id"] == "patch_llm_critic_bad"
    assert proposed[0]["attempt"] == 1


def test_unparseable_output_is_audited_as_proposed(tmp_path: Path) -> None:
    """Even an unparseable completion is a proposal, logged as one."""
    state = _state()
    provider = MockProvider([PROSE_RESPONSE])
    runtime, paths = _runtime(tmp_path, "audit_prose")

    runtime.run(
        initial_state=state,
        operators=[MockLLMCriticOperator(provider, max_attempts=1)],
    )

    proposed = [e for e in _audit_events(paths) if e["event"] == "patch.proposed"]
    assert len(proposed) == 1
    assert proposed[0]["patch_id"] == "unparsed_patch"


# ---------------------------------------------------------------------------
# Retries do not overwrite each other.
# ---------------------------------------------------------------------------


def test_each_retry_attempt_keeps_its_own_artifacts(tmp_path: Path) -> None:
    state = _state()
    provider = MockProvider([PROSE_RESPONSE])  # always prose -> 3 attempts
    operator = MockLLMCriticOperator(provider, max_attempts=3)
    runtime, paths = _runtime(tmp_path, "retries")

    result = runtime.run(initial_state=state, operators=[operator])

    assert result.steps[0].attempts == 3
    for attempt in (1, 2, 3):
        assert paths.patch_attempt_file(1, attempt).exists()
        assert paths.validation_attempt_file(1, attempt).exists()
    # The canonical report still holds the final attempt's outcome.
    assert paths.validation_file(1).exists()


def test_retry_then_commit_keeps_the_superseded_attempt(tmp_path: Path) -> None:
    """The prose attempt survives even though the repaired one committed."""
    state = _state()
    provider = MockProvider([PROSE_RESPONSE, build_valid_critic_payload(state, now=NOW)])
    runtime, paths = _runtime(tmp_path, "retry_commit")

    result = runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])

    assert result.steps[0].decision is RouterDecision.COMMIT
    assert paths.patch_attempt_file(1, 1).read_text(encoding="utf-8") == PROSE_RESPONSE
    assert "patch_llm_critic" in paths.patch_attempt_file(1, 2).read_text(encoding="utf-8")
    # The canonical patch file records the committed outcome, not the prose.
    assert runtime.patch_store.read(1).status is PatchStatus.COMMITTED


# ---------------------------------------------------------------------------
# The attempt trail must not disturb the §20.8 artifact counts.
# ---------------------------------------------------------------------------


def test_attempt_files_are_not_counted_as_patches_or_reports(tmp_path: Path) -> None:
    """Metrics glob `patch_*.json` / `validation_*.json`; attempts must not match."""
    state = _state()
    provider = MockProvider([PROSE_RESPONSE, build_valid_critic_payload(state, now=NOW)])
    runtime, paths = _runtime(tmp_path, "counts")

    runtime.run(initial_state=state, operators=[MockLLMCriticOperator(provider)])

    assert len(list(paths.patches_dir.glob("patch_*.json"))) == 1
    assert len(list(paths.validation_dir.glob("validation_*.json"))) == 1
