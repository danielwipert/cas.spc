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
    OBSERVED = "observed"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    SPECULATIVE = "speculative"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"


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
