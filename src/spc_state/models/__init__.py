"""Public model API for the SPC Shared Semantic State Engine.

Import the model types from here, e.g.::

    from spc_state.models import SemanticState, SemanticPatch, Claim

Implementation lives in the submodules; this file curates the public surface
and re-exports the spec-defined types.
"""

from __future__ import annotations

from .enums import (
    ClaimType,
    ContradictionStatus,
    ContradictionType,
    EpistemicStatus,
    HypothesisStatus,
    Impact,
    InferenceType,
    ObjectStatus,
    ObjectType,
    PatchStatus,
    Perspective,
    Priority,
    QuestionStatus,
    Reliability,
    RouterDecision,
    Severity,
    StateStatus,
    TransformType,
    ValidationLayer,
    ValidationSeverity,
)
from .objects import (
    Assumption,
    Claim,
    Confidence,
    Contradiction,
    Entity,
    Evidence,
    Hypothesis,
    Inference,
    Question,
    Relation,
)
from .patch import AddObjects, ArchiveObject, SemanticPatch, UpdateObject
from .projection import IncludedObjects, Projection, ProjectionPolicy
from .receipt import ConfidenceMap, ReasoningReceipt, ReceiptAudit, ReceiptSummary
from .state import SCHEMA_VERSION, SemanticState, StateAuditTallies
from .transform import ConfidenceChange, ModelFingerprint, TransformRecord
from .validation import ValidationIssue, ValidationReport

__all__ = [
    # state + container
    "SCHEMA_VERSION",
    "SemanticState",
    "StateAuditTallies",
    # objects
    "Assumption",
    "Claim",
    "Confidence",
    "Contradiction",
    "Entity",
    "Evidence",
    "Hypothesis",
    "Inference",
    "Question",
    "Relation",
    # patch
    "AddObjects",
    "ArchiveObject",
    "SemanticPatch",
    "UpdateObject",
    # transform
    "ConfidenceChange",
    "ModelFingerprint",
    "TransformRecord",
    # validation
    "ValidationIssue",
    "ValidationReport",
    # projection
    "IncludedObjects",
    "Projection",
    "ProjectionPolicy",
    # receipt
    "ConfidenceMap",
    "ReasoningReceipt",
    "ReceiptAudit",
    "ReceiptSummary",
    # enums
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
