"""Project a `ReasoningReceipt` from actual state history. See PILOT_SPEC.md §18.

The receipt is **not** an after-the-fact explanation (§18.3). Every field is
read out of the committed `SemanticState` versions and their `transform_log`:

- `claims_produced` / `evidence_used` / `assumptions` / `contradictions` are
  the active objects in the final state,
- `open_questions` are the questions still `open` / `in_progress`,
- `transform_history` is the ordered `transform_log`,
- `confidence_map` is computed from claim confidence, evidence count, and
  assumption linkage,
- `audit` is the committed/reviewed/rejected ledger.

`derive_summary` answers the decision question from the state itself: the
answer is the leading active `Hypothesis` (highest confidence). Nothing here
re-prompts a model.
"""

from __future__ import annotations

import datetime as dt

from ..models import (
    ConfidenceMap,
    ObjectStatus,
    QuestionStatus,
    ReasoningReceipt,
    ReceiptAudit,
    ReceiptSummary,
    SemanticState,
)

# Confidence thresholds for the strongest/weakest split. Chosen so the demo
# state separates cleanly; documented here so the boundary is explicit rather
# than magic.
STRONG_CONFIDENCE = 0.8
WEAK_CONFIDENCE = 0.7

NO_RECOMMENDATION = "No recommendation was formed from the available state."


def _active(objects: dict) -> list[str]:
    """Sorted ids of objects whose status is not archived/superseded."""
    return sorted(
        oid
        for oid, obj in objects.items()
        if getattr(obj, "status", ObjectStatus.ACTIVE) == ObjectStatus.ACTIVE
    )


def derive_summary(state: SemanticState, *, question: str | None = None) -> ReceiptSummary:
    """Build the receipt summary, reading the answer out of state.

    The answer is the highest-confidence active hypothesis (the engine's
    standing recommendation). `question` defaults to the state name framed as
    a decision question.
    """
    q = question or f"What does the state conclude about: {state.name}?"

    live = [
        h
        for h in state.hypotheses.values()
        if h.status.value in {"active", "accepted"}
    ]
    if live:
        # Highest confidence wins; ties break on id for determinism.
        best = sorted(live, key=lambda h: (-h.confidence, h.id))[0]
        answer = best.text
    else:
        answer = NO_RECOMMENDATION

    return ReceiptSummary(question=q, answer=answer)


def _confidence_map(state: SemanticState) -> ConfidenceMap:
    active_claims = {
        cid: c
        for cid, c in state.claims.items()
        if c.status == ObjectStatus.ACTIVE
    }

    strongest = sorted(
        (cid for cid, c in active_claims.items() if c.confidence >= STRONG_CONFIDENCE),
        key=lambda cid: (-active_claims[cid].confidence, cid),
    )
    weakest = sorted(
        (cid for cid, c in active_claims.items() if c.confidence < WEAK_CONFIDENCE),
        key=lambda cid: (active_claims[cid].confidence, cid),
    )

    # A claim is assumption-sensitive if it cites an assumption directly or a
    # `depends_on` relation ties it to an assumption.
    dep_targets: dict[str, set[str]] = {}
    for rel in state.relations:
        if rel.predicate == "depends_on" and rel.target in state.assumptions:
            dep_targets.setdefault(rel.source, set()).add(rel.target)

    sensitive = sorted(
        cid
        for cid, c in active_claims.items()
        if c.assumptions or cid in dep_targets
    )

    return ConfidenceMap(
        strongest_claims=strongest,
        weakest_claims=weakest,
        assumption_sensitive_claims=sensitive,
    )


def _open_questions(state: SemanticState) -> list[str]:
    open_states = {QuestionStatus.OPEN, QuestionStatus.IN_PROGRESS}
    return sorted(
        qid for qid, q in state.questions.items() if q.status in open_states
    )


def project_receipt(
    *,
    final_state: SemanticState,
    receipt_id: str,
    generated_at: dt.datetime,
    question: str | None = None,
) -> ReasoningReceipt:
    """Project a `ReasoningReceipt` from the final committed state.

    All history-derived fields (`transform_history`, `audit`) are read from
    `final_state`, which carries the cumulative `transform_log` and audit
    ledger built up across every committed patch.
    """
    summary = derive_summary(final_state, question=question)

    inferred_or_observed = _active(final_state.claims)

    audit = ReceiptAudit(
        committed_patches=list(final_state.audit.committed_patches),
        reviewed_patches=list(final_state.audit.pending_patches),
        rejected_patches=list(final_state.audit.rejected_patches),
    )

    return ReasoningReceipt(
        receipt_id=receipt_id,
        state_id=final_state.state_id,
        state_version=final_state.state_version,
        generated_at=generated_at,
        summary=summary,
        claims_produced=inferred_or_observed,
        evidence_used=_active(final_state.evidence),
        assumptions=_active(final_state.assumptions),
        contradictions=_active(final_state.contradictions),
        open_questions=_open_questions(final_state),
        transform_history=[t.id for t in final_state.transform_log],
        confidence_map=_confidence_map(final_state),
        audit=audit,
    )


__all__ = [
    "NO_RECOMMENDATION",
    "STRONG_CONFIDENCE",
    "WEAK_CONFIDENCE",
    "derive_summary",
    "project_receipt",
]
