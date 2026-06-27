"""Operator abstract base. See PILOT_SPEC.md §13.

Every operator obeys this contract (AGENTS.md §II):

1. Receives a `Projection`, not raw `SemanticState`.
2. Returns a `SemanticPatch`.
3. Never mutates state or the projection.
4. Includes `read_set` and `write_set` in its `TransformRecord`.

Operators are handed *both* the frozen `SemanticState` and the perspective
`Projection`, but they read through `resolve_view(projection, state)` (Phase
5) so they only ever touch the slice their projection includes — a frozen,
deep-copied `ProjectionView` with no path back to canonical state. The raw
`state` argument remains a frozen Pydantic model; the operator cannot mutate
it via attribute writes either.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Perspective, Projection, SemanticPatch, SemanticState


class Operator(ABC):
    """The abstract interface every operator implements."""

    name: str
    version: str
    perspective: Perspective
    goal: str

    @abstractmethod
    def propose(
        self,
        state: SemanticState,
        projection: Projection,
    ) -> SemanticPatch:
        """Return a `SemanticPatch` proposing the operator's contribution.

        Implementations must:
        - never set attributes on `state` or `projection`,
        - populate `transform_record.read_set` and `write_set`,
        - leave `transform_record.output_state_version` as `None` (the
          runtime fills it on commit).
        """

    def fully_qualified(self) -> str:
        return f"{self.name}@{self.version}"


__all__ = ["Operator"]
