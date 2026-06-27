"""Retriever — flag evidence gaps as open questions (spec §8.3 step p4).

A claim is an *evidence gap* when nothing solid backs it: it cites no evidence,
or it is under-confident and rests only on lower-reliability spans. Finding
those is a structural read over committed state, not a judgement call, so the
Retriever is deterministic — no model, free, reproducible. It proposes a patch
that opens a `needs_evidence` question for each gap, surfacing "what is missing"
explicitly in the state (and thereby in the Decision Memo).

It reads through its `RETRIEVER` projection and, like every operator, proposes
a `SemanticPatch` — it never mutates state.
"""

from __future__ import annotations

from ..models import (
    PatchStatus,
    Perspective,
    Priority,
    Projection,
    Question,
    QuestionStatus,
    Relation,
    Reliability,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import AddObjects
from ..projection import resolve_view
from ..projection.builder import WEAK_CONFIDENCE_THRESHOLD
from ..projection.view import ProjectionView
from ..runtime.clock import Clock, WallClock
from .base import Operator


class RetrieverOperator(Operator):
    """Open an evidence-gap question for each under-supported claim."""

    name = "retriever_transform"
    version = "0.1.0"
    perspective = Perspective.RETRIEVER
    goal = (
        "Identify claims that lack sufficient evidence and record what sources "
        "are still needed."
    )

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        patch_id: str = "patch_004",
        transform_id: str = "transform_retriever_001",
    ) -> None:
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id

    def _is_gap(self, claim, view: ProjectionView) -> bool:
        if not claim.supporting_evidence:
            return True
        has_high = any(
            (e := view.evidence.get(eid)) is not None and e.reliability == Reliability.HIGH
            for eid in claim.supporting_evidence
        )
        return claim.confidence < WEAK_CONFIDENCE_THRESHOLD and not has_high

    def propose(self, state: SemanticState, projection: Projection) -> SemanticPatch:
        view = resolve_view(projection, state)
        gaps = [cid for cid in sorted(view.claims) if self._is_gap(view.claims[cid], view)]

        started = self.clock.now()
        questions: list[Question] = []
        relations: list[Relation] = []
        write_set: list[str] = []

        for i, cid in enumerate(gaps, start=1):
            claim = view.claims[cid]
            no_evidence = not claim.supporting_evidence
            snippet = claim.text if len(claim.text) <= 90 else claim.text[:89] + "..."
            qid = f"q_gap_{i:03d}"
            if no_evidence:
                text = (
                    f'What source would establish "{snippet}"? '
                    f"({cid} has no supporting evidence on record.)"
                )
                priority = Priority.HIGH
            else:
                text = (
                    f'What stronger source would confirm "{snippet}"? '
                    f"({cid} rests only on lower-reliability evidence.)"
                )
                priority = Priority.MEDIUM
            questions.append(
                Question(
                    id=qid,
                    text=text,
                    status=QuestionStatus.OPEN,
                    priority=priority,
                    linked_objects=[cid],
                    asked_by=self.transform_id,
                )
            )
            write_set.append(qid)
            rid = f"rel_gap_{i:03d}"
            relations.append(
                Relation(
                    id=rid,
                    source=qid,
                    predicate="needs_evidence",
                    target=cid,
                    confidence=1.0,
                    created_by=self.transform_id,
                )
            )
            write_set.append(rid)

        finished = self.clock.now()
        read_set = sorted(view.claims)
        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="retrieve",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=read_set,
            write_set=write_set,
            confidence_changes=[],
            started_at=started,
            finished_at=finished,
            notes=f"Flagged {len(gaps)} evidence gap(s).",
        )
        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=finished,
            read_set=read_set,
            add_objects=AddObjects(questions=questions),
            add_relations=relations,
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


__all__ = ["RetrieverOperator"]
