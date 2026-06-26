"""Command-line interface for the SPC pilot demo.

Phase 3 wires `spc-demo run` to the runtime: it bootstraps an empty
`SemanticState v0`, applies Extract → Planner → Critic, and writes the
canonical `runs/<run_id>/` artifact tree.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from . import __version__
from .models import EpistemicStatus, SemanticState
from .operators import CriticOperator, ExtractOperator, PlannerOperator
from .receipt import FollowUps, write_run_artifacts
from .runtime import FixedClock, Runtime, WallClock, bootstrap_state
from .store import RunPaths, StateStore

app = typer.Typer(
    name="spc-demo",
    help="SPC Shared Semantic State Engine — pilot demo runner.",
    add_completion=False,
    no_args_is_help=True,
)

_console = Console()


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(f"spc-state {__version__}")


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
) -> None:
    """Run the deterministic demo pipeline against an input document.

    Writes the canonical artifact tree under `<runs-dir>/<run-id>/`:
    state snapshots, patches, validation reports, audit log, plus the input
    document copied verbatim.
    """
    input_text = input.read_text(encoding="utf-8")
    paths = RunPaths(root=runs_dir, run_id=run_id)

    if deterministic:
        # 12 evenly-spaced timestamps cover every clock.now() call in the
        # three-operator demo run. WallClock is used otherwise.
        start = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=dt.timezone.utc)
        clock = FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(48)])
    else:
        clock = WallClock()

    initial = bootstrap_state(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="AI Coding Assistant Adoption Analysis",
        now=clock.now(),
    )

    runtime = Runtime(paths=paths, clock=clock)
    operators = [
        ExtractOperator(input_text=input_text, clock=clock),
        PlannerOperator(clock=clock),
        CriticOperator(clock=clock),
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

    answers = [
        ("What did the critic add?", fu.what_did_operator_add("critic_transform").text),
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

    table = Table(title=f"§8.4 follow-ups — {run_id}", box=box.ASCII, show_lines=True)
    table.add_column("Question")
    table.add_column("Answer (from state)")
    for q, a in answers:
        table.add_row(q, a)
    _console.print(table)


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
        table.add_row(
            str(outcome.ordinal),
            outcome.patch.transform_record.operator,
            outcome.patch.patch_id,
            outcome.decision.value,
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
