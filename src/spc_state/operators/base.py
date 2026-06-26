"""Operator abstract base. See PILOT_SPEC.md §13.

Every operator obeys this contract (AGENTS.md §II):

1. Receives a `Projection`, not raw `SemanticState`.
2. Returns a `SemanticPatch`.
3. Never mutates state or the projection.
4. Includes `read_set` and `write_set` in its `TransformRecord`.

Phase 3 hands operators *both* the state (for lookups) and the projection
(for scope). Phase 5 will tighten this so operators only see what their
projection includes. The state argument is kept here as a frozen Pydantic
model — the operator cannot mutate it via attribute writes.
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
