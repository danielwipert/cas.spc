"""Per-run LLM cost ledger (TASKS.md T5).

`Runtime.step_llm` already stamps a `TransformRecord` with which model
produced a patch (`model_fingerprint`) and, now, how many tokens every
attempt of that step spent (`token_usage`) — summed across retries, since a
retry is a real, separately billed call, not a free do-over. This module is
the read side: it walks a run's `StepOutcome`s, prices each LLM step's usage
by its model, and writes the total to `runs/<id>/cost_ledger.json`.

A step with no `model_fingerprint` is deterministic (no model call, e.g. the
Retriever) and contributes nothing. A step where every attempt was
unparseable prose has no patch at all — no `TransformRecord` to read cost
from — so it's absent from the ledger even though it cost real tokens; this
mirrors the ledger's literal scope (spec/TASKS.md T5: "summing tokens/cost
per TransformRecord"), not a full attempt-by-attempt accounting.

Pure and read-only: never re-runs a model, never estimates its own numbers —
it only sums what `TransformRecord.token_usage` already recorded and prices
it via `providers.openrouter.estimate_cost_usd`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .providers.openrouter import estimate_cost_usd
from .runtime import StepOutcome
from .store import RunPaths


@dataclass(frozen=True)
class CostLedgerEntry:
    """One LLM step's cost — one row per `TransformRecord` that spent tokens."""

    transform_id: str
    operator: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, object]:
        return {
            "transform_id": self.transform_id,
            "operator": self.operator,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


@dataclass(frozen=True)
class CostLedger:
    """A run's LLM spend: one entry per model-backed step, plus the totals."""

    run_id: str
    entries: list[CostLedgerEntry] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(e.total_tokens for e in self.entries)

    @property
    def total_estimated_cost_usd(self) -> float:
        return round(sum(e.estimated_cost_usd for e in self.entries), 6)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "entries": [e.to_dict() for e in self.entries],
            "total_tokens": self.total_tokens,
            "total_estimated_cost_usd": self.total_estimated_cost_usd,
        }


def build_cost_ledger(run_id: str, steps: list[StepOutcome]) -> CostLedger:
    """Build a `CostLedger` from a run's steps. Pure — reads only, no I/O."""
    entries: list[CostLedgerEntry] = []
    for step in steps:
        if step.patch is None:
            continue
        record = step.patch.transform_record
        fingerprint = record.model_fingerprint
        if fingerprint is None:
            continue  # a deterministic step — no model call, no cost
        usage = record.token_usage
        prompt_tokens = usage.prompt_tokens if usage is not None else 0
        completion_tokens = usage.completion_tokens if usage is not None else 0
        cost = (
            estimate_cost_usd(fingerprint.model, usage) if usage is not None else 0.0
        )
        entries.append(
            CostLedgerEntry(
                transform_id=record.id,
                operator=record.operator,
                provider=fingerprint.provider,
                model=fingerprint.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=cost,
            )
        )
    return CostLedger(run_id=run_id, entries=entries)


def write_cost_ledger(paths: RunPaths, ledger: CostLedger) -> Path:
    """Write `runs/<id>/cost_ledger.json`; return its path."""
    path = paths.cost_ledger_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = ["CostLedger", "CostLedgerEntry", "build_cost_ledger", "write_cost_ledger"]
