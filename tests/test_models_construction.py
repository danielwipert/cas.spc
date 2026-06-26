"""Phase 2 — direct construction of every public model.

Sanity-checks that the Pydantic models accept reasonable values and reject
unreasonable ones (extra="forbid" everywhere, confidence in [0,1], etc.).
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from spc_state.models import (
    AddObjects,
    Assumption,
    Claim,
    ClaimType,
    ConfidenceChange,
    Contradiction,
    ContradictionStatus,
    ContradictionType,
    EpistemicStatus,
    Evidence,
    Impact,
    Inference,
    InferenceType,
    PatchStatus,
    Perspective,
    Projection,
    Question,
    Reliability,
    SemanticPatch,
    SemanticState,
    Severity,
    TransformRecord,
    UpdateObject,
)


UTC = dt.timezone.utc


def _now() -> dt.datetime:
    return dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=UTC)


def test_claim_round_trips() -> None:
    claim = Claim(
        id="claim_001",
        text="Coding assistants speed routine tasks.",
        claim_type=ClaimType.ANALYTICAL,
        epistemic_status=EpistemicStatus.INFERRED,
        confidence=0.74,
        supporting_evidence=["ev_001"],
        assumptions=["assumption_001"],
    )
    payload = claim.model_dump()
    rebuilt = Claim.model_validate(payload)
    assert rebuilt == claim
    assert rebuilt.object_type == "claim"


def test_claim_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Claim.model_validate(
            {
                "id": "claim_001",
                "text": "x",
                "epistemic_status": "inferred",
                "confidence": 0.5,
                "bogus_field": True,
            }
        )


def test_claim_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="claim_001",
            text="x",
            epistemic_status=EpistemicStatus.INFERRED,
            confidence=1.5,
        )


def test_evidence_with_location() -> None:
    ev = Evidence(
        id="ev_001",
        source_type="input_document",
        source_id="doc_001",
        quote_or_span="Prior benchmark studies suggest...",
        location={"page": 4, "section": "introduction"},
        reliability=Reliability.MEDIUM,
    )
    assert ev.location["page"] == 4


def test_assumption_minimal() -> None:
    a = Assumption(
        id="assumption_001",
        text="Benchmark transfer is partial.",
        confidence=0.58,
        impact=Impact.HIGH,
        if_false_effect="Productivity argument weakens.",
    )
    assert a.confidence == 0.58


def test_contradiction_status_enum() -> None:
    c = Contradiction(
        id="contradiction_001",
        claim_a="claim_002",
        claim_b="claim_003",
        contradiction_type=ContradictionType.TENSION,
        severity=Severity.MEDIUM,
    )
    assert c.status is ContradictionStatus.UNRESOLVED


def test_inference_premises_required() -> None:
    inf = Inference(
        id="inf_001",
        inference_type=InferenceType.ABDUCTIVE,
        premises=["claim_001", "assumption_001"],
        conclusion="claim_004",
        confidence_delta=0.12,
        generated_by="transform_planner_001",
    )
    assert inf.confidence_delta == 0.12


def test_question_linking() -> None:
    q = Question(
        id="q_001",
        text="Does evidence transfer to complex work?",
        linked_objects=["claim_001", "assumption_001"],
    )
    assert q.linked_objects == ["claim_001", "assumption_001"]


def test_update_object_uses_aliases() -> None:
    upd = UpdateObject.model_validate(
        {
            "object_id": "claim_001",
            "field": "confidence",
            "from": 0.74,
            "to": 0.62,
            "reason": "Evidence supports routine speed only.",
        }
    )
    # by-name access still works:
    assert upd.from_value == 0.74
    assert upd.to_value == 0.62
    # round-trip preserves the aliased key on the wire:
    dumped = upd.model_dump(by_alias=True)
    assert dumped["from"] == 0.74
    assert dumped["to"] == 0.62


def test_confidence_change_uses_aliases() -> None:
    cc = ConfidenceChange.model_validate(
        {"object_id": "claim_001", "from": 0.74, "to": 0.62, "reason": "x"}
    )
    assert cc.from_value == 0.74


def test_add_objects_is_empty() -> None:
    assert AddObjects().is_empty()
    add = AddObjects(
        questions=[Question(id="q_99", text="why?")],
    )
    assert not add.is_empty()


def test_semantic_patch_construction() -> None:
    tr = TransformRecord(
        id="transform_critic_001",
        transform_type="critique",
        operator="critic_transform",
        operator_version="critic_transform@0.1.0",
        input_state_version=2,
        read_set=["claim_001"],
        write_set=["q_001"],
    )
    patch = SemanticPatch(
        patch_id="patch_003",
        base_state_id="sr_001",
        base_state_version=2,
        proposed_by="critic_transform@0.1.0",
        created_at=_now(),
        read_set=["claim_001"],
        add_objects=AddObjects(questions=[Question(id="q_001", text="?")]),
        transform_record=tr,
    )
    assert patch.status is PatchStatus.PROPOSED
    assert not patch.is_empty()


def test_semantic_state_minimal() -> None:
    state = SemanticState(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="Test",
        state_version=0,
        created_at=_now(),
        updated_at=_now(),
    )
    assert state.schema_version == "0.1.0"
    assert state.all_object_ids() == set()
    assert not state.has_id("claim_001")


def test_projection_construction() -> None:
    proj = Projection(
        projection_id="proj_critic_003",
        base_state_id="sr_001",
        base_state_version=2,
        perspective=Perspective.CRITIC,
        goal="Identify weak claims and unsupported assumptions.",
    )
    assert proj.perspective is Perspective.CRITIC
    assert proj.projection_policy.include_low_confidence_claims is True
