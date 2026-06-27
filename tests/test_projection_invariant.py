"""Phase 5 — the projection invariant (PILOT_SPEC.md §14.4).

> A projection may hide or emphasize parts of state, but it must not mutate
> canonical state.

We enforce this two ways:

1. The `Projection` an operator receives is frozen — attribute writes raise.
2. `resolve_view` hands the operator a frozen, deep-copied `ProjectionView`
   that (a) contains only its slice, and (b) shares no object references with
   canonical state, so even in-place edits cannot leak back.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spc_state.models import Perspective, SemanticState
from spc_state.projection import build_projection, resolve_view

GOAL = "test goal"


def _final(demo_history: list[SemanticState]) -> SemanticState:
    return demo_history[3]


# ---------------------------------------------------------------------------
# 1. The projection an operator receives cannot be mutated.
# ---------------------------------------------------------------------------


def test_projection_is_frozen(demo_history) -> None:
    proj = build_projection(_final(demo_history), perspective=Perspective.CRITIC, goal=GOAL)
    with pytest.raises(ValidationError):
        proj.goal = "hijacked"  # type: ignore[misc]


def test_included_objects_is_frozen(demo_history) -> None:
    proj = build_projection(_final(demo_history), perspective=Perspective.CRITIC, goal=GOAL)
    with pytest.raises(ValidationError):
        proj.included_objects.claims = ["claim_002"]  # type: ignore[misc]


def test_projection_policy_is_frozen(demo_history) -> None:
    proj = build_projection(_final(demo_history), perspective=Perspective.WRITER, goal=GOAL)
    with pytest.raises(ValidationError):
        proj.projection_policy.include_writer_notes = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Operators only see their slice.
# ---------------------------------------------------------------------------


def test_view_contains_only_the_projected_slice(demo_history) -> None:
    state = _final(demo_history)
    proj = build_projection(state, perspective=Perspective.CRITIC, goal=GOAL)
    view = resolve_view(proj, state)

    # The critic's slice is the weak claim only — the strong claims are absent.
    assert set(view.claims) == {"claim_001"}
    assert "claim_002" not in view.claims
    assert "claim_003" not in view.claims
    # Everything the view exposes is a subset of what the projection declared.
    declared = (
        set(proj.included_objects.claims)
        | set(proj.included_objects.evidence)
        | set(proj.included_objects.assumptions)
        | set(proj.included_objects.inferences)
        | set(proj.included_objects.questions)
        | set(proj.included_objects.contradictions)
        | set(proj.included_objects.relations)
    )
    assert view.object_ids() <= declared


def test_writer_view_hides_the_weak_claim(demo_history) -> None:
    state = _final(demo_history)
    view = resolve_view(
        build_projection(state, perspective=Perspective.WRITER, goal=GOAL), state
    )
    assert "claim_001" not in view.claims
    assert set(view.claims) == {"claim_002", "claim_003"}


# ---------------------------------------------------------------------------
# 3. The view cannot mutate canonical state.
# ---------------------------------------------------------------------------


def test_view_is_frozen(demo_history) -> None:
    state = _final(demo_history)
    view = resolve_view(
        build_projection(state, perspective=Perspective.CRITIC, goal=GOAL), state
    )
    with pytest.raises(ValidationError):
        view.claims = {}  # type: ignore[misc]


def test_editing_a_view_object_does_not_touch_state(demo_history) -> None:
    state = _final(demo_history)
    view = resolve_view(
        build_projection(state, perspective=Perspective.CRITIC, goal=GOAL), state
    )

    before = state.claims["claim_001"].confidence
    # The objects in the view are deep copies — mutating one is allowed but
    # local. It must not reach back into the frozen canonical state.
    view.claims["claim_001"].confidence = 0.01
    assert view.claims["claim_001"].confidence == 0.01
    assert state.claims["claim_001"].confidence == before
    assert state.claims["claim_001"].confidence != 0.01


def test_view_objects_are_not_the_same_instances_as_state(demo_history) -> None:
    state = _final(demo_history)
    view = resolve_view(
        build_projection(state, perspective=Perspective.CRITIC, goal=GOAL), state
    )
    assert view.claims["claim_001"] is not state.claims["claim_001"]
