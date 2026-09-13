"""The live five-stage analysis pipeline: `spc-demo analyze` over ANY document.

`run_analysis` runs extract -> plan -> critique -> retrieve -> verify ->
calibrate against a real `LLMProvider` (plus a corroborate stage when a run has
more than one source), each a validated, committed patch
(`Runtime.step_llm` / `Runtime.step`), then projects the Reasoning Receipt and
Decision Memo from the committed state. It never re-prompts a model once the
pipeline has run — both documents are faithful projections of state.

Factored out of `cli.analyze` so the pipeline can be driven by an injected
provider in tests (`tests/test_analyze_pipeline.py`) without going through the
CLI or a network call — the CLI command is a thin wrapper that builds the
provider, calls this, and renders the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .cost_ledger import CostLedger, build_cost_ledger, write_cost_ledger
from .memo import write_memo
from .operators import (
    CalibrationOperator,
    LLMContradictionOperator,
    LLMCorroborationOperator,
    LLMExtractOperator,
    LLMPlannerOperator,
    LLMReviewCriticOperator,
    Operator,
    RetrieverOperator,
)
from .providers import LLMProvider
from .receipt import ReceiptArtifacts, write_run_artifacts
from .runtime import Clock, RunResult, Runtime, WallClock, bootstrap_state
from .source_types import DEFAULT_SOURCE_TYPE, SourceType
from .store import RunPaths

DEFAULT_QUESTION = "What does this document establish?"


@dataclass(frozen=True)
class SourceDocument:
    """A further document to extract into the same semantic state.

    One run, one state, several sources. Each extraction mints ids in its own
    namespace (`d2_claim_001`) because `claim_001` is already taken and L2
    refuses the collision by design. Everything downstream is unchanged: the
    planner, critic, retriever, verifier and calibrator read whatever claims
    committed state holds, so they compare across sources for free.

    The point of the exercise is that `source_type` is **per document**. A
    press release and a regulator's determination on the same transaction do
    not carry the same weight (T14), and until now a run could declare only one
    of them.
    """

    text: str
    source_type: SourceType | str = DEFAULT_SOURCE_TYPE


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
    source_type: SourceType | str = DEFAULT_SOURCE_TYPE,
    extra_documents: Sequence[SourceDocument] = (),
) -> list[Operator]:
    """The six-stage operator list, plus corroboration when sources differ.

    extract -> plan -> critique -> retrieve -> verify -> calibrate, with a
    corroborate stage between extract and plan **when there is more than one
    source**. Retrieve and calibrate are deterministic (`RetrieverOperator`,
    `CalibrationOperator`, no model call); the rest are LLM-backed and share
    `provider`.

    Calibrate runs **last** on purpose: it holds each recommendation to the
    confidence its support can carry, and the critic has by then already moved
    the claims underneath it (T15).

    `source_type` says what kind of document this is. It sets the reliability
    of every span the extraction records, and so how hard the Retriever looks
    for corroboration downstream — see `source_types`.

    `extra_documents` adds one extraction stage per further source, each with
    its own declared `source_type` and its own id namespace, before the shared
    stages run over the combined state.
    """
    operators: list[Operator] = [
        LLMExtractOperator(
            provider, input_text=document, clock=clock, source_type=source_type
        )
    ]
    for i, extra in enumerate(extra_documents, start=2):
        operators.append(
            LLMExtractOperator(
                provider,
                input_text=extra.text,
                clock=clock,
                source_type=extra.source_type,
                # Deliberately outside the fixed downstream numbering
                # (`patch_002` is the planner), so a second source cannot
                # shadow a later stage's patch id.
                patch_id=f"patch_extract_{i:03d}",
                transform_id=f"transform_extract_{i:03d}",
                source_id=f"doc_{i:03d}",
                id_prefix=f"d{i}_",
            )
        )
    if not extract_only:
        if extra_documents:
            # Before the planner on purpose: corroboration settles what the
            # sources jointly establish, and the planner should reason from
            # that picture rather than from one document's account of it (T19).
            # Only with more than one source — with a single document there is
            # nothing to corroborate across, and adding a stage to answer a
            # question that has no answer costs a real call and would make
            # every existing cassette stale for nothing.
            operators.append(LLMCorroborationOperator(provider, clock=clock))
        operators.append(LLMPlannerOperator(provider, clock=clock))
        operators.append(LLMReviewCriticOperator(provider, clock=clock))
        operators.append(RetrieverOperator(clock=clock))
        operators.append(LLMContradictionOperator(provider, clock=clock))
        operators.append(CalibrationOperator(clock=clock))
    return operators


def run_analysis(
    provider: LLMProvider,
    document: str,
    paths: RunPaths,
    *,
    clock: Clock | None = None,
    question: str = DEFAULT_QUESTION,
    extract_only: bool = False,
    source_type: SourceType | str = DEFAULT_SOURCE_TYPE,
    extra_documents: Sequence[SourceDocument] = (),
) -> AnalysisResult:
    """Run the pipeline and project its Reasoning Receipt + Decision Memo."""
    clock = clock or WallClock()
    operators = build_analysis_operators(
        provider,
        document,
        clock=clock,
        extract_only=extract_only,
        source_type=source_type,
        extra_documents=extra_documents,
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
    "SourceDocument",
    "build_analysis_operators",
    "run_analysis",
]
