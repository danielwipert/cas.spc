"""Perspective-specific projections of SemanticState. See PILOT_SPEC.md §14.

`build_projection` selects the slice of object IDs a perspective sees;
`resolve_view` materialises that slice into a frozen, isolated `ProjectionView`
an operator can read without any path back to canonical state.

This replaces the Phase 3 passthrough stub (PILOT_SPEC.md §22, Phase 5).
"""

from .builder import (
    WEAK_CONFIDENCE_THRESHOLD,
    build_projection,
    is_evidence_gap,
    is_strong_claim,
    is_weak_claim,
)
from .view import ProjectionView, resolve_view

__all__ = [
    "WEAK_CONFIDENCE_THRESHOLD",
    "ProjectionView",
    "build_projection",
    "is_evidence_gap",
    "is_strong_claim",
    "is_weak_claim",
    "resolve_view",
]
