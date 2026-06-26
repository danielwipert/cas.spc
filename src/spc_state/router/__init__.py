"""Patch router: COMMIT / REVIEW / REJECT / RETRY. See PILOT_SPEC.md §15."""

from .router import decide

__all__ = ["decide"]
