"""Phase 3 projection stub: include every object ID in the state.

The operator contract (PILOT_SPEC.md §13.5) requires a `Projection`, but
Phase 3 does not yet ship perspective-specific views — Phase 5 does. This
stub passes every active object's ID through, regardless of perspective.
"""

from __future__ import annotations

from ..models import (
    IncludedObjects,
    ObjectStatus,
    Perspective,
    Projection,
    SemanticState,
)


def passthrough(
    state: SemanticState,
    *,
    perspective: Perspective,
    goal: str,
    include_archived: bool = False,
) -> Projection:
    """Return a `Projection` listing every active object ID in `state`."""

    def _active_ids(container: dict[str, object]) -> list[str]:
        out: list[str] = []
        for obj_id, obj in container.items():
            status = getattr(obj, "status", None)
            if not include_archived and status == ObjectStatus.ARCHIVED:
                continue
            out.append(obj_id)
        return out

    included = IncludedObjects(
        entities=_active_ids(state.entities),
        claims=_active_ids(state.claims),
        evidence=_active_ids(state.evidence),
        assumptions=_active_ids(state.assumptions),
        inferences=_active_ids(state.inferences),
        hypotheses=_active_ids(state.hypotheses),
        questions=_active_ids(state.questions),
        contradictions=_active_ids(state.contradictions),
        relations=[
            r.id for r in state.relations
            if include_archived or r.status != ObjectStatus.ARCHIVED
        ],
    )

    return Projection(
        projection_id=f"proj_{perspective.value}_v{state.state_version:03d}",
        base_state_id=state.state_id,
        base_state_version=state.state_version,
        perspective=perspective,
        goal=goal,
        included_objects=included,
    )


__all__ = ["passthrough"]
