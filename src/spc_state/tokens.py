"""A deterministic, dependency-free token estimator for the Phase 8 report.

The evaluation metrics (PILOT_SPEC.md §20.4, §20.7) compare how many tokens
each pipeline pushes into its operators. We do **not** need a model-accurate
tokenizer for that — we need a single, deterministic, monotonic proxy applied
identically to both pipelines so the *ratio* is meaningful. We use the common
"~4 characters per token" heuristic on the JSON-normalised payload.

Keeping this in-tree (rather than pulling in `tiktoken`) preserves the project
invariant that a deterministic run is byte-for-byte reproducible with no
network or model-version dependence.
"""

from __future__ import annotations

import json
from math import ceil
from typing import Any

_CHARS_PER_TOKEN = 4


def estimate_tokens(payload: Any) -> int:
    """Estimate the token count of a string or JSON-serialisable payload.

    Strings are measured directly; everything else is serialised to compact,
    key-sorted JSON first so the estimate is stable across dict orderings.
    The result is an *approximation* (see module docstring) — it exists to
    compare two pipelines on the same yardstick, not to bill an API.
    """
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return max(1, ceil(len(text) / _CHARS_PER_TOKEN))


__all__ = ["estimate_tokens"]
