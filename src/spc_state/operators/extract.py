"""Deterministic Extract operator for the AI-coding-assistant demo doc.

Phase 3 ships hand-crafted extractions keyed to a known input. This is the
explicit shortcut: Extract recognises the demo scenario by a marker phrase
and emits a canned patch. Phase 6+ replaces this with an LLM operator
returning the same patch shape under structured-output enforcement.
"""

from __future__ import annotations

from ..models import (
    Assumption,
    Claim,
    ClaimType,
    EpistemicStatus,
    Evidence,
    Impact,
    PatchStatus,
    Perspective,
    Projection,
    Reliability,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import AddObjects
from ..runtime.clock import Clock
from .base import Operator


class ExtractOperator(Operator):
    name = "extract_transform"
    version = "0.1.0"
    perspective = Perspective.EXTRACT
    goal = (
        "Extract initial entities, claims, evidence, and assumptions from the "
        "input document."
    )

    MARKER = "AI coding assistant"

    def __init__(
        self,
        *,
        input_text: str,
        clock: Clock,
        patch_id: str = "patch_001",
        transform_id: str = "transform_extract_001",
    ) -> None:
        self.input_text = input_text
        self.clock = clock
        self.patch_id = patch_id
        self.transform_id = transform_id

    def propose(self, state: SemanticState, projection: Projection) -> SemanticPatch:
        if self.MARKER not in self.input_text:
            raise NotImplementedError(
                "ExtractOperator (Phase 3 deterministic) only handles the "
                "AI-coding-assistant demo scenario. Add a scenario fixture or "
                "swap in an LLM operator (Phase 7) for other documents."
            )

        started = self.clock.now()

        claim_001 = Claim(
            id="claim_001",
            text="AI coding assistants may improve routine engineering task speed.",
            claim_type=ClaimType.ANALYTICAL,
            epistemic_status=EpistemicStatus.INFERRED,
            confidence=0.74,
            supporting_evidence=["ev_001"],
            assumptions=["assumption_001"],
            extracted_by=self.transform_id,
        )
        claim_002 = Claim(
            id="claim_002",
            text="Usage-based costs are a material concern raised by finance.",
            claim_type=ClaimType.ANALYTICAL,
            epistemic_status=EpistemicStatus.OBSERVED,
            confidence=0.85,
            supporting_evidence=["ev_002"],
            extracted_by=self.transform_id,
        )
        claim_003 = Claim(
            id="claim_003",
            text="Adoption may expose proprietary source code to a third-party service.",
            claim_type=ClaimType.ANALYTICAL,
            epistemic_status=EpistemicStatus.OBSERVED,
            confidence=0.83,
            supporting_evidence=["ev_003"],
            extracted_by=self.transform_id,
        )

        ev_001 = Evidence(
            id="ev_001",
            source_type="input_document",
            source_id="doc_001",
            quote_or_span=(
                "Prior benchmark studies suggest coding assistants can accelerate "
                "routine tasks."
            ),
            reliability=Reliability.MEDIUM,
            extracted_by=self.transform_id,
        )
        ev_002 = Evidence(
            id="ev_002",
            source_type="input_document",
            source_id="doc_001",
            quote_or_span="finance is concerned about usage-based costs",
            reliability=Reliability.HIGH,
            extracted_by=self.transform_id,
        )
        ev_003 = Evidence(
            id="ev_003",
            source_type="input_document",
            source_id="doc_001",
            quote_or_span="Security has concerns about source code exposure.",
            reliability=Reliability.HIGH,
            extracted_by=self.transform_id,
        )

        assumption_001 = Assumption(
            id="assumption_001",
            text=(
                "Benchmark improvements will partially transfer to this "
                "company's engineering workflow."
            ),
            confidence=0.58,
            impact=Impact.HIGH,
            if_false_effect="The productivity justification weakens materially.",
            extracted_by=self.transform_id,
        )

        new_ids = [
            "claim_001",
            "claim_002",
            "claim_003",
            "ev_001",
            "ev_002",
            "ev_003",
            "assumption_001",
        ]

        finished = self.clock.now()

        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="extract",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=[],
            write_set=new_ids,
            confidence_changes=[],
            started_at=started,
            finished_at=finished,
            notes="Deterministic extraction of the AI-coding-assistant demo doc.",
        )

        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=finished,
            read_set=[],
            add_objects=AddObjects(
                claims=[claim_001, claim_002, claim_003],
                evidence=[ev_001, ev_002, ev_003],
                assumptions=[assumption_001],
            ),
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


__all__ = ["ExtractOperator"]
