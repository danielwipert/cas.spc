"""Enumerated vocabularies for SPC semantic objects and runtime decisions.

See PILOT_SPEC.md §10–18. Where the spec uses an open-ended string (e.g.,
`source_type`), we keep `str` in the model rather than enumerating, so the
schema stays open to evolution. Enums are reserved for vocabularies the
runtime needs to branch on.
"""

from __future__ import annotations

from enum import Enum


class ObjectType(str, Enum):
    ENTITY = "entity"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    ASSUMPTION = "assumption"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"
    QUESTION = "question"
    CONTRADICTION = "contradiction"
    RELATION = "relation"


class EpistemicStatus(str, Enum):
    """**How a claim entered state.** See PILOT_SPEC.md §11.2.

    One axis, one question, five mutually exclusive answers. T20 narrowed it to
    that: it used to carry seven members answering *three* different questions —
    how a claim was acquired, how well it is supported (`VERIFIED`), and whether
    anything contradicts it (`CONTRADICTED`). A claim has a value on all three at
    once and one field holds one, so every write on a second axis destroyed the
    first: T19's corroboration overwrote `REPORTED` with `VERIFIED`, although a
    corroborated claim is still reported — it was read out of a document, and a
    second source agreeing does not change that.

    The other two axes are **derived, never stored** (`spc_state.epistemics`),
    because state already holds what they need: corroboration from the spans a
    claim cites and the sources behind them, conflict from the `Contradiction`
    objects naming it. That is the T14/T15/T16 rule — derive it from structure,
    do not let anyone assert it — applied to the type those judgements land in.

    `OBSERVED` and `REPORTED` are the distinction T17 drew, and the difference
    matters more than it looks. Reading a document establishes **that the
    document says so** — never that the thing is so. An extractor holding a
    press release has observed the press release; it has not observed the
    merger. So a claim drawn from a source is `REPORTED`, and `OBSERVED` is
    reserved for an operator that genuinely saw the thing itself.

    Claims stored before T20 may carry `verified` or `contradicted` on disk;
    `Claim` migrates both to `reported` on load, which is where they came from.
    """

    OBSERVED = "observed"
    REPORTED = "reported"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    SPECULATIVE = "speculative"

    @property
    def is_grounded(self) -> bool:
        """Does this claim trace to something outside the reasoning itself?

        Replaces `projection.builder._UNGROUNDED`. `REPORTED` is deliberately
        grounded: a named source says it and the span is on record. What it
        lacks is *first-hand* observation, which the label says out loud (T17)
        rather than a projection filter re-litigating it — how much the source
        is worth is already priced by T14/T16.
        """
        return self in (EpistemicStatus.OBSERVED, EpistemicStatus.REPORTED)

    @property
    def needs_provenance(self) -> bool:
        """Must a claim with this status cite evidence or an assumption?

        Replaces `projection.builder._PROVENANCE_FREE` and
        `validation.l2._PROVENANCE_FREE_STATUSES`, which were the same two-member
        set maintained twice. `ASSUMED` and `SPECULATIVE` are exempt because both
        say out loud that nothing supports them yet.
        """
        return self not in (EpistemicStatus.ASSUMED, EpistemicStatus.SPECULATIVE)


#: Statuses retired by T20 and what a stored claim carrying one becomes. Both
#: were answers to a *different* question than this axis asks, and both were
#: reached from `reported` — corroboration promoted it, and nothing ever emitted
#: `contradicted` at all (T3 gave conflict its own first-class object).
RETIRED_EPISTEMIC_STATUSES = {
    "verified": EpistemicStatus.REPORTED,
    "contradicted": EpistemicStatus.REPORTED,
}


class ObjectStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class ClaimType(str, Enum):
    FACTUAL = "factual_claim"
    ANALYTICAL = "analytical_claim"
    PREDICTIVE = "predictive_claim"
    NORMATIVE = "normative_claim"


class Reliability(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContradictionType(str, Enum):
    """See PILOT_SPEC.md §11.5."""

    FACTUAL_CONFLICT = "factual_conflict"
    TENSION = "tension"
    SCOPE_MISMATCH = "scope_mismatch"
    TEMPORAL_CONFLICT = "temporal_conflict"


class ContradictionStatus(str, Enum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class QuestionStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ANSWERED = "answered"
    CLOSED = "closed"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InferenceType(str, Enum):
    DEDUCTIVE = "deductive"
    INDUCTIVE = "inductive"
    ABDUCTIVE = "abductive"


class HypothesisStatus(str, Enum):
    ACTIVE = "active"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


class PatchStatus(str, Enum):
    """See PILOT_SPEC.md §12.4."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    COMMITTED = "committed"
    REJECTED = "rejected"
    PENDING_REVIEW = "pending_review"
    SUPERSEDED = "superseded"
    FAILED_VALIDATION = "failed_validation"


class RouterDecision(str, Enum):
    """See PILOT_SPEC.md §15.2."""

    COMMIT = "COMMIT"
    REVIEW = "REVIEW"
    REJECT = "REJECT"
    RETRY = "RETRY"
    FAIL = "FAIL"


class Perspective(str, Enum):
    """See PILOT_SPEC.md §14.2.

    `EXTRACT` is not in the spec's listed set; it is added here because the
    Extract operator runs against an empty/initial state where the other
    perspectives don't yet make sense.
    """

    EXTRACT = "extract"
    PLANNER = "planner"
    CRITIC = "critic"
    RETRIEVER = "retriever"
    VERIFIER = "verifier"
    WRITER = "writer"
    EXECUTIVE = "executive"


class StateStatus(str, Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    ARCHIVED = "archived"


class TransformType(str, Enum):
    """Common transform kinds. The model leaves this open via plain str
    everywhere it appears; this enum is provided as a vocabulary aid for
    deterministic operators.
    """

    EXTRACT = "extract"
    PLAN = "plan"
    CRITIQUE = "critique"
    RETRIEVE = "retrieve"
    VERIFY = "verify"
    WRITE = "write"


class ValidationLayer(str, Enum):
    """See PILOT_SPEC.md §16."""

    L1_SCHEMA = "L1_schema"
    L2_REFERENTIAL = "L2_referential"
    L3_MODEL = "L3_model"
    L4_HEURISTIC = "L4_heuristic"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


__all__ = [
    "ClaimType",
    "ContradictionStatus",
    "ContradictionType",
    "EpistemicStatus",
    "HypothesisStatus",
    "Impact",
    "InferenceType",
    "ObjectStatus",
    "ObjectType",
    "PatchStatus",
    "Perspective",
    "Priority",
    "QuestionStatus",
    "Reliability",
    "RouterDecision",
    "Severity",
    "StateStatus",
    "TransformType",
    "ValidationLayer",
    "ValidationSeverity",
]
