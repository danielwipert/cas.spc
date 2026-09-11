"""Per-run LLM cost ledger (TASKS.md T5).

`Runtime.step_llm` already stamps a `TransformRecord` with which model
produced a patch (`model_fingerprint`) and, now, how many tokens every
attempt of that step spent (`token_usage`) — summed across retries, since a
retry is a real, separately billed call, not a free do-over. This module is
the read side: it walks a run's `StepOutcome`s, prices each LLM step's usage
by its model, and writes the total to `runs/<id>/cost_ledger.json`.

A step with no model fingerprint is deterministic (no model call, e.g. the
Retriever) and contributes nothing.

**Every billed call is counted, committed or not (T13).** T5 keyed the ledger
to `TransformRecord`, so a step whose every attempt failed to parse — having
no patch, and therefore no record — spent real money that appeared nowhere.
A run that lost its extraction to three truncated replies reported the cost
of the *other* four steps and called it the total. The ledger now reads spend
off the `StepOutcome` itself, which carries it whether or not anything
committed, and marks each row `committed` so attribution and reconciliation
stay separable: filter to committed rows to ask what the state cost, sum
every row to ask what the provider will bill.

Pure and read-only: never re-runs a model, never estimates its own numbers —
it only sums the usage the provider already reported and prices it via
`providers.openrouter.estimate_cost_usd`.
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
    """One model-backed step's cost, across every attempt it took."""

    #: `None` when the step committed nothing, so there is no transform to name.
    transform_id: str | None
    operator: str
    provider: str
    model: str
    #: Billed calls this row covers. A retry is a real call, not a free retry.
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    #: False when every attempt failed — spend with nothing in state to show.
    committed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "transform_id": self.transform_id,
            "operator": self.operator,
            "provider": self.provider,
            "model": self.model,
            "attempts": self.attempts,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "committed": self.committed,
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

    @property
    def uncommitted_tokens(self) -> int:
        """Spend that bought nothing: steps where every attempt failed."""
        return sum(e.total_tokens for e in self.entries if not e.committed)

    @property
    def uncommitted_estimated_cost_usd(self) -> float:
        return round(
            sum(e.estimated_cost_usd for e in self.entries if not e.committed), 6
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "entries": [e.to_dict() for e in self.entries],
            "total_tokens": self.total_tokens,
            "total_estimated_cost_usd": self.total_estimated_cost_usd,
            "uncommitted_tokens": self.uncommitted_tokens,
            "uncommitted_estimated_cost_usd": self.uncommitted_estimated_cost_usd,
        }


def build_cost_ledger(run_id: str, steps: list[StepOutcome]) -> CostLedger:
    """Build a `CostLedger` from a run's steps. Pure — reads only, no I/O."""
    entries: list[CostLedgerEntry] = []
    for step in steps:
        record = step.patch.transform_record if step.patch is not None else None

        # Prefer what the step itself recorded: it is the usage the provider
        # reported, summed over every attempt, and it survives a step that
        # produced no patch. The record is the fallback for a patch that
        # arrived carrying its own usage.
        fingerprint = step.fingerprint or (
            record.model_fingerprint if record is not None else None
        )
        if fingerprint is None:
            continue  # a deterministic step — no model call, no cost

        usage = step.usage or (record.token_usage if record is not None else None)
        prompt_tokens = usage.prompt_tokens if usage is not None else 0
        completion_tokens = usage.completion_tokens if usage is not None else 0
        cost = estimate_cost_usd(fingerprint.model, usage) if usage is not None else 0.0

        # A step that committed is named by its transform; one that did not has
        # no transform to name, and saying so beats inventing an id.
        committed = step.next_state is not None
        entries.append(
            CostLedgerEntry(
                transform_id=record.id if (record is not None and committed) else None,
                operator=(record.operator if record is not None else step.operator),
                provider=fingerprint.provider,
                model=fingerprint.model,
                attempts=step.attempts,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=cost,
                committed=committed,
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
