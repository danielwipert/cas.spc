"""`SemanticPatch` — the only legal way to change `SemanticState`.

See PILOT_SPEC.md §12. The hard invariant (AGENTS.md §I) is that no operator
may mutate state directly; every change is proposed as a patch, validated,
and committed by the runtime.

Design note: the spec's §12.2 example shows `add_objects` and `add_relations`
as bare ID lists for readability. To make L1/L2 validation possible the
implementation requires the **full object payloads** in those fields, not
just IDs. This is the only deliberate divergence from the literal YAML in
§12.2 — the model carries the same information, in a stricter shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .enums import PatchStatus
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


class AddObjects(BaseModel):
    """New objects proposed by the patch, grouped by type.

    The runtime concatenates each list into the corresponding
    `SemanticState` dict on commit.
    """

    entities: list[Entity] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    inferences: list[Inference] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def is_empty(self) -> bool:
        return not any(
            (
                self.entities,
                self.claims,
                self.evidence,
                self.assumptions,
                self.inferences,
                self.hypotheses,
                self.questions,
                self.contradictions,
            )
        )


class UpdateObject(BaseModel):
    """A typed field update on an existing object. See spec §12.2."""

    object_id: str
    field: str
    from_value: Any = Field(alias="from")
    to_value: Any = Field(alias="to")
    reason: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ArchiveObject(BaseModel):
    """Archive (soft-delete) an object. The object remains in state with
    `status='archived'` so audit history stays intact.
    """

    object_id: str
    reason: str

    model_config = ConfigDict(extra="forbid")


class SemanticPatch(BaseModel):
    """A proposed mutation to `SemanticState`. See spec §12."""

    patch_id: str
    patch_version: str = "0.1.0"
    base_state_id: str
    base_state_version: int = Field(ge=0)
    proposed_by: str
    created_at: AwareDatetime

    read_set: list[str] = Field(default_factory=list)
    add_objects: AddObjects = Field(default_factory=AddObjects)
    update_objects: list[UpdateObject] = Field(default_factory=list)
    add_relations: list[Relation] = Field(default_factory=list)
    archive_objects: list[ArchiveObject] = Field(default_factory=list)

    transform_record: TransformRecord
    status: PatchStatus = PatchStatus.PROPOSED

    model_config = ConfigDict(extra="forbid")

    def is_empty(self) -> bool:
        """True if the patch proposes no changes at all."""
        return (
            self.add_objects.is_empty()
            and not self.update_objects
            and not self.add_relations
            and not self.archive_objects
        )


__all__ = [
    "AddObjects",
    "ArchiveObject",
    "SemanticPatch",
    "UpdateObject",
]
