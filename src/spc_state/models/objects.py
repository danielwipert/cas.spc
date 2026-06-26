"""Concrete semantic object types stored inside `SemanticState`.

See PILOT_SPEC.md §10.2, §11.2–§11.7. The spec's example shapes are mirrored
here as Pydantic v2 models. Every object carries a stable `id` and a
discriminating `object_type` literal; objects validate strictly
(`extra="forbid"`) so operator-generated patches that smuggle unknown fields
fail at L1.

Note on relations: the spec's §11.1 stores `relations` as a list (not a dict),
because relations are identified by edges between objects rather than by
standalone identity, but each relation still carries an `id` so patches can
reference it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    ClaimType,
    ContradictionStatus,
    ContradictionType,
    EpistemicStatus,
    HypothesisStatus,
    Impact,
    InferenceType,
    ObjectStatus,
    Priority,
    QuestionStatus,
    Reliability,
    Severity,
)


# ---------------------------------------------------------------------------
# Common field aliases
# ---------------------------------------------------------------------------

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
"""A confidence score in [0, 1]."""


class _Frozenish(BaseModel):
    """Base config for all semantic objects: strict, alias-friendly."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=False)
    # Note: object-level immutability is intentionally not enforced here.
    # Immutability is enforced at the `SemanticState` boundary so the runtime
    # owns commits via `state.model_copy(update=...)`.


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------


class Entity(_Frozenish):
    """A thing in the world (organization, person, product, model, paper)."""

    id: str
    object_type: Literal["entity"] = "entity"
    name: str
    entity_type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    confidence: Confidence = 1.0
    status: ObjectStatus = ObjectStatus.ACTIVE
    extracted_by: str | None = None


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


class Claim(_Frozenish):
    """A proposition the system asserts, infers, or assumes. See spec §11.2."""

    id: str
    object_type: Literal["claim"] = "claim"
    text: str
    claim_type: ClaimType = ClaimType.ANALYTICAL
    epistemic_status: EpistemicStatus
    confidence: Confidence
    status: ObjectStatus = ObjectStatus.ACTIVE
    supporting_evidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    contradicted_by: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    extracted_by: str | None = None


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class Evidence(_Frozenish):
    """An observed source span. See spec §11.3.

    Evidence must not be collapsed into claims. The runtime enforces that
    high-confidence claims either cite at least one `Evidence` or carry an
    explicit `epistemic_status` of `assumed` or `speculative`.
    """

    id: str
    object_type: Literal["evidence"] = "evidence"
    source_type: str
    source_id: str
    quote_or_span: str
    summary: str | None = None
    location: dict[str, str | int] = Field(default_factory=dict)
    reliability: Reliability = Reliability.MEDIUM
    status: ObjectStatus = ObjectStatus.ACTIVE
    extracted_by: str | None = None


# ---------------------------------------------------------------------------
# Assumption
# ---------------------------------------------------------------------------


class Assumption(_Frozenish):
    """A premise the analysis depends on but has not proven. See spec §11.4."""

    id: str
    object_type: Literal["assumption"] = "assumption"
    text: str
    confidence: Confidence
    impact: Impact = Impact.MEDIUM
    if_false_effect: str | None = None
    status: ObjectStatus = ObjectStatus.ACTIVE
    extracted_by: str | None = None


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


class Inference(_Frozenish):
    """A recorded reasoning step. See spec §11.6.

    Inference objects are how the engine remembers that A and B were used to
    derive C, separately from the claim/evidence graph.
    """

    id: str
    object_type: Literal["inference"] = "inference"
    inference_type: InferenceType
    premises: list[str]
    conclusion: str
    confidence_delta: float = Field(ge=-1.0, le=1.0, default=0.0)
    generated_by: str | None = None
    notes: str | None = None
    status: ObjectStatus = ObjectStatus.ACTIVE


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


class Hypothesis(_Frozenish):
    """A live candidate interpretation or plan. See brainstorm §7.10."""

    id: str
    object_type: Literal["hypothesis"] = "hypothesis"
    text: str
    status: HypothesisStatus = HypothesisStatus.ACTIVE
    confidence: Confidence = 0.5
    supporting_claims: list[str] = Field(default_factory=list)
    rival_hypotheses: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    generated_by: str | None = None


# ---------------------------------------------------------------------------
# Question
# ---------------------------------------------------------------------------


class Question(_Frozenish):
    """An unresolved information need. See spec §11.7."""

    id: str
    object_type: Literal["question"] = "question"
    text: str
    status: QuestionStatus = QuestionStatus.OPEN
    priority: Priority = Priority.MEDIUM
    linked_objects: list[str] = Field(default_factory=list)
    asked_by: str | None = None


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------


class Contradiction(_Frozenish):
    """A first-class conflict between two claims. See spec §11.5.

    Contradictions are preserved as objects rather than flattened into a
    single consensus claim; premature consensus is a failure mode (§25.7).
    """

    id: str
    object_type: Literal["contradiction"] = "contradiction"
    claim_a: str
    claim_b: str
    contradiction_type: ContradictionType = ContradictionType.TENSION
    severity: Severity = Severity.MEDIUM
    status: ContradictionStatus = ContradictionStatus.UNRESOLVED
    resolution_options: list[str] = Field(default_factory=list)
    detected_by: str | None = None


# ---------------------------------------------------------------------------
# Relation
# ---------------------------------------------------------------------------


class Relation(_Frozenish):
    """A typed edge between two semantic objects. See brainstorm §7.5."""

    id: str
    object_type: Literal["relation"] = "relation"
    source: str
    predicate: str
    target: str
    confidence: Confidence = 1.0
    created_by: str | None = None
    status: ObjectStatus = ObjectStatus.ACTIVE


__all__ = [
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
]
