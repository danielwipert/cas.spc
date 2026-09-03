"""Patch router: COMMIT / REVIEW / REJECT / RETRY. See PILOT_SPEC.md §15."""

from .router import decide, decide_llm

__all__ = ["decide", "decide_llm"]
