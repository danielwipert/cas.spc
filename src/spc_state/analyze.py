"""The live five-stage analysis pipeline: `spc-demo analyze` over ANY document.

`run_analysis` runs extract -> plan -> critique -> retrieve -> verify against
a real `LLMProvider`, each stage a validated, committed patch
(`Runtime.step_llm` / `Runtime.step`), then projects the Reasoning Receipt and
Decision Memo from the committed state. It never re-prompts a model once the
pipeline has run — both documents are faithful projections of state.

Factored out of `cli.analyze` so the pipeline can be driven by an injected
provider in tests (`tests/test_analyze_pipeline.py`) without going through the
CLI or a network call — the CLI command is a thin wrapper that builds the
provider, calls this, and renders the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cost_ledger import CostLedger, build_cost_ledger, write_cost_ledger
from .memo import write_memo
from .operators import (
    LLMContradictionOperator,
    LLMExtractOperator,
    LLMPlannerOperator,
    LLMReviewCriticOperator,
    Operator,
    RetrieverOperator,
)
from .providers import LLMProvider
from .receipt import ReceiptArtifacts, write_run_artifacts
from .runtime import Clock, RunResult, Runtime, WallClock, bootstrap_state
from .store import RunPaths

DEFAULT_QUESTION = "What does this document establish?"


@dataclass(frozen=True)
class AnalysisResult:
    """Everything the pipeline produced: the run, and its projected artifacts.

    `artifacts` and `memo_path` are `None` when nothing committed — the
    extractor produced no valid patch, so there is no committed state to
    project a receipt or memo from. `cost_ledger` is `None` on the same
    condition, or if somehow no step recorded a model fingerprint.
    """

    paths: RunPaths
    run: RunResult
    artifacts: ReceiptArtifacts | None
    memo_path: Path | None
    cost_ledger: CostLedger | None


def build_analysis_operators(
    provider: LLMProvider,
    document: str,
    *,
    clock: Clock,
    extract_only: bool = False,
) -> list[Operator]:
    """The five-stage operator list (four when `extract_only`).

    extract -> plan -> critique -> retrieve -> verify. Retrieve is
    deterministic (`RetrieverOperator`, no model call); the rest are
    LLM-backed and share `provider`.
    """
    operators: list[Operator] = [
        LLMExtractOperator(provider, input_text=document, clock=clock)
    ]
    if not extract_only:
        operators.append(LLMPlannerOperator(provider, clock=clock))
        operators.append(LLMReviewCriticOperator(provider, clock=clock))
        operators.append(RetrieverOperator(clock=clock))
        operators.append(LLMContradictionOperator(provider, clock=clock))
    return operators


def run_analysis(
    provider: LLMProvider,
    document: str,
    paths: RunPaths,
    *,
    clock: Clock | None = None,
    question: str = DEFAULT_QUESTION,
    extract_only: bool = False,
) -> AnalysisResult:
    """Run the pipeline and project its Reasoning Receipt + Decision Memo."""
    clock = clock or WallClock()
    operators = build_analysis_operators(
        provider, document, clock=clock, extract_only=extract_only
    )

    runtime = Runtime(paths=paths, clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_001",
            project_id="spc_analysis_001",
            name="Document analysis",
            now=clock.now(),
        ),
        operators=operators,
        input_text=document,
    )

    # Always build the ledger — every stage here is LLM-backed except the
    # retriever, and even a run that committed nothing may have spent real
    # tokens on rejected/retried attempts (spec T5, AGENTS.md §III).
    ledger = build_cost_ledger(paths.run_id, result.steps)
    cost_ledger = ledger if ledger.entries else None
    if cost_ledger is not None:
        write_cost_ledger(paths, cost_ledger)

    if result.final_state.state_version == 0:
        return AnalysisResult(
            paths=paths, run=result, artifacts=None, memo_path=None, cost_ledger=cost_ledger
        )

    states = [result.initial_state, *(s.next_state for s in result.steps if s.next_state)]
    artifacts = write_run_artifacts(
        paths, states, generated_at=clock.now(), question=question
    )
    memo_path = write_memo(paths, result.final_state, question=question)
    return AnalysisResult(
        paths=paths,
        run=result,
        artifacts=artifacts,
        memo_path=memo_path,
        cost_ledger=cost_ledger,
    )


__all__ = [
    "DEFAULT_QUESTION",
    "AnalysisResult",
    "build_analysis_operators",
    "run_analysis",
]
