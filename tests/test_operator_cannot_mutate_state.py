"""AGENTS.md §I — operators must not mutate canonical SemanticState.

This invariant is the single most important property of the engine. We
enforce it three ways:

1. `SemanticState` is frozen at the Pydantic level (covered in
   test_state_frozen.py).
2. Operators receive `state` and `projection`, but the runtime only commits
   their **patch** — anything they may have tried to do to the state in
   memory does not survive into the next version. This test proves that
   even when a malicious operator imitates the runtime's commit path, the
   actual on-disk state version after the runtime step does **not** reflect
   their direct mutation attempts.
3. The Pydantic frozen check should raise `ValidationError` when an
   operator tries to set an attribute. This test exercises that path
   directly with a custom operator.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from spc_state.models import (
    PatchStatus,
    Perspective,
    Projection,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from spc_state.models.patch import AddObjects
from spc_state.operators.base import Operator
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths

UTC = dt.timezone.utc


class _NaughtyOperator(Operator):
    """An operator that attempts to mutate state directly."""

    name = "naughty_op"
    version = "0.0.1"
    perspective = Perspective.PLANNER
    goal = "Try to mutate state directly."

    def __init__(self, clock: FixedClock) -> None:
        self.clock = clock
        self.mutation_blocked: bool = False

    def propose(
        self,
        state: SemanticState,
        projection: Projection,
    ) -> SemanticPatch:
        try:
            state.state_version = 999  # type: ignore[misc]
        except ValidationError:
            self.mutation_blocked = True
        now = self.clock.now()
        return SemanticPatch(
            patch_id="patch_naughty",
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=now,
            read_set=[],
            add_objects=AddObjects(),
            transform_record=TransformRecord(
                id="transform_naughty",
                transform_type="naughty",
                operator=self.name,
                operator_version=self.fully_qualified(),
                input_state_version=state.state_version,
                read_set=[],
                write_set=[],
            ),
            status=PatchStatus.PROPOSED,
        )


def test_attribute_mutation_raises_validation_error_inside_operator(tmp_path: Path) -> None:
    """An operator that tries `state.state_version = 999` must be blocked."""
    paths = RunPaths(root=tmp_path / "runs", run_id="naughty")
    clock = FixedClock(dt.datetime(2026, 6, 26, tzinfo=UTC))
    initial = bootstrap_state(
        state_id="sr_x",
        project_id="spc_pilot_test",
        name="naughty test",
        now=clock.now(),
    )
    runtime = Runtime(paths=paths, clock=clock)
    naughty = _NaughtyOperator(clock=clock)
    result = runtime.run(initial_state=initial, operators=[naughty])

    # The frozen-state guard fired inside the operator.
    assert naughty.mutation_blocked is True
    # State version did not jump to 999. The empty patch commits cleanly
    # and bumps to 1 (the runtime's normal increment), nothing more.
    assert result.final_state.state_version == 1


def test_runtime_only_commits_via_the_returned_patch(tmp_path: Path) -> None:
    """Even if an operator could mutate state in memory, the on-disk next
    state version reflects only the runtime's commit step — i.e. only the
    returned patch's add_objects/update_objects/etc."""
    paths = RunPaths(root=tmp_path / "runs", run_id="contract")
    clock = FixedClock(dt.datetime(2026, 6, 26, tzinfo=UTC))
    initial = bootstrap_state(
        state_id="sr_x",
        project_id="spc_pilot_test",
        name="contract test",
        now=clock.now(),
    )
    runtime = Runtime(paths=paths, clock=clock)
    naughty = _NaughtyOperator(clock=clock)
    runtime.run(initial_state=initial, operators=[naughty])

    on_disk = json.loads((paths.state_file(1)).read_text(encoding="utf-8"))
    assert on_disk["state_version"] == 1
    assert on_disk["claims"] == {}
    assert on_disk["audit"]["committed_patches"] == ["patch_naughty"]
