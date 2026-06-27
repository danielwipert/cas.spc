"""`Projection` — a perspective-specific view of `SemanticState`.

See PILOT_SPEC.md §14. Operators receive a `Projection`, not the raw
`SemanticState`, so that critic/writer/retriever/etc. only see the slice
their role needs. The projection may emphasize or hide, but it must not
mutate canonical state (spec §14.4).

The model is frozen: an operator that receives a `Projection` cannot
reassign its attributes. The perspective-specific builders live in
`spc_state.projection` (Phase 5).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import Perspective


class ProjectionPolicy(BaseModel):
    """Switches that govern what the projection includes. See spec §14.3."""

    include_low_confidence_claims: bool = True
    include_evidence_spans: bool = True
    include_dependency_edges: bool = True
    include_writer_notes: bool = False
    include_archived: bool = False
    include_contradictions: bool = True

    model_config = ConfigDict(extra="forbid", frozen=True)


class IncludedObjects(BaseModel):
    """Object IDs included in this projection, grouped by type."""

    entities: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True)


class Projection(BaseModel):
    """A perspective-specific projection of a state version. See spec §14.3."""

    projection_id: str
    base_state_id: str
    base_state_version: int = Field(ge=0)
    perspective: Perspective
    goal: str
    included_objects: IncludedObjects = Field(default_factory=IncludedObjects)
    projection_policy: ProjectionPolicy = Field(default_factory=ProjectionPolicy)

    model_config = ConfigDict(extra="forbid", frozen=True)


__all__ = ["IncludedObjects", "Projection", "ProjectionPolicy"]
