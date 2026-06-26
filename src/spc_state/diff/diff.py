"""State-version diff. See PILOT_SPEC.md §18.1 ("state diffs") and §20.

`diff_states(before, after)` compares two `SemanticState` versions object-type
by object-type and returns a `StateDiff`: which objects were **added**,
**removed**, or **changed** (with field-level before/after values).

The diff is itself a frozen, JSON-serializable Pydantic model so it can be
written to `runs/<id>/diffs/diff_vAAA_vBBB.json` through the same store
machinery as every other artifact, and rendered into a Reasoning Receipt.

Determinism: every list is sorted (ids lexicographically, field changes by
field name) so the same pair of states always produces byte-identical output.
This preserves the Phase 3 reproducibility exit-gate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models import SemanticState

# Object collections in a stable render order. Dict-typed collections map
# id -> object directly; relations are a list, so we key them by `id`.
_COLLECTIONS: dict[str, Callable[[SemanticState], dict[str, Any]]] = {
    "entity": lambda s: dict(s.entities),
    "claim": lambda s: dict(s.claims),
    "evidence": lambda s: dict(s.evidence),
    "assumption": lambda s: dict(s.assumptions),
    "inference": lambda s: dict(s.inferences),
    "hypothesis": lambda s: dict(s.hypotheses),
    "question": lambda s: dict(s.questions),
    "contradiction": lambda s: dict(s.contradictions),
    "relation": lambda s: {r.id: r for r in s.relations},
}


class FieldChange(BaseModel):
    """One field whose value differs between the two states."""

    field: str
    from_value: Any = Field(alias="from")
    to_value: Any = Field(alias="to")

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)


class ChangedObject(BaseModel):
    """An object present in both states whose contents differ."""

    object_id: str
    object_type: str
    field_changes: list[FieldChange] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True)


class TypeDiff(BaseModel):
    """Added / removed / changed objects for a single object type."""

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    changed: list[ChangedObject] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


class StateDiff(BaseModel):
    """A structural diff between two `SemanticState` versions.

    `by_type` only carries object types that actually changed, in the fixed
    `_COLLECTIONS` order, so an unchanged type never adds noise to the receipt.
    """

    state_id: str
    from_version: int = Field(ge=0)
    to_version: int = Field(ge=0)
    by_type: dict[str, TypeDiff] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", frozen=True)

    def is_empty(self) -> bool:
        return all(td.is_empty() for td in self.by_type.values())

    @property
    def total_added(self) -> int:
        return sum(len(td.added) for td in self.by_type.values())

    @property
    def total_removed(self) -> int:
        return sum(len(td.removed) for td in self.by_type.values())

    @property
    def total_changed(self) -> int:
        return sum(len(td.changed) for td in self.by_type.values())


def _changed_fields(before: Any, after: Any) -> list[FieldChange]:
    """Field-level diff of two objects of the same type, JSON-normalized."""
    b = before.model_dump(mode="json", by_alias=True)
    a = after.model_dump(mode="json", by_alias=True)
    changes: list[FieldChange] = []
    for field in sorted(set(b) | set(a)):
        if b.get(field) != a.get(field):
            changes.append(
                FieldChange.model_validate(
                    {"field": field, "from": b.get(field), "to": a.get(field)}
                )
            )
    return changes


def _diff_collection(
    object_type: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> TypeDiff:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed: list[ChangedObject] = []
    for object_id in sorted(set(before) & set(after)):
        field_changes = _changed_fields(before[object_id], after[object_id])
        if field_changes:
            changed.append(
                ChangedObject(
                    object_id=object_id,
                    object_type=object_type,
                    field_changes=field_changes,
                )
            )
    return TypeDiff(added=added, removed=removed, changed=changed)


def diff_states(before: SemanticState, after: SemanticState) -> StateDiff:
    """Return a `StateDiff` describing how `after` differs from `before`.

    Neither state is mutated. Only object types with at least one change are
    recorded in `by_type`.
    """
    by_type: dict[str, TypeDiff] = {}
    for object_type, getter in _COLLECTIONS.items():
        td = _diff_collection(object_type, getter(before), getter(after))
        if not td.is_empty():
            by_type[object_type] = td

    return StateDiff(
        state_id=after.state_id,
        from_version=before.state_version,
        to_version=after.state_version,
        by_type=by_type,
    )


__all__ = [
    "ChangedObject",
    "FieldChange",
    "StateDiff",
    "TypeDiff",
    "diff_states",
]
