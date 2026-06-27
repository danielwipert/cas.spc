"""`ProjectionView` — the materialised, isolated slice an operator reads from.

A `Projection` lists *which* object IDs a perspective sees (see
`builder.py`). `resolve_view` turns that ID list into the actual objects,
but as **deep copies**, and wraps them in a frozen container. This gives an
operator the strongest form of the §14.4 invariant:

- it can only reach objects in its slice (everything else is absent), and
- mutating the view — or any object inside it — cannot leak back into
  canonical `SemanticState`, because the view holds copies, not references.

This is the mechanism behind the operator contract in `operators/base.py`:
operators only see what their projection includes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..models import (
    Assumption,
    Claim,
    Contradiction,
    Entity,
    Evidence,
    Hypothesis,
    Inference,
    Perspective,
    Projection,
    Question,
    Relation,
    SemanticState,
)

_T = TypeVar("_T", bound=BaseModel)


def _resolve(container: Mapping[str, _T], ids: list[str]) -> dict[str, _T]:
    """Deep-copy the in-slice objects so the view is isolated from state."""
    out: dict[str, _T] = {}
    for obj_id in ids:
        obj = container.get(obj_id)
        if obj is not None:
            out[obj_id] = obj.model_copy(deep=True)
    return out


class ProjectionView(BaseModel):
    """A frozen, deep-copied view of the objects a perspective may read.

    Frozen at the attribute level: `view.claims = {}` raises. The objects
    inside are independent copies, so even in-place edits cannot reach
    canonical state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str
    perspective: Perspective
    goal: str

    entities: dict[str, Entity] = Field(default_factory=dict)
    claims: dict[str, Claim] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    assumptions: dict[str, Assumption] = Field(default_factory=dict)
    inferences: dict[str, Inference] = Field(default_factory=dict)
    hypotheses: dict[str, Hypothesis] = Field(default_factory=dict)
    questions: dict[str, Question] = Field(default_factory=dict)
    contradictions: dict[str, Contradiction] = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list)

    def object_ids(self) -> set[str]:
        """Every object id visible in this view (relations included)."""
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


def resolve_view(projection: Projection, state: SemanticState) -> ProjectionView:
    """Materialise the objects named by `projection` into a frozen view.

    Only IDs listed in `projection.included_objects` are resolved, and every
    object is deep-copied — so the operator that reads this view cannot see
    or touch anything outside its slice.
    """
    inc = projection.included_objects
    rel_ids = set(inc.relations)
    return ProjectionView(
        projection_id=projection.projection_id,
        perspective=projection.perspective,
        goal=projection.goal,
        entities=_resolve(state.entities, inc.entities),
        claims=_resolve(state.claims, inc.claims),
        evidence=_resolve(state.evidence, inc.evidence),
        assumptions=_resolve(state.assumptions, inc.assumptions),
        inferences=_resolve(state.inferences, inc.inferences),
        hypotheses=_resolve(state.hypotheses, inc.hypotheses),
        questions=_resolve(state.questions, inc.questions),
        contradictions=_resolve(state.contradictions, inc.contradictions),
        relations=[r.model_copy(deep=True) for r in state.relations if r.id in rel_ids],
    )


__all__ = ["ProjectionView", "resolve_view"]
