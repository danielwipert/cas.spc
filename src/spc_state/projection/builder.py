"""Phase 5 projection builder: perspective-specific views of `SemanticState`.

Replaces the Phase 3 `passthrough` stub. Each perspective in PILOT_SPEC.md
§14.2 selects a different slice of state:

| Perspective | Primary focus |
|-------------|---------------|
| Planner     | goals, options, dependencies, candidate paths |
| Critic      | assumptions, contradictions, weak evidence, failure modes |
| Retriever   | evidence gaps, source targets, open questions |
| Verifier    | claim/evidence alignment, provenance, confidence sanity |
| Writer      | high-confidence claims, narrative order, audience, caveats |
| Executive   | recommendation, risks, tradeoffs, decision options |

The builder only *selects* object IDs; it never mutates canonical state
(spec §14.4). `Extract` runs against an empty/initial state, so its
perspective is treated as a passthrough.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from ..models import (
    Claim,
    Impact,
    IncludedObjects,
    ObjectStatus,
    Perspective,
    Priority,
    Projection,
    ProjectionPolicy,
    QuestionStatus,
    Reliability,
    SemanticState,
)
from ..models.enums import EpistemicStatus

# A claim is "weak" below this confidence, or whenever it is not grounded in
# observation/verification. Writers want the complement; critics want these.
WEAK_CONFIDENCE_THRESHOLD = 0.75

_UNGROUNDED = {
    EpistemicStatus.INFERRED,
    EpistemicStatus.ASSUMED,
    EpistemicStatus.SPECULATIVE,
}
_PROVENANCE_FREE = {EpistemicStatus.ASSUMED, EpistemicStatus.SPECULATIVE}
_WEAK_RELIABILITY = {Reliability.LOW, Reliability.MEDIUM}

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def is_weak_claim(claim: Claim) -> bool:
    """A claim a critic should scrutinise: low confidence or ungrounded."""
    return claim.confidence < WEAK_CONFIDENCE_THRESHOLD or claim.epistemic_status in _UNGROUNDED


def is_strong_claim(claim: Claim) -> bool:
    """A claim a writer can lean on: high confidence and grounded."""
    return claim.confidence >= WEAK_CONFIDENCE_THRESHOLD and claim.epistemic_status not in _PROVENANCE_FREE


def is_evidence_gap(claim: Claim) -> bool:
    """A claim a retriever should chase: no evidence yet, or still weak."""
    return not claim.supporting_evidence or claim.confidence < WEAK_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _active(container: Mapping[str, _T], *, include_archived: bool) -> dict[str, _T]:
    """Drop archived objects unless explicitly asked to keep them."""
    out: dict[str, _T] = {}
    for obj_id, obj in container.items():
        status = getattr(obj, "status", ObjectStatus.ACTIVE)
        if not include_archived and status == ObjectStatus.ARCHIVED:
            continue
        out[obj_id] = obj
    return out


# ---------------------------------------------------------------------------
# Per-perspective selection
# ---------------------------------------------------------------------------


def _select(
    perspective: Perspective,
    state: SemanticState,
    *,
    include_archived: bool,
) -> tuple[IncludedObjects, ProjectionPolicy]:
    entities = _active(state.entities, include_archived=include_archived)
    claims = _active(state.claims, include_archived=include_archived)
    evidence = _active(state.evidence, include_archived=include_archived)
    assumptions = _active(state.assumptions, include_archived=include_archived)
    inferences = _active(state.inferences, include_archived=include_archived)
    hypotheses = _active(state.hypotheses, include_archived=include_archived)
    questions = _active(state.questions, include_archived=include_archived)
    contradictions = _active(state.contradictions, include_archived=include_archived)

    # `sel` accumulates the selected IDs per type; relations are derived last.
    sel: dict[str, list[str]] = {}
    policy = ProjectionPolicy(include_archived=include_archived)

    if perspective == Perspective.EXTRACT:
        # Extract runs on the initial/empty state — give it everything active.
        sel = {
            "entities": list(entities),
            "claims": list(claims),
            "evidence": list(evidence),
            "assumptions": list(assumptions),
            "inferences": list(inferences),
            "hypotheses": list(hypotheses),
            "questions": list(questions),
            "contradictions": list(contradictions),
        }

    elif perspective == Perspective.PLANNER:
        # Goals, options, dependencies, candidate paths — the decision skeleton.
        sel = {
            "entities": list(entities),
            "claims": list(claims),
            "assumptions": list(assumptions),
            "inferences": list(inferences),
            "hypotheses": list(hypotheses),
            "questions": list(questions),
            "contradictions": list(contradictions),
        }
        policy = ProjectionPolicy(
            include_evidence_spans=False,
            include_dependency_edges=True,
            include_archived=include_archived,
        )

    elif perspective == Perspective.CRITIC:
        # Assumptions, contradictions, weak evidence, failure modes.
        sel = {
            "claims": [cid for cid, c in claims.items() if is_weak_claim(c)],
            "evidence": [eid for eid, e in evidence.items() if e.reliability in _WEAK_RELIABILITY],
            "assumptions": list(assumptions),
            "inferences": list(inferences),
            "questions": list(questions),
            "contradictions": list(contradictions),
        }
        policy = ProjectionPolicy(
            include_low_confidence_claims=True,
            include_contradictions=True,
            include_archived=include_archived,
        )

    elif perspective == Perspective.RETRIEVER:
        # Evidence gaps, source targets, open questions.
        sel = {
            "claims": [cid for cid, c in claims.items() if is_evidence_gap(c)],
            "evidence": list(evidence),
            "assumptions": list(assumptions),
            "questions": [qid for qid, q in questions.items() if q.status == QuestionStatus.OPEN],
        }
        policy = ProjectionPolicy(
            include_evidence_spans=True,
            include_archived=include_archived,
        )

    elif perspective == Perspective.VERIFIER:
        # Claim/evidence alignment, provenance, confidence sanity.
        sel = {
            "claims": list(claims),
            "evidence": list(evidence),
            "assumptions": list(assumptions),
            "inferences": list(inferences),
            "contradictions": list(contradictions),
        }
        policy = ProjectionPolicy(
            include_evidence_spans=True,
            include_dependency_edges=True,
            include_archived=include_archived,
        )

    elif perspective == Perspective.WRITER:
        # High-confidence claims, narrative, audience, caveats.
        sel = {
            "claims": [cid for cid, c in claims.items() if is_strong_claim(c)],
            "assumptions": [aid for aid, a in assumptions.items() if a.impact == Impact.HIGH],
            "hypotheses": list(hypotheses),
            "contradictions": list(contradictions),
        }
        policy = ProjectionPolicy(
            include_low_confidence_claims=False,
            include_evidence_spans=False,
            include_writer_notes=True,
            include_archived=include_archived,
        )

    elif perspective == Perspective.EXECUTIVE:
        # Recommendation, risks, tradeoffs, decision options.
        sel = {
            "claims": [cid for cid, c in claims.items() if is_strong_claim(c)],
            "assumptions": [aid for aid, a in assumptions.items() if a.impact == Impact.HIGH],
            "hypotheses": list(hypotheses),
            "questions": [
                qid
                for qid, q in questions.items()
                if q.status == QuestionStatus.OPEN and q.priority == Priority.HIGH
            ],
            "contradictions": list(contradictions),
        }
        policy = ProjectionPolicy(
            include_low_confidence_claims=False,
            include_archived=include_archived,
        )

    else:  # pragma: no cover - defensive; every Perspective is handled above.
        raise ValueError(f"Unknown perspective: {perspective!r}")

    # Relations are included only when *both* endpoints are in the slice, so
    # the projection stays referentially closed (no dangling edges).
    if policy.include_dependency_edges:
        selected: set[str] = set()
        for ids in sel.values():
            selected.update(ids)
        sel["relations"] = [
            r.id
            for r in state.relations
            if (include_archived or r.status != ObjectStatus.ARCHIVED)
            and r.source in selected
            and r.target in selected
        ]

    return IncludedObjects(**sel), policy


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_projection(
    state: SemanticState,
    *,
    perspective: Perspective,
    goal: str,
    include_archived: bool = False,
) -> Projection:
    """Build a perspective-specific `Projection` of `state`.

    The projection lists only the object IDs the perspective needs. It never
    mutates canonical state (spec §14.4). Use `resolve_view` to materialise an
    isolated, read-only view of the selected objects for an operator.
    """
    included, policy = _select(perspective, state, include_archived=include_archived)
    return Projection(
        projection_id=f"proj_{perspective.value}_v{state.state_version:03d}",
        base_state_id=state.state_id,
        base_state_version=state.state_version,
        perspective=perspective,
        goal=goal,
        included_objects=included,
        projection_policy=policy,
    )


__all__ = [
    "WEAK_CONFIDENCE_THRESHOLD",
    "build_projection",
    "is_evidence_gap",
    "is_strong_claim",
    "is_weak_claim",
]
