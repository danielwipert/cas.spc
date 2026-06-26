"""Shared fixtures for the Phase 4 (diff / receipt / follow-ups) tests.

`demo_history` runs the deterministic Extract → Planner → Critic pipeline once
and returns the full committed state history `[v0, v1, v2, v3]`, so the diff,
receipt, and follow-up tests all assert against the same canonical run. The
run helpers live in `_demo_helpers` so they are importable from tests too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spc_state.models import SemanticState
from spc_state.store import RunPaths
from tests._demo_helpers import run_demo


@pytest.fixture
def demo_run(tmp_path: Path) -> tuple[RunPaths, list[SemanticState]]:
    return run_demo(tmp_path / "runs")


@pytest.fixture
def demo_history(demo_run: tuple[RunPaths, list[SemanticState]]) -> list[SemanticState]:
    return demo_run[1]
