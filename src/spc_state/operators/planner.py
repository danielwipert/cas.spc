"""Deterministic Planner operator for the AI-coding-assistant demo.

The planner reads the post-extract state and adds:
- an inference linking the productivity claim to its assumption,
- a candidate hypothesis (the plan-shaped output),
- a high-priority open question about how productivity will be measured,
- a `claim_001 depends_on assumption_001` relation.

Phase 6+ replaces this with an LLM operator.
"""

from __future__ import annotations

from ..models import (
    Hypothesis,
    HypothesisStatus,
    Inference,
    InferenceType,
    PatchStatus,
    Perspective,
    Priority,
    Projection,
    Question,
    QuestionStatus,
    Relation,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import AddObjects
from ..runtime.clock import Clock
from .base import Operator


class PlannerOperator(Operator):
    name = "planner_transform"
    version = "0.1.0"
    perspective = Perspective.PLANNER
    goal = (
        "Surface candidate paths, dependencies, and unresolved questions for "
        "the decision under analysis."
    )

    def __init__(
        self,
        *,
        clock: Clock,
        patch_id: str = "patch_002",
        transform_id: str = "transform_planner_001",
    ) -> None:
        self.clock = clock
        self.patch_id = patch_id
        self.transform_id = transform_id

    def propose(self, state: SemanticState, projection: Projection) -> SemanticPatch:
        if "claim_001" not in state.claims or "assumption_001" not in state.assumptions:
            raise RuntimeError(
                "PlannerOperator (Phase 3 deterministic) expects the post-extract "
                "demo state. Did the Extract step run?"
            )

        started = self.clock.now()

        inference = Inference(
            id="inf_001",
            inference_type=InferenceType.ABDUCTIVE,
            premises=["claim_001", "assumption_001"],
            conclusion="claim_001",
            confidence_delta=0.0,
            generated_by=self.transform_id,
            notes=(
                "Productivity claim is materially conditional on the benchmark-"
                "transfer assumption."
            ),
        )

        hypothesis = Hypothesis(
            id="hyp_001",
            text=(
                "The company should pilot the assistant on routine engineering "
                "tasks while restricting it from architecture work."
            ),
            status=HypothesisStatus.ACTIVE,
            confidence=0.6,
            supporting_claims=["claim_001"],
            generated_by=self.transform_id,
        )

        question = Question(
            id="q_001",
            text="How will the productivity gains be measured during the pilot?",
            status=QuestionStatus.OPEN,
            priority=Priority.HIGH,
            linked_objects=["claim_001"],
            asked_by=self.transform_id,
        )

        relation = Relation(
            id="rel_001",
            source="claim_001",
            predicate="depends_on",
            target="assumption_001",
            confidence=0.9,
            created_by=self.transform_id,
        )

        finished = self.clock.now()

        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="plan",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=["claim_001", "assumption_001"],
            write_set=["inf_001", "hyp_001", "q_001", "rel_001"],
            confidence_changes=[],
            started_at=started,
            finished_at=finished,
        )

        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=finished,
            read_set=["claim_001", "assumption_001"],
            add_objects=AddObjects(
                inferences=[inference],
                hypotheses=[hypothesis],
                questions=[question],
            ),
            add_relations=[relation],
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


__all__ = ["PlannerOperator"]
