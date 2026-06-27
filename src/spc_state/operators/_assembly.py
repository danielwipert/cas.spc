"""Shared helpers for LLM operators that *assemble* a patch from model content.

The LLM-backed operators (extract, planner, critic) all follow the same shape:
the model returns compact JSON content, and the operator assembles a canonical
`SemanticPatch` around it (ids, transform record, provenance wiring). These
helpers cover the parts every one of them needs — tolerant JSON parsing, loose
enum coercion, confidence clamping — so the operators stay focused on their
own content shape.

On any assembly failure the operator returns the model's raw text instead, so
the runtime's validator reports `JSON_DECODE` and the retry loop kicks in
(`Runtime.step_llm`). `LLMAssemblyError` is that signal.
"""

from __future__ import annotations

import json
from typing import Any


class LLMAssemblyError(ValueError):
    """Model output could not be assembled into a patch (-> raw text -> RETRY)."""


def load_json(raw: str) -> Any:
    """Parse JSON, tolerating a ```json fenced block the model may wrap it in."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMAssemblyError(f"Output was not valid JSON: {exc}") from exc


def coerce_enum(value: Any, mapping: dict[str, Any], default: Any) -> Any:
    """Map a loose model string onto an enum, tolerating case and synonyms."""
    if not isinstance(value, str):
        return default
    return mapping.get(value.strip().lower(), default)


def clamp_confidence(value: Any, *, default: float = 0.5) -> float:
    """Coerce a model-supplied confidence to a float in [0, 1]."""
    try:
        c = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, c))


__all__ = ["LLMAssemblyError", "clamp_confidence", "coerce_enum", "load_json"]
