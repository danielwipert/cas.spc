"""`SemanticState` — the versioned, frozen container of the shared semantic reality.

See PILOT_SPEC.md §10.1 and §11.1. This is the canonical state of a problem,
document, decision, or argument. It is **frozen**: operators cannot mutate
it. The only path to a new state version is `SemanticState.with_committed_patch(...)`
which returns a fresh model via `model_copy(update=...)`.

This frozen-at-the-top discipline is the enforcement mechanism for the hard
invariant in AGENTS.md §I. A dedicated test asserts that direct attribute
writes raise `ValidationError`.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .enums import StateStatus
from .objects import (
    Assumption,
    Claim,
    Contradiction,
    Entity,
    Evidence,
    Hypothesis,
    Inference,
    Question,
    Relation,
)
from .transform import TransformRecord

SCHEMA_VERSION = "0.1.0"


class StateAuditTallies(BaseModel):
    committed_patches: list[str] = Field(default_factory=list)
    pending_patches: list[str] = Field(default_factory=list)
    rejected_patches: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticState(BaseModel):
    """Versioned semantic state. Frozen — must not be mutated in place."""

    state_id: str
    schema_version: str = SCHEMA_VERSION
    project_id: str
    name: str
    state_version: int = Field(ge=0)
    previous_state_version: int | None = Field(default=None, ge=0)
    status: StateStatus = StateStatus.ACTIVE
    created_at: AwareDatetime
    updated_at: AwareDatetime

    entities: dict[str, Entity] = Field(default_factory=dict)
    claims: dict[str, Claim] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    assumptions: dict[str, Assumption] = Field(default_factory=dict)
    inferences: dict[str, Inference] = Field(default_factory=dict)
    hypotheses: dict[str, Hypothesis] = Field(default_factory=dict)
    questions: dict[str, Question] = Field(default_factory=dict)
    contradictions: dict[str, Contradiction] = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list)

    transform_log: list[TransformRecord] = Field(default_factory=list)
    audit: StateAuditTallies = Field(default_factory=StateAuditTallies)

    # Pydantic v2 will refuse `state.state_version = 4` once frozen is on,
    # which is the enforcement we want. Nested dict mutation is technically
    # possible, but operators never see SemanticState directly — they see
    # Projection — so the surface that could mutate it is the runtime alone.
    model_config = ConfigDict(extra="forbid", frozen=True)

    # -- read helpers -------------------------------------------------------

    def has_id(self, object_id: str) -> bool:
        """Return True if any object/relation in state carries this id."""
        if (
            object_id in self.entities
            or object_id in self.claims
            or object_id in self.evidence
            or object_id in self.assumptions
            or object_id in self.inferences
            or object_id in self.hypotheses
            or object_id in self.questions
            or object_id in self.contradictions
        ):
            return True
        return any(r.id == object_id for r in self.relations)

    def all_object_ids(self) -> set[str]:
        ids: set[str] = set()
        ids.update(self.entities)
        ids.update(self.claims)
        ids.update(self.evidence)
        ids.update(self.assumptions)
        ids.update(self.inferences)
        ids.update(self.hypotheses)
        ids.update(self.questions)
        ids.update(self.contradictions)
        ids.update(r.id for r in self.relations)
        return ids


__all__ = ["SCHEMA_VERSION", "SemanticState", "StateAuditTallies"]
