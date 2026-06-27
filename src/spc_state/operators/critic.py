"""Deterministic Critic operator for the AI-coding-assistant demo.

The critic reads the post-planner state and:
- lowers confidence on `claim_001` (the productivity claim) from 0.74 → 0.62,
- raises a high-priority question about transfer to architecture work,
- adds a `q_002 questions claim_001` relation.

This mirrors the spec §12.2 example patch shape. Phase 6+ replaces this
with an LLM operator returning the same patch shape under structured-output
enforcement.
"""

from __future__ import annotations

from ..models import (
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
from ..models.patch import AddObjects, UpdateObject
from ..models.transform import ConfidenceChange
from ..projection import resolve_view
from ..runtime.clock import Clock
from .base import Operator


class CriticOperator(Operator):
    name = "critic_transform"
    version = "0.1.0"
    perspective = Perspective.CRITIC
    goal = "Identify weak claims, missing assumptions, and unresolved tensions."

    OLD_CONFIDENCE = 0.74
    NEW_CONFIDENCE = 0.62

    def __init__(
        self,
        *,
        clock: Clock,
        patch_id: str = "patch_003",
        transform_id: str = "transform_critic_001",
    ) -> None:
        self.clock = clock
        self.patch_id = patch_id
        self.transform_id = transform_id

    def propose(self, state: SemanticState, projection: Projection) -> SemanticPatch:
        # The critic's projection surfaces weak claims; claim_001 is one.
        view = resolve_view(projection, state)
        target = view.claims.get("claim_001")
        if target is None:
            raise RuntimeError(
                "CriticOperator (Phase 3 deterministic) expects claim_001 in its "
                "critic projection (it should be flagged as a weak claim)."
            )

        started = self.clock.now()

        reason = (
            "Evidence supports routine task speed but not complex architecture work."
        )

        update = UpdateObject.model_validate(
            {
                "object_id": "claim_001",
                "field": "confidence",
                "from": target.confidence,
                "to": self.NEW_CONFIDENCE,
                "reason": reason,
            }
        )

        question = Question(
            id="q_002",
            text="Does the productivity evidence transfer to complex architecture work?",
            status=QuestionStatus.OPEN,
            priority=Priority.HIGH,
            linked_objects=["claim_001", "assumption_001"],
            asked_by=self.transform_id,
        )

        relation = Relation(
            id="rel_002",
            source="q_002",
            predicate="questions",
            target="claim_001",
            confidence=1.0,
            created_by=self.transform_id,
        )

        confidence_change = ConfidenceChange.model_validate(
            {
                "object_id": "claim_001",
                "from": target.confidence,
                "to": self.NEW_CONFIDENCE,
                "reason": reason,
            }
        )

        finished = self.clock.now()

        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="critique",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=["claim_001", "assumption_001"],
            write_set=["claim_001", "q_002", "rel_002"],
            confidence_changes=[confidence_change],
            started_at=started,
            finished_at=finished,
        )

        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=finished,
            read_set=["claim_001", "claim_002", "assumption_001"],
            add_objects=AddObjects(questions=[question]),
            update_objects=[update],
            add_relations=[relation],
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


__all__ = ["CriticOperator"]
