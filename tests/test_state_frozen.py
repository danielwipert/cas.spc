"""Phase 2 — enforce the hard invariant from AGENTS.md §I.

`SemanticState` must be frozen at the Pydantic level. Direct attribute
writes must raise `ValidationError`. A non-frozen state would let any
operator silently mutate canonical state, bypassing the patch protocol.

If this test ever fails, the architecture is broken. Do not relax it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from spc_state.models import Claim, EpistemicStatus, SemanticState

UTC = dt.timezone.utc


def _fresh_state() -> SemanticState:
    now = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=UTC)
    return SemanticState(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="Frozen test",
        state_version=1,
        created_at=now,
        updated_at=now,
    )


def test_state_attribute_assignment_raises() -> None:
    state = _fresh_state()
    with pytest.raises(ValidationError):
        state.state_version = 99  # type: ignore[misc]


def test_state_top_level_dict_replacement_raises() -> None:
    state = _fresh_state()
    new_claims = {
        "claim_001": Claim(
            id="claim_001",
            text="Forbidden direct mutation.",
            epistemic_status=EpistemicStatus.SPECULATIVE,
            confidence=0.5,
        )
    }
    with pytest.raises(ValidationError):
        state.claims = new_claims  # type: ignore[misc]


def test_model_copy_with_update_returns_new_state() -> None:
    """The runtime's only legal path to a new state version is `model_copy`.

    This isn't a privilege the operator should ever take, but proving the
    runtime *can* take it (via `model_copy(update={...})`) closes the loop
    on how Phase 3 will produce semantic_state_v002.json from v001.
    """
    state = _fresh_state()
    bumped = state.model_copy(update={"state_version": 2, "previous_state_version": 1})
    assert state.state_version == 1, "original must not be mutated"
    assert bumped.state_version == 2
    assert bumped.previous_state_version == 1


def test_state_extra_fields_forbidden() -> None:
    now = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        SemanticState.model_validate(
            {
                "state_id": "sr_001",
                "project_id": "spc_pilot_001",
                "name": "x",
                "state_version": 0,
                "created_at": now,
                "updated_at": now,
                "schema_version": "0.1.0",
                "extra_smuggled_field": "denied",
            }
        )
