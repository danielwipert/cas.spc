"""Importable helpers that run the deterministic Phase 3 demo pipeline.

Kept in a regular module (not `conftest.py`) so tests can `from _demo_helpers
import run_demo` directly — pytest does not expose `conftest` as an importable
module name.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

from spc_state.models import SemanticState
from spc_state.operators import CriticOperator, ExtractOperator, PlannerOperator
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths, StateStoreProtocol

UTC = dt.UTC


def fresh_clock() -> FixedClock:
    start = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=UTC)
    return FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(48)])


def read_example() -> str:
    return (
        Path(__file__).resolve().parent.parent / "examples" / "ai_coding_assistant.txt"
    ).read_text(encoding="utf-8")


def run_demo(
    root: Path,
    run_id: str = "demo_001",
    *,
    state_store_factory: Callable[[RunPaths], StateStoreProtocol] | None = None,
) -> tuple[RunPaths, list[SemanticState]]:
    """Run the deterministic demo and return (paths, [v0..v3]).

    `state_store_factory` (T6) swaps the state-version backend — pass
    `SQLiteStateStore` to run the same pipeline on SQLite instead of the
    file-based default; its committed states must come out identical.
    """
    paths = RunPaths(root=root, run_id=run_id)
    clock = fresh_clock()
    initial = bootstrap_state(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="Should the company adopt an AI coding assistant?",
        now=clock.now(),
    )
    state_store = state_store_factory(paths) if state_store_factory is not None else None
    runtime = Runtime(paths=paths, clock=clock, state_store=state_store)
    text = read_example()
    result = runtime.run(
        initial_state=initial,
        operators=[
            ExtractOperator(input_text=text, clock=clock),
            PlannerOperator(clock=clock),
            CriticOperator(clock=clock),
        ],
        input_text=text,
    )
    states = [result.initial_state, *(s.next_state for s in result.steps if s.next_state)]
    return paths, states
