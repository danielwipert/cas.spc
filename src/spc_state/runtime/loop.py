"""The runtime: load → project → operate → validate → route → commit → audit.

See PILOT_SPEC.md §15.1. This is the only module that has reference to a
mutable next-state via `model_copy(update=...)`. Operators see only their
projection; validators see only `(state, patch_payload)`; the router sees
only the report. The runtime stitches them together.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field

from ..audit import AuditLog
from ..models import (
    PatchStatus,
    RouterDecision,
    SemanticPatch,
    SemanticState,
    StateStatus,
    ValidationReport,
)
from ..projection import passthrough
from ..router import decide as router_decide
from ..store import PatchStore, RunPaths, StateStore, ValidationStore
from ..validation import validate as run_validation
from .clock import Clock, WallClock
from .commit import commit_patch


# ---------------------------------------------------------------------------
# Bootstrapping an initial state
# ---------------------------------------------------------------------------


def bootstrap_state(
    *,
    state_id: str,
    project_id: str,
    name: str,
    now: dt.datetime,
) -> SemanticState:
    """Return an empty, version-0 `SemanticState` for a fresh run."""
    return SemanticState(
        state_id=state_id,
        project_id=project_id,
        name=name,
        state_version=0,
        previous_state_version=None,
        status=StateStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


@dataclass
class StepOutcome:
    ordinal: int
    patch: SemanticPatch
    report: ValidationReport
    decision: RouterDecision
    next_state: SemanticState | None  # None on REJECT / RETRY / FAIL


@dataclass
class RunResult:
    paths: RunPaths
    initial_state: SemanticState
    final_state: SemanticState
    steps: list[StepOutcome] = field(default_factory=list)


class Runtime:
    """Per-run runtime control plane."""

    def __init__(
        self,
        *,
        paths: RunPaths,
        clock: Clock | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self.paths = paths
        self.clock = clock or WallClock()
        self.state_store = StateStore(paths)
        self.patch_store = PatchStore(paths)
        self.validation_store = ValidationStore(paths)
        self.audit = audit or AuditLog(paths.audit_log())

    # -- one operator step ------------------------------------------------

    def step(
        self,
        state: SemanticState,
        operator,
        *,
        ordinal: int,
        report_id: str | None = None,
    ) -> StepOutcome:
        # 1. Build a projection (Phase 3: passthrough stub).
        projection = passthrough(
            state,
            perspective=operator.perspective,
            goal=operator.goal,
        )

        # 2. Run the operator.
        self.audit.append(
            "operator.started",
            at=self.clock.now(),
            operator=operator.fully_qualified(),
            base_state_version=state.state_version,
        )
        patch = operator.propose(state, projection)

        # 3. Persist the proposed patch.
        self.patch_store.write(patch, ordinal)
        self.audit.append(
            "patch.proposed",
            at=self.clock.now(),
            patch_id=patch.patch_id,
            base_state_version=patch.base_state_version,
            operator=operator.fully_qualified(),
        )

        # 4. Validate (L1 + L2) — round-trip through JSON the way an LLM
        #    operator's output would be received in Phase 7. This catches
        #    any divergence between the operator's in-memory model and the
        #    on-the-wire shape.
        patch_payload = json.loads(patch.model_dump_json(by_alias=True))
        report = run_validation(
            state=state,
            patch_payload=patch_payload,
            report_id=report_id or f"report_{ordinal:03d}",
            now=self.clock.now(),
        )
        self.validation_store.write(report, ordinal)

        # 5. Route.
        decision = router_decide(report)
        self.audit.append(
            "patch.routed",
            at=self.clock.now(),
            patch_id=patch.patch_id,
            decision=decision.value,
            issues=[i.code for i in report.issues],
        )

        # 6. Commit (only on COMMIT). REJECT/RETRY/REVIEW/FAIL leave state
        #    unchanged; the audit log records the outcome.
        next_state: SemanticState | None = None
        if decision is RouterDecision.COMMIT:
            committed_patch = patch.model_copy(update={"status": PatchStatus.COMMITTED})
            self.patch_store.write(committed_patch, ordinal)
            next_state = commit_patch(state, committed_patch, now=self.clock.now())
            self.state_store.write(next_state)
            self.audit.append(
                "state.committed",
                at=self.clock.now(),
                patch_id=patch.patch_id,
                previous_state_version=state.state_version,
                new_state_version=next_state.state_version,
            )

        return StepOutcome(
            ordinal=ordinal,
            patch=patch,
            report=report,
            decision=decision,
            next_state=next_state,
        )

    # -- a full run -------------------------------------------------------

    def run(
        self,
        *,
        initial_state: SemanticState,
        operators: list,
        input_text: str | None = None,
    ) -> RunResult:
        self.paths.ensure_dirs()
        if input_text is not None:
            self.paths.input_copy().write_text(input_text, encoding="utf-8")

        # Snapshot v0.
        self.state_store.write(initial_state)
        self.audit.append(
            "state.bootstrapped",
            at=self.clock.now(),
            state_id=initial_state.state_id,
            state_version=initial_state.state_version,
        )

        state = initial_state
        steps: list[StepOutcome] = []
        for ordinal, operator in enumerate(operators, start=1):
            outcome = self.step(state, operator, ordinal=ordinal)
            steps.append(outcome)
            if outcome.next_state is not None:
                state = outcome.next_state

        return RunResult(
            paths=self.paths,
            initial_state=initial_state,
            final_state=state,
            steps=steps,
        )


__all__ = ["Runtime", "RunResult", "StepOutcome", "bootstrap_state"]
