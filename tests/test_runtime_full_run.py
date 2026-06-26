"""Phase 3 exit gate — document → v1 → v2 → v3 deterministically.

This is the test that locks in the §15.1 runtime loop and the §17.1 disk
layout. It also enforces that two identical runs produce byte-for-byte
identical artifacts (the spec says "reproducible across runs").
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spc_state.audit import AuditLog
from spc_state.models import RouterDecision
from spc_state.operators import CriticOperator, ExtractOperator, PlannerOperator
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths

UTC = dt.timezone.utc


def _fresh_clock() -> FixedClock:
    start = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=UTC)
    return FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(48)])


def _read_input() -> str:
    return (
        Path(__file__).resolve().parent.parent / "examples" / "ai_coding_assistant.txt"
    ).read_text(encoding="utf-8")


def _do_run(root: Path, run_id: str) -> tuple[RunPaths, dict]:
    paths = RunPaths(root=root, run_id=run_id)
    clock = _fresh_clock()
    initial = bootstrap_state(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="AI Coding Assistant Adoption Analysis",
        now=clock.now(),
    )
    runtime = Runtime(paths=paths, clock=clock)
    input_text = _read_input()
    operators = [
        ExtractOperator(input_text=input_text, clock=clock),
        PlannerOperator(clock=clock),
        CriticOperator(clock=clock),
    ]
    result = runtime.run(
        initial_state=initial,
        operators=operators,
        input_text=input_text,
    )
    return paths, json.loads(
        Path(paths.state_file(result.final_state.state_version)).read_text(encoding="utf-8")
    )


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def test_full_run_produces_state_v3(runs_root: Path) -> None:
    paths, final = _do_run(runs_root, "demo_001")

    # State versions v0..v3 all on disk.
    for v in range(4):
        assert paths.state_file(v).exists(), f"missing state v{v}"
    # Three patches and three validation reports.
    for ordinal in (1, 2, 3):
        assert paths.patch_file(ordinal).exists()
        assert paths.validation_file(ordinal).exists()
    # Audit log has at least one event per logical step.
    assert paths.audit_log().exists()

    # Final state details:
    assert final["state_version"] == 3
    assert final["previous_state_version"] == 2
    assert set(final["claims"]) == {"claim_001", "claim_002", "claim_003"}
    assert final["claims"]["claim_001"]["confidence"] == 0.62
    assert set(final["questions"]) == {"q_001", "q_002"}
    assert {r["id"] for r in final["relations"]} == {"rel_001", "rel_002"}
    assert final["audit"]["committed_patches"] == ["patch_001", "patch_002", "patch_003"]
    assert len(final["transform_log"]) == 3


def test_every_decision_is_commit(runs_root: Path) -> None:
    paths = RunPaths(root=runs_root, run_id="demo_002")
    clock = _fresh_clock()
    initial = bootstrap_state(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="x",
        now=clock.now(),
    )
    runtime = Runtime(paths=paths, clock=clock)
    text = _read_input()
    result = runtime.run(
        initial_state=initial,
        operators=[
            ExtractOperator(input_text=text, clock=clock),
            PlannerOperator(clock=clock),
            CriticOperator(clock=clock),
        ],
        input_text=text,
    )
    decisions = [o.decision for o in result.steps]
    assert decisions == [RouterDecision.COMMIT] * 3


def test_audit_log_has_expected_event_sequence(runs_root: Path) -> None:
    paths, _ = _do_run(runs_root, "demo_003")
    events = [e["event"] for e in AuditLog(paths.audit_log()).read()]
    # The first event is the bootstrap, then per operator we get
    # started → proposed → routed → committed.
    assert events[0] == "state.bootstrapped"
    per_op = events[1:]
    expected_block = ["operator.started", "patch.proposed", "patch.routed", "state.committed"]
    assert per_op == expected_block * 3


def test_two_runs_are_byte_for_byte_identical(runs_root: Path) -> None:
    a_paths, _ = _do_run(runs_root, "run_a")
    b_paths, _ = _do_run(runs_root, "run_b")

    # Compare every artifact except the audit log path (different run_id
    # appears in the path but not the content) and the input copy (same
    # bytes).
    artifacts_a = sorted(p.relative_to(a_paths.run_dir) for p in a_paths.run_dir.rglob("*") if p.is_file())
    artifacts_b = sorted(p.relative_to(b_paths.run_dir) for p in b_paths.run_dir.rglob("*") if p.is_file())
    assert artifacts_a == artifacts_b

    for rel in artifacts_a:
        a_bytes = (a_paths.run_dir / rel).read_bytes()
        b_bytes = (b_paths.run_dir / rel).read_bytes()
        assert a_bytes == b_bytes, f"byte-mismatch in {rel}"


def test_final_state_round_trips_through_pydantic(runs_root: Path) -> None:
    """The on-disk v3 state revalidates without errors."""
    paths, _ = _do_run(runs_root, "demo_validate")
    from spc_state.models import SemanticState

    raw = (paths.state_file(3)).read_text(encoding="utf-8")
    state = SemanticState.model_validate_json(raw)
    assert state.state_version == 3
    assert state.claims["claim_001"].confidence == 0.62
    # The transform_log entries have output_state_version filled in.
    for tr in state.transform_log:
        assert tr.output_state_version is not None
