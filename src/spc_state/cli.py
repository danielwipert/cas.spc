"""Command-line interface for the SPC pilot demo.

Phase 3 wires `spc-demo run` to the runtime: it bootstraps an empty
`SemanticState v0`, applies Extract → Planner → Critic, and writes the
canonical `runs/<run_id>/` artifact tree.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from . import __version__
from .analyze import DEFAULT_QUESTION, SourceDocument, run_analysis
from .baseline import run_baseline
from .config import load_dotenv
from .cost_ledger import build_cost_ledger, write_cost_ledger
from .demo import (
    LiveCriticUnavailable,
    run_full_demo,
    write_demo_markdown,
)
from .evaluation import evaluate, write_report
from .memo import write_memo
from .models import EpistemicStatus, SemanticState
from .operators import CriticOperator, ExtractOperator, LLMCriticOperator, Operator, PlannerOperator
from .providers import OpenRouterConfigError, OpenRouterProvider
from .receipt import FollowUps, write_run_artifacts
from .runtime import Clock, FixedClock, Runtime, WallClock, bootstrap_state
from .source_types import DEFAULT_SOURCE_TYPE, SourceType, reliability_for
from .store import RunPaths, StateStore

app = typer.Typer(
    name="spc-demo",
    help="SPC Shared Semantic State Engine — pilot demo runner.",
    add_completion=False,
    no_args_is_help=True,
)

_console = Console()


@app.callback()
def _main() -> None:
    """Load a local `.env` (if any) before any command runs.

    Lets a key dropped in `.env` (e.g. OPENROUTER_API_KEY) reach the live
    operators without exporting it into the shell. Real env vars take
    precedence; missing file is a no-op.
    """
    load_dotenv()


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(f"spc-state {__version__}")


def _lineage_arg(value: str, known: set[str]) -> str | None:
    """One `--also-derives-from` value: a known source id, or nothing.

    Validated here rather than swallowed, because a typo'd parent silently buys
    back the independence the flag was passed to deny — the failure mode would
    be a `verified` claim that nobody checked.
    """
    cleaned = value.strip()
    if cleaned.lower() in ("", "none", "-"):
        return None
    if cleaned not in known:
        raise typer.BadParameter(
            f"--also-derives-from {value!r} is not a source in this run. "
            f"Known sources: {', '.join(sorted(known))} (doc_001 is --input, "
            "extras follow in the order given), or 'none'."
        )
    return cleaned


@app.command()
def analyze(
    input: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        readable=True,
        resolve_path=True,
        help="Any document to analyze into semantic state.",
    ),
    run_id: str = typer.Option("analysis_001", "--run-id", help="Run id."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    question: str = typer.Option(
        DEFAULT_QUESTION,
        "--question",
        "-q",
        help="Decision/analysis question recorded in the receipt.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="OpenRouter model slug (defaults to a value-based model; also "
        "reads SPC_OPENROUTER_MODEL).",
    ),
    source_type: SourceType = typer.Option(
        DEFAULT_SOURCE_TYPE.value,
        "--source-type",
        case_sensitive=False,
        help="What kind of document this is. Sets the reliability of every "
        "extracted span, and so how hard the pipeline looks for corroboration. "
        "Undeclared means medium — never high.",
    ),
    also_input: list[Path] = typer.Option(
        [],
        "--also-input",
        exists=True,
        readable=True,
        resolve_path=True,
        help="A further document to extract into the SAME semantic state. "
        "Repeatable; pair each with a --also-source-type in the same order.",
    ),
    also_source_type: list[SourceType] = typer.Option(
        [],
        "--also-source-type",
        case_sensitive=False,
        help="Source type for each --also-input, in the same order.",
    ),
    also_derives_from: list[str] = typer.Option(
        [],
        "--also-derives-from",
        help="For an --also-input written off another document, the source id "
        "it came from (doc_001 is --input; extras are doc_002, doc_003, ... in "
        "order). Two sources where one derives from the other never corroborate "
        "each other. Repeatable; pass 'none' to skip one. Omit entirely to "
        "declare every document independent.",
    ),
    extract_only: bool = typer.Option(
        False,
        "--extract-only",
        help="Stop after extraction (skip the remaining four stages).",
    ),
) -> None:
    """Analyze a real document into provenance-tracked semantic state + memo.

    Runs the full live pipeline over ANY document (not just the demo), six
    stages each emitting a validated patch:

      extract   -> claims committed with their supporting quote
      plan      -> a recommendation plus open questions
      critique  -> weak confidence adjusted
      retrieve  -> evidence gaps opened as questions (deterministic, no model)
      verify    -> conflicting claim pairs committed as unresolved contradictions
      calibrate -> the recommendation capped to what its support can carry
                   (deterministic, no model)

    Pass `--source-type` to say what kind of document this is: a press release
    and a regulatory filing are not equally trustworthy, and the pipeline acts
    on the difference. Left undeclared, spans are weighed as medium.

    Pass `--also-input` (with a matching `--also-source-type`) to extract
    further documents into the **same** state, each weighed by its own source
    type. The later stages then read every source at once, so the verifier can
    find a conflict between two documents rather than only within one.

    A Decision Memo and a Reasoning Receipt are then projected from the
    committed state — neither re-prompts the model. Needs OPENROUTER_API_KEY;
    the run is non-deterministic (a live model).
    """
    if len(also_input) != len(also_source_type):
        raise typer.BadParameter(
            f"{len(also_input)} --also-input but {len(also_source_type)} "
            "--also-source-type: give one source type per extra document, in "
            "the same order. A document's weight is not a detail to guess at."
        )
    if also_derives_from and len(also_derives_from) != len(also_input):
        raise typer.BadParameter(
            f"{len(also_input)} --also-input but {len(also_derives_from)} "
            "--also-derives-from: give one per extra document, in the same "
            "order, using 'none' for a document that stands on its own. Omit "
            "the option entirely to declare every document independent."
        )
    known_sources = {f"doc_{i:03d}" for i in range(1, len(also_input) + 2)}
    lineage = [_lineage_arg(v, known_sources) for v in also_derives_from] or [
        None
    ] * len(also_input)

    document = input.read_text(encoding="utf-8")
    extras = [
        SourceDocument(
            text=path.read_text(encoding="utf-8"), source_type=st, derives_from=parent
        )
        for path, st, parent in zip(
            also_input, also_source_type, lineage, strict=True
        )
    ]
    paths = RunPaths(root=runs_dir, run_id=run_id)
    clock = WallClock()

    try:
        provider = OpenRouterProvider(model=model)
    except OpenRouterConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    stages = (
        "extract"
        if extract_only
        else "extract -> plan -> critique -> retrieve -> verify -> calibrate"
    )
    _console.print(
        f"[yellow]live analysis via OpenRouter:[/yellow] {provider.model} "
        f"[dim]({stages})[/dim]"
    )
    _console.print(
        f"[yellow]source type:[/yellow] {source_type.value} "
        f"[dim](evidence reliability: {reliability_for(source_type).value})[/dim]"
    )
    for i, (path, st, parent) in enumerate(
        zip(also_input, also_source_type, lineage, strict=True), start=2
    ):
        origin = f", derives from {parent}" if parent else ""
        _console.print(
            f"[yellow]also source {i}:[/yellow] {st.value} "
            f"[dim]({reliability_for(st).value}{origin}) — {path.name}[/dim]"
        )

    analysis = run_analysis(
        provider,
        document,
        paths,
        clock=clock,
        question=question,
        extract_only=extract_only,
        source_type=source_type,
        extra_documents=extras,
    )

    _render_summary(analysis.run)
    if analysis.artifacts is None or analysis.memo_path is None:
        _console.print("[red]Nothing committed — the extractor produced no valid patch.[/red]")
        raise typer.Exit(code=1)

    final = analysis.run.final_state
    _console.print(
        f"[green]state v{final.state_version}:[/green] "
        f"{len(final.claims)} claims, {len(final.evidence)} evidence, "
        f"{len(final.assumptions)} assumptions, {len(final.hypotheses)} hypotheses, "
        f"{len(final.questions)} questions"
    )
    if final.hypotheses:
        lead = max(final.hypotheses.values(), key=lambda h: h.confidence)
        _console.print(f"[green]recommendation:[/green] {_ascii(lead.text)}")
    _console.print(f"[green]decision memo:[/green] [dim]{analysis.memo_path}[/dim]")
    _console.print(
        f"[green]reasoning receipt:[/green] [dim]{analysis.artifacts.receipt_path}[/dim]"
    )


@app.command()
def memo(
    run_id: str = typer.Option("analysis_001", "--run-id", help="Run to render."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    question: str = typer.Option(
        "Decision analysis",
        "--question",
        "-q",
        help="Heading/decision question for the memo.",
    ),
) -> None:
    """Render a citation-backed Decision Memo from a run's committed state.

    Reads the final `SemanticState` and projects `runs/<id>/memo.md` — a
    stakeholder document where every finding cites its source span. Pure read,
    no model call, so it can be regenerated any time.
    """
    paths = RunPaths(root=runs_dir, run_id=run_id)
    history = _load_history(paths)
    final = max(history, key=lambda s: s.state_version)
    memo_path = write_memo(paths, final, question=question)
    _console.print(f"[green]decision memo:[/green] [dim]{memo_path}[/dim]")


@app.command()
def run(
    input: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        readable=True,
        resolve_path=True,
        help="Path to the input document.",
    ),
    run_id: str = typer.Option("demo_001", "--run-id", help="Identifier for this run."),
    runs_dir: Path = typer.Option(
        Path("runs"),
        "--runs-dir",
        help="Root directory under which run trees are written.",
    ),
    question: str = typer.Option(
        "Should the company adopt an AI coding assistant?",
        "--question",
        "-q",
        help="Decision question recorded in the Reasoning Receipt summary.",
    ),
    deterministic: bool = typer.Option(
        True,
        "--deterministic/--wall-clock",
        help="Use a fixed clock for byte-reproducible runs (default) or the wall clock.",
    ),
    live_critic: bool = typer.Option(
        False,
        "--live-critic",
        help="Replace the deterministic critic with a live OpenRouter LLM critic "
        "(needs OPENROUTER_API_KEY; run becomes non-deterministic).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="OpenRouter model slug for --live-critic (e.g. deepseek/deepseek-chat). "
        "Defaults to a value-based model; also reads SPC_OPENROUTER_MODEL.",
    ),
) -> None:
    """Run the demo pipeline against an input document.

    Writes the canonical artifact tree under `<runs-dir>/<run-id>/`:
    state snapshots, patches, validation reports, audit log, plus the input
    document copied verbatim. With --live-critic the third step is an
    OpenRouter-backed LLM critic instead of the deterministic one.
    """
    input_text = input.read_text(encoding="utf-8")
    paths = RunPaths(root=runs_dir, run_id=run_id)

    # A live model is non-deterministic, so a fixed clock would be misleading.
    clock: Clock
    if deterministic and not live_critic:
        # 48 evenly-spaced timestamps cover every clock.now() call in the
        # three-operator demo run. WallClock is used otherwise.
        start = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=dt.UTC)
        clock = FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(48)])
    else:
        clock = WallClock()

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
            raise typer.BadParameter(str(exc)) from exc
        critic = LLMCriticOperator(provider)
        _console.print(f"[yellow]live critic via OpenRouter:[/yellow] {provider.model}")
    else:
        critic = CriticOperator(clock=clock)

    runtime = Runtime(paths=paths, clock=clock)
    operators = [
        ExtractOperator(input_text=input_text, clock=clock),
        PlannerOperator(clock=clock),
        critic,
    ]
    result = runtime.run(
        initial_state=initial,
        operators=operators,
        input_text=input_text,
    )

    # Phase 4: project the Reasoning Receipt and per-version diffs from the
    # committed state history and write them into the run tree.
    states = [result.initial_state, *(s.next_state for s in result.steps if s.next_state)]
    artifacts = write_run_artifacts(
        paths,
        states,
        generated_at=clock.now(),
        question=question,
    )

    _render_summary(result)
    _console.print(
        f"[green]reasoning receipt:[/green] [dim]{artifacts.receipt_path}[/dim]"
    )

    if live_critic:
        # Only a step outside the deterministic path ever spends real tokens,
        # so only --live-critic gets a ledger file — no new artifact appears
        # in the byte-stable default `spc-demo run`.
        ledger = build_cost_ledger(run_id, result.steps)
        if ledger.entries:
            ledger_path = write_cost_ledger(paths, ledger)
            _console.print(
                f"[green]cost ledger:[/green] [dim]{ledger_path}[/dim] "
                f"(~{ledger.total_tokens} tokens, "
                f"${ledger.total_estimated_cost_usd:.6f} est.)"
            )


_ASCII_MAP = {
    "→": "->",  # right arrow
    "≈": "~",  # almost-equal
    "×": "x",  # multiplication sign
    "—": "-",  # em dash
    "–": "-",  # en dash
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "…": "...",
    "§": "",  # section sign — drop cleanly for the terminal
}


def _ascii(text: str) -> str:
    """Make a string safe to print on a legacy (cp1252) Windows console.

    The Markdown artifacts keep the nicer glyphs; only terminal output is
    down-converted so a narrated run never crashes on an un-encodable char.
    """
    for src, dst in _ASCII_MAP.items():
        text = text.replace(src, dst)
    return text.encode("ascii", "ignore").decode("ascii")


@app.command()
def demo(
    run_id: str = typer.Option("demo", "--run-id", help="Run id for the demo tree."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    input: Path = typer.Option(
        Path("examples/ai_coding_assistant.txt"),
        "--input",
        "-i",
        exists=True,
        readable=True,
        resolve_path=True,
        help="Input document (defaults to the §8 demo scenario).",
    ),
    live_critic: bool = typer.Option(
        False,
        "--live-critic",
        help="Use a live OpenRouter LLM critic instead of the deterministic one "
        "(needs OPENROUTER_API_KEY; the run is no longer reproducible).",
    ),
    model: str | None = typer.Option(
        None, "--model", help="OpenRouter model slug for --live-critic."
    ),
) -> None:
    """Run the full §8 North Star Demo as a narrated, end-to-end story.

    Builds semantic state through three governed patches, runs the JSON-handoff
    baseline over the same document, answers the §8.4 follow-ups from state, and
    writes a shareable `DEMO.md` plus the full pilot report. Deterministic by
    default; `--live-critic` swaps in a real model on the same loop.
    """
    document = input.read_text(encoding="utf-8")
    try:
        result = run_full_demo(
            runs_dir=runs_dir,
            run_id=run_id,
            document=document,
            live_critic=live_critic,
            model=model,
        )
    except LiveCriticUnavailable as exc:
        raise typer.BadParameter(str(exc)) from exc

    _narrate_demo(result)

    # The deterministic run is reproducible, so its DEMO.md is safe to commit at
    # the repo root; a live run only writes into its own run tree.
    repo_root = Path.cwd() if not result.live else None
    demo_md = write_demo_markdown(result, repo_root=repo_root)
    _console.print()
    _console.print(f"[green]shareable walkthrough:[/green] [dim]{demo_md}[/dim]")
    if repo_root is not None:
        _console.print(f"[green]                     :[/green] [dim]{repo_root / 'DEMO.md'}[/dim]")
    if result.report_md_path:
        _console.print(f"[green]pilot report:[/green] [dim]{result.report_md_path}[/dim]")
    _console.print(f"[green]reasoning receipt:[/green] [dim]{result.receipt_path}[/dim]")
    if result.cost_ledger_path is not None:
        _console.print(f"[green]cost ledger:[/green] [dim]{result.cost_ledger_path}[/dim]")


def _narrate_demo(result) -> None:
    mode = f"live critic: {result.model}" if result.live else "deterministic"
    _console.print()
    _console.print(f"[bold]SPC North Star Demo[/bold] [dim]({_ascii(mode)})[/dim]")
    _console.print(
        "Coordinating AI stages through persistent, versioned semantic state "
        "instead of text/JSON handoffs.\n"
    )

    _console.print(f"[bold]1. Decision[/bold]: {_ascii(result.question)}")
    _console.print("[bold]   Document[/bold]:")
    for line in result.document.strip().splitlines():
        _console.print(f"   [dim]{_ascii(line)}[/dim]")
    _console.print()

    _console.print("[bold]2. SPC builds semantic state (one governed patch per step)[/bold]")
    steps_table = Table(box=box.ASCII, show_lines=False)
    steps_table.add_column("Step")
    steps_table.add_column("Operator")
    steps_table.add_column("Decision")
    steps_table.add_column("State")
    steps_table.add_column("What it wrote")
    for s in result.steps:
        bits = []
        if s.added:
            bits.append("added " + ", ".join(s.added))
        for oid, frm, to in s.confidence_changes:
            bits.append(f"{oid} conf {frm:.2f}->{to:.2f}")
        decision = s.decision + (f" (x{s.attempts})" if s.attempts > 1 else "")
        steps_table.add_row(
            str(s.ordinal),
            _ascii(s.operator),
            decision,
            f"v{s.state_version}",
            _ascii("; ".join(bits) if bits else "-"),
        )
    _console.print(steps_table)

    base = result.baseline
    _console.print(
        f"\n[bold]3. Baseline (JSON handoff)[/bold]: summary -> critique -> memo "
        f"[dim](document re-read {base.full_document_reingestions}x; "
        f"no durable state)[/dim]"
    )

    ev = result.evaluation
    if ev is None:
        for w in result.warnings:
            _console.print(f"[yellow]note:[/yellow] {_ascii(w)}")
        return

    _console.print(
        f"\n[bold]4. Follow-ups answered from state[/bold] "
        f"[dim]({ev.followups_spc_answered}/{ev.followups_total}, no re-reading)[/dim]"
    )
    answers = next(m for m in ev.metrics if m.key == "20.7").spc.get("answers", {})
    fu_table = Table(box=box.ASCII, show_lines=True)
    fu_table.add_column("§8.4 question")
    fu_table.add_column("Answer (read from committed state)")
    for q, a in answers.items():
        fu_table.add_row(_ascii(q), _ascii(a))
    _console.print(fu_table)

    dm = ev.demo_moment
    _console.print(f"\n[bold]5. The demo moment (§8.5)[/bold]: {_ascii(dm.question)}")
    _console.print(f"   [red]baseline[/red]: {_ascii(dm.baseline_response)}")
    _console.print(f"   [green]SPC[/green]:      {_ascii(dm.spc_response)}")

    _console.print("\n[bold]6. Scorecard (§20)[/bold]")
    score = Table(box=box.ASCII, show_lines=True)
    score.add_column("Metric")
    score.add_column("SPC vs. baseline")
    for m in ev.metrics:
        score.add_row(_ascii(f"§{m.key} {m.name}"), _ascii(m.headline))
    _console.print(score)


def _load_history(paths: RunPaths) -> list[SemanticState]:
    """Read every committed SemanticState version for a run, in order."""
    store = StateStore(paths)
    latest = store.latest_version()
    if latest is None:
        raise typer.BadParameter(
            f"No state versions found under {paths.state_dir}. Run `spc-demo run` first."
        )
    return [store.read(v) for v in range(latest + 1)]


@app.command()
def followups(
    run_id: str = typer.Option("demo_001", "--run-id", help="Run to interrogate."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    assumption: str = typer.Option(
        "assumption_001",
        "--assumption",
        help="Assumption id used for the dependency follow-up.",
    ),
) -> None:
    """Answer the spec §8.4 demo follow-ups from saved state — no re-prompting."""
    paths = RunPaths(root=runs_dir, run_id=run_id)
    history = _load_history(paths)
    fu = FollowUps(history)

    # The critic's operator name differs between the deterministic
    # (critic_transform) and live (llm_critic_transform) pipelines; find it
    # from the transform log so the follow-up works for either.
    critic_op = next(
        (
            rec.operator
            for rec in reversed(fu.final.transform_log)
            if rec.transform_type == "critique"
        ),
        "critic_transform",
    )

    answers = [
        ("What did the critic add?", fu.what_did_operator_add(critic_op).text),
        ("Which claims are weakest?", fu.weakest_claims().text),
        (
            "Which assumptions most affect the conclusion?",
            fu.assumptions_affecting_conclusion().text,
        ),
        ("Which source supports claim_001?", fu.source_supporting_claim("claim_001").text),
        ("What changed between state v1 and v3?", fu.changes_between(1, 3).text),
        ("Which unresolved questions remain?", fu.unresolved_questions().text),
        (
            f"Which recommendation depends on {assumption}?",
            fu.recommendation_dependencies(assumption).text,
        ),
        (
            "Which claims were inferred rather than observed?",
            fu.claims_by_status(EpistemicStatus.INFERRED).text,
        ),
    ]

    table = Table(title=f"follow-ups — {run_id}", box=box.ASCII, show_lines=True)
    table.add_column("Question")
    table.add_column("Answer (from state)")
    for q, a in answers:
        table.add_row(_ascii(q), _ascii(a))
    _console.print(table)


def _write_baseline_artifacts(paths: RunPaths, result) -> None:
    """Persist the baseline's per-stage JSON and the handoff transcript."""
    paths.baseline_dir.mkdir(parents=True, exist_ok=True)
    for stage in result.stages:
        paths.baseline_file(f"{stage.name}.json").write_text(
            json.dumps(stage.output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    paths.baseline_file("transcript.md").write_text(
        result.transcript_markdown(), encoding="utf-8"
    )


def _resolve_input_text(input: Path | None, paths: RunPaths) -> str:
    """Use --input if given, else the document copied into the run tree."""
    if input is not None:
        return input.read_text(encoding="utf-8")
    saved = paths.input_copy()
    if not saved.exists():
        raise typer.BadParameter(
            f"No input document for run '{paths.run_id}'. Pass --input or run "
            "`spc-demo run` first so the document is saved under the run tree."
        )
    return saved.read_text(encoding="utf-8")


@app.command()
def baseline(
    input: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        readable=True,
        resolve_path=True,
        help="Path to the input document.",
    ),
    run_id: str = typer.Option("demo_001", "--run-id", help="Run tree to write into."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
) -> None:
    """Run the JSON-handoff baseline (spec §8.2) and write its artifacts."""
    paths = RunPaths(root=runs_dir, run_id=run_id)
    result = run_baseline(input.read_text(encoding="utf-8"))
    _write_baseline_artifacts(paths, result)

    _console.print(
        f"[green]baseline:[/green] summary -> critique -> memo "
        f"[dim]({result.total_ingested_tokens} tokens ingested, "
        f"document re-read {result.full_document_reingestions}x)[/dim]"
    )
    _console.print(f"[dim]-> {paths.baseline_file('transcript.md')}[/dim]")


@app.command()
def report(
    run_id: str = typer.Option("demo_001", "--run-id", help="SPC run to evaluate."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    input: Path = typer.Option(
        None,
        "--input",
        "-i",
        exists=True,
        readable=True,
        resolve_path=True,
        help="Input document. Defaults to the copy saved in the run tree.",
    ),
) -> None:
    """Compare the SPC run against the baseline and write the pilot report.

    Reads the committed SPC state history, runs the JSON-handoff baseline over
    the same document, scores both across the spec §20 metrics, and writes
    `report/pilot_report.md` + `report/metrics.json` (Milestone 3).
    """
    paths = RunPaths(root=runs_dir, run_id=run_id)
    history = _load_history(paths)
    document = _resolve_input_text(input, paths)

    baseline_result = run_baseline(document)
    _write_baseline_artifacts(paths, baseline_result)

    generated_at = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=dt.UTC)
    evaluation = evaluate(
        run_id=run_id,
        history=history,
        paths=paths,
        baseline=baseline_result,
        generated_at=generated_at,
    )
    md_path, json_path = write_report(paths, evaluation)

    table = Table(title=f"Pilot scorecard — {run_id}", box=box.ASCII, show_lines=True)
    table.add_column("§ Metric")
    table.add_column("Result (SPC vs baseline)")
    for m in evaluation.metrics:
        table.add_row(f"§{m.key} {m.name}", m.headline)
    _console.print(table)
    _console.print(f"[green]pilot report:[/green] [dim]{md_path}[/dim]")
    _console.print(f"[green]metrics json:[/green] [dim]{json_path}[/dim]")


def _render_summary(result) -> None:
    table = Table(title=f"Run {result.paths.run_id}", show_lines=False, box=box.ASCII)
    table.add_column("Step")
    table.add_column("Operator")
    table.add_column("Patch")
    table.add_column("Decision")
    table.add_column("State")
    table.add_column("Issues")
    for outcome in result.steps:
        state_version = outcome.next_state.state_version if outcome.next_state else "-"
        # An LLM step can end without a parsed patch (e.g. only prose returned).
        operator_name = (
            outcome.patch.transform_record.operator if outcome.patch else "-"
        )
        patch_id = outcome.patch.patch_id if outcome.patch else "-"
        decision = outcome.decision.value
        attempts = getattr(outcome, "attempts", 1)
        if attempts > 1:
            decision = f"{decision} (x{attempts})"
        table.add_row(
            str(outcome.ordinal),
            operator_name,
            patch_id,
            decision,
            str(state_version),
            str(len(outcome.report.issues)),
        )
    _console.print(table)
    _console.print(
        f"[green]final state version:[/green] {result.final_state.state_version} "
        f"[dim]-> {result.paths.state_file(result.final_state.state_version)}[/dim]"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
