"""The North Star demonstration (PILOT_SPEC.md §8): one orchestrated story.

`run_full_demo` runs the whole pilot end-to-end against the demo document —
the SPC engine (extract -> plan -> critique, each patch validated and
committed), the JSON-handoff baseline, the §20 evaluation, and the Reasoning
Receipt — and returns everything needed to *narrate* it. The CLI `spc-demo
demo` command renders that to the terminal; `render_demo_markdown` renders the
same data to a shareable `DEMO.md`.

This is a thin orchestration layer over machinery that already exists and is
tested (Phases 3-8). Its job is to make the value visible and to prove, in one
command, that the pieces fit together. The deterministic path is byte-for-byte
reproducible; `--live-critic` swaps in a real OpenRouter model on the same loop.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from .baseline import BaselineResult, run_baseline
from .evaluation import EvaluationReport, evaluate, write_report
from .operators import (
    CriticOperator,
    ExtractOperator,
    LLMCriticOperator,
    Operator,
    PlannerOperator,
)
from .providers import OpenRouterConfigError, OpenRouterProvider
from .receipt import write_run_artifacts
from .runtime import Clock, FixedClock, Runtime, WallClock, bootstrap_state
from .store import RunPaths
from .tokens import estimate_tokens

# A fixed timestamp keeps the deterministic demo (and DEMO.md) reproducible.
FIXED_GENERATED_AT = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=dt.UTC)

DEFAULT_QUESTION = "Should the company adopt an AI coding assistant?"


@dataclass(frozen=True)
class StepNarration:
    """One narrated SPC operator step."""

    ordinal: int
    operator: str
    decision: str
    state_version: int | str
    added: list[str]
    confidence_changes: list[tuple[str, float, float]]
    issues: int
    attempts: int


@dataclass(frozen=True)
class DemoResult:
    paths: RunPaths
    document: str
    question: str
    steps: list[StepNarration]
    baseline: BaselineResult
    evaluation: EvaluationReport | None
    report_md_path: str
    metrics_json_path: str
    receipt_path: Path
    live: bool
    model: str | None = None
    warnings: list[str] = field(default_factory=list)


class LiveCriticUnavailable(RuntimeError):
    """Raised when --live-critic is requested but no provider can be built."""


def _build_steps(result) -> list[StepNarration]:
    steps: list[StepNarration] = []
    for outcome in result.steps:
        if outcome.patch is not None:
            rec = outcome.patch.transform_record
            operator = rec.operator
            added = list(rec.write_set)
            changes = [
                (cc.object_id, cc.from_value, cc.to_value)
                for cc in rec.confidence_changes
            ]
        else:
            operator = "(no patch)"
            added = []
            changes = []
        steps.append(
            StepNarration(
                ordinal=outcome.ordinal,
                operator=operator,
                decision=outcome.decision.value,
                state_version=(
                    outcome.next_state.state_version if outcome.next_state else "-"
                ),
                added=added,
                confidence_changes=changes,
                issues=len(outcome.report.issues),
                attempts=getattr(outcome, "attempts", 1),
            )
        )
    return steps


def run_full_demo(
    *,
    runs_dir: Path,
    run_id: str,
    document: str,
    question: str = DEFAULT_QUESTION,
    live_critic: bool = False,
    model: str | None = None,
    generated_at: dt.datetime | None = None,
) -> DemoResult:
    """Run the full §8 demo and return everything needed to narrate it.

    Deterministic by default (fixed clock, reproducible artifacts). With
    `live_critic=True` the third operator is an OpenRouter LLM critic and the
    run becomes non-deterministic; a missing key raises `LiveCriticUnavailable`.
    """
    paths = RunPaths(root=runs_dir, run_id=run_id)
    warnings: list[str] = []

    clock: Clock
    if live_critic:
        clock = WallClock()
        generated_at = generated_at or clock.now()
    else:
        start = FIXED_GENERATED_AT
        clock = FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(48)])
        generated_at = generated_at or start

    initial = bootstrap_state(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="AI Coding Assistant Adoption Analysis",
        now=clock.now(),
    )

    critic: Operator
    if live_critic:
        try:
            provider = OpenRouterProvider(model=model)
        except OpenRouterConfigError as exc:
            raise LiveCriticUnavailable(str(exc)) from exc
        critic = LLMCriticOperator(provider)
        model = provider.model
    else:
        critic = CriticOperator(clock=clock)

    runtime = Runtime(paths=paths, clock=clock)
    result = runtime.run(
        initial_state=initial,
        operators=[
            ExtractOperator(input_text=document, clock=clock),
            PlannerOperator(clock=clock),
            critic,
        ],
        input_text=document,
    )
    steps = _build_steps(result)

    history = [
        result.initial_state,
        *(s.next_state for s in result.steps if s.next_state),
    ]
    artifacts = write_run_artifacts(
        paths, history, generated_at=generated_at, question=question
    )

    baseline = run_baseline(document)
    _write_baseline_artifacts(paths, baseline)

    if len(history) < 4:
        # A live critic can fail to commit; fall back to a clear warning rather
        # than crashing the demo. Evaluation needs the full v0..v3 history.
        warnings.append(
            f"SPC produced only {len(history)} state version(s); the live critic "
            "may not have committed. Showing what was built; metrics need v0..v3."
        )
        evaluation = None  # type: ignore[assignment]
        report_md, metrics_json = "", ""
    else:
        evaluation = evaluate(
            run_id=run_id,
            history=history,
            paths=paths,
            baseline=baseline,
            generated_at=generated_at,
        )
        report_md, metrics_json = write_report(paths, evaluation)

    return DemoResult(
        paths=paths,
        document=document,
        question=question,
        steps=steps,
        baseline=baseline,
        evaluation=evaluation,
        report_md_path=report_md,
        metrics_json_path=metrics_json,
        receipt_path=artifacts.receipt_path,
        live=live_critic,
        model=model,
        warnings=warnings,
    )


def _write_baseline_artifacts(paths: RunPaths, baseline: BaselineResult) -> None:
    import json

    paths.baseline_dir.mkdir(parents=True, exist_ok=True)
    for stage in baseline.stages:
        paths.baseline_file(f"{stage.name}.json").write_text(
            json.dumps(stage.output, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    paths.baseline_file("transcript.md").write_text(
        baseline.transcript_markdown(), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Shareable Markdown render (DEMO.md)
# ---------------------------------------------------------------------------


def _step_line(s: StepNarration) -> str:
    bits = []
    if s.added:
        bits.append("added " + ", ".join(s.added))
    for oid, frm, to in s.confidence_changes:
        bits.append(f"{oid} confidence {frm:.2f}->{to:.2f}")
    detail = "; ".join(bits) if bits else "no objects written"
    attempts = f" (x{s.attempts})" if s.attempts > 1 else ""
    return (
        f"| {s.ordinal} | `{s.operator}` | {s.decision}{attempts} | "
        f"v{s.state_version} | {detail} |"
    )


def render_demo_markdown(demo: DemoResult) -> str:
    """Render the demo as a shareable walkthrough document."""
    ev = demo.evaluation
    doc_tokens = estimate_tokens(demo.document)
    lines: list[str] = [
        "# SPC Demonstration — Shared Semantic State in action",
        "",
        "> Generated by `spc-demo demo`"
        + (f" (live critic: `{demo.model}`)" if demo.live else " (deterministic)")
        + ". Re-run it yourself with the command at the bottom.",
        "",
        "The Semantic Processing Computer (SPC) coordinates AI stages through a "
        "**persistent, versioned semantic state** — typed claims, evidence, "
        "assumptions, and contradictions — that every operator changes only by "
        "proposing a validated `SemanticPatch`. This walkthrough runs the §8 "
        "North Star Demo and contrasts it with a competent JSON-handoff chain.",
        "",
        "## 1. The question and the document",
        "",
        f"**Decision:** {demo.question}",
        "",
        "```text",
        demo.document.strip(),
        "```",
        "",
        "## 2. SPC builds semantic state, one governed patch at a time",
        "",
        "Each operator reads a perspective-specific projection, proposes a "
        "patch, and the runtime validates -> routes -> commits it into a new "
        "state version. No operator mutates state directly.",
        "",
        "| step | operator | decision | state | what it wrote |",
        "|---|---|---|---|---|",
    ]
    lines.extend(_step_line(s) for s in demo.steps)
    final_v = demo.steps[-1].state_version if demo.steps else "?"
    lines += [
        "",
        f"The result is `SemanticState v{final_v}` — a queryable object graph, "
        "not a paragraph. Every claim carries its evidence, every confidence "
        "change carries its reason, and the whole history is in the audit log.",
        "",
        "## 3. The baseline: a competent JSON handoff that keeps no state",
        "",
        "The same document through `summary -> critique -> final memo`. It "
        "produces a reasonable memo, but each stage re-reads the full document "
        f"(~{doc_tokens} tokens x {demo.baseline.full_document_reingestions} = "
        f"~{doc_tokens * demo.baseline.full_document_reingestions} source tokens "
        "reprocessed) and nothing durable survives the handoffs: no ids, no "
        "provenance, no assumptions, no transform history.",
        "",
        "```json",
        '"recommendation": ' + _short(demo.baseline.memo.get("recommendation", "")),
        "```",
        "",
    ]

    if ev is not None:
        lines += _markdown_payoff(demo, ev)
    else:
        lines += [
            "## 4. (Live run note)",
            "",
            *[f"> {w}" for w in demo.warnings],
            "",
        ]

    cmd = "spc-demo demo" + (" --live-critic" if demo.live else "")
    lines += [
        "## Run it yourself",
        "",
        "```bash",
        "pip install -e \".[dev]\"",
        cmd,
        "```",
        "",
        "Artifacts land under "
        f"`{demo.paths.run_dir.as_posix()}/` — state snapshots, patches, "
        "validation reports, diffs, the audit log, the Reasoning Receipt, the "
        "baseline transcript, and the full pilot report.",
        "",
    ]
    return "\n".join(lines)


def _markdown_payoff(demo: DemoResult, ev: EvaluationReport) -> list[str]:
    by_key = {m.key: m for m in ev.metrics}
    answers: dict[str, str] = by_key["20.7"].spc.get("answers", {})  # type: ignore[assignment]
    dm = ev.demo_moment
    lines = [
        "## 4. The payoff: follow-ups answered from state, not re-reasoned",
        "",
        "After both systems answer, we ask the spec §8.4 follow-ups. The SPC "
        f"engine answers all {ev.followups_total} **directly from committed "
        "state** — no model call, no re-reading the document:",
        "",
    ]
    for q, a in answers.items():
        lines.append(f"- **{q}**")
        lines.append(f"  - {a}")
    lines += [
        "",
        "The baseline cannot: half of these have no durable object to read at "
        "all (no ids, no versions, no provenance), and the rest require "
        "re-running the chain.",
        "",
        "### The demo moment (spec §8.5)",
        "",
        f"**{dm.question}**",
        "",
        f"- _Baseline:_ {dm.baseline_response}",
        f"- _SPC:_ {dm.spc_response}",
        "",
        "## 5. Scorecard (spec §20)",
        "",
        "| Metric | SPC vs. baseline |",
        "|---|---|",
    ]
    for m in ev.metrics:
        lines.append(f"| §{m.key} {m.name} | {m.headline} |")
    lines += [
        "",
        f"Full report: `{Path(demo.report_md_path).as_posix()}`.",
        "",
    ]
    return lines


def _short(text: str, limit: int = 200) -> str:
    text = text.strip()
    return f'"{text}"' if len(text) <= limit else f'"{text[: limit - 1]}…"'


def write_demo_markdown(demo: DemoResult, *, repo_root: Path | None = None) -> Path:
    """Write `DEMO.md` to the run tree (and repo root for the deterministic run)."""
    md = render_demo_markdown(demo)
    run_copy = demo.paths.run_dir / "DEMO.md"
    run_copy.write_text(md, encoding="utf-8")
    if repo_root is not None:
        (repo_root / "DEMO.md").write_text(md, encoding="utf-8")
    return run_copy


__all__ = [
    "DEFAULT_QUESTION",
    "DemoResult",
    "LiveCriticUnavailable",
    "StepNarration",
    "render_demo_markdown",
    "run_full_demo",
    "write_demo_markdown",
]
