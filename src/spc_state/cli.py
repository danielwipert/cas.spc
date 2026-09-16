"""Command-line interface for the SPC pilot demo.

Phase 3 wires `spc-demo run` to the runtime: it bootstraps an empty
`SemanticState v0`, applies Extract → Planner → Critic, and writes the
canonical `runs/<run_id>/` artifact tree.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
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
from .providers import (
    Cassette,
    CassetteError,
    OpenRouterConfigError,
    OpenRouterProvider,
    ReplayProvider,
    RunSpec,
)
from .receipt import FollowUps, write_run_artifacts
from .regions import RegionError, SourceRegion, parse_region, resolve_regions
from .runtime import Clock, FixedClock, Runtime, WallClock, bootstrap_state
from .source_types import (
    DEFAULT_SOURCE_TYPE,
    SourceType,
    coerce_source_type,
    reliability_for,
)
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


@dataclass(frozen=True)
class _Declared:
    """What the caller said the run reads — resolved once, used by two commands.

    `analyze` and `replay` must describe a run *identically*: a replay that
    declares different sources than the recording replays against material the
    recording never saw. Sharing one resolver is what stops the two drifting
    apart, the same reason `tools/record_cassette.py` shares `_add_source_args`
    between `record` and `check`.
    """

    #: The primary document's text (`doc_001`).
    document: str
    #: The extra documents, in the order the pipeline reads them.
    extras: list[SourceDocument]
    #: Every text in reading order — what a cassette pins (T25).
    texts: list[str]
    #: Regions carving the primary document into stretches weighed differently.
    regions: tuple[SourceRegion, ...]
    #: Each region with the offset it resolved to, for echoing back.
    located: list[tuple[SourceRegion, int]]


def _declare_sources(
    input: Path,
    *,
    also_input: list[Path],
    also_source_type: list[SourceType],
    also_derives_from: list[str],
    region: list[str],
) -> _Declared:
    """Validate the source declarations and read every document.

    Every failure here is a `BadParameter`, never a traceback from inside the
    pipeline: for `analyze` that means it is caught before a billed call, and a
    marker that does not occur used to be found only after several (T27).

    Keyword-only past `input` on purpose: four of the five arguments are
    same-typed lists whose meanings are not interchangeable, and a positional
    call that transposed two of them would read as valid and mis-weigh a
    document.
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
    try:
        regions = tuple(parse_region(spec) for spec in region)
        # Resolved per declaration rather than in bulk: `resolve_regions`
        # returns them in *document* order, which is what the extractor wants
        # and not what the caller typed. Pairing the two would misreport a
        # marker declared out of order.
        located = [(r, resolve_regions(document, [r])[0].start) for r in regions]
    except RegionError as exc:
        raise typer.BadParameter(str(exc)) from exc

    extras = [
        SourceDocument(
            text=path.read_text(encoding="utf-8"), source_type=st, derives_from=parent
        )
        for path, st, parent in zip(
            also_input, also_source_type, lineage, strict=True
        )
    ]
    return _Declared(
        document=document,
        extras=extras,
        texts=[document, *(e.text for e in extras)],
        regions=regions,
        located=located,
    )


@dataclass(frozen=True)
class _Resolved:
    """The declarations to run with, after the cassette has filled the blanks."""

    input: Path
    question: str
    source_type: SourceType
    also_input: list[Path]
    also_source_type: list[SourceType]
    also_derives_from: list[str]


def _resolve_against_spec(
    spec: RunSpec | None,
    *,
    input: Path | None,
    question: str | None,
    source_type: SourceType | None,
    also_input: list[Path],
    also_source_type: list[SourceType],
    also_derives_from: list[str],
) -> _Resolved:
    """Fill each declaration the caller left out from the recording's own.

    An argument given on the command line always wins — overriding a
    declaration that reaches no prompt is a real experiment, and `replay`
    reports it as a deviation rather than refusing it. What is *omitted* comes
    from the cassette, which is the whole point of recording it: a caller who
    passes only `--cassette` gets the run that was captured.

    Extra sources are all-or-nothing. Half a multi-source declaration — the
    paths from the cassette and the lineage from the caller, say — is a run
    nobody described, and silently pairing them by index is how a document ends
    up weighed as its neighbour.
    """
    recorded_sources = list(spec.sources) if spec is not None else []
    primary = recorded_sources[0] if recorded_sources else None

    if input is None:
        if primary is None:
            raise typer.BadParameter("--input is required: the cassette names no source.")
        input = Path(primary.path)
        if not input.exists():
            raise typer.BadParameter(
                f"the cassette records its source as {primary.path!r}, which does "
                "not exist from here. Run from the repository root, or pass "
                "--input explicitly."
            )
    if question is None:
        question = spec.question if spec is not None else DEFAULT_QUESTION
    if source_type is None:
        source_type = (
            coerce_source_type(primary.source_type)
            if primary is not None
            else DEFAULT_SOURCE_TYPE
        )

    if not also_input and len(recorded_sources) > 1:
        if also_source_type or also_derives_from:
            raise typer.BadParameter(
                "--also-source-type/--also-derives-from were given without "
                "--also-input. Either pass every extra source explicitly, or "
                "pass none of them and take all of the cassette's."
            )
        extras = recorded_sources[1:]
        also_input = [Path(s.path) for s in extras]
        missing = [str(path) for path in also_input if not path.exists()]
        if missing:
            raise typer.BadParameter(
                f"the cassette records extra sources that do not exist from "
                f"here: {', '.join(missing)}. Run from the repository root, or "
                "pass --also-input explicitly."
            )
        also_source_type = [coerce_source_type(s.source_type) for s in extras]
        # 'none' is the CLI's spelling for "derives from nothing", and
        # `_lineage_arg` is what reads it back.
        also_derives_from = [s.derives_from or "none" for s in extras]

    return _Resolved(
        input=input,
        question=question,
        source_type=source_type,
        also_input=also_input,
        also_source_type=also_source_type,
        also_derives_from=also_derives_from,
    )


def _echo_declarations(
    declared: _Declared,
    source_type: SourceType,
    also_input: list[Path],
    also_source_type: list[SourceType],
) -> None:
    """Print what the run was told, in the order the pipeline reads it."""
    _console.print(
        f"[yellow]source type:[/yellow] {source_type.value} "
        f"[dim](evidence reliability: {reliability_for(source_type).value})[/dim]"
    )
    for declared_region, start in declared.located:
        _console.print(
            f"[yellow]region:[/yellow] {declared_region.source_type.value} "
            f"[dim]({reliability_for(declared_region.source_type).value}) from "
            f"offset {start} — {declared_region.marker!r}[/dim]"
        )
    for i, (path, st, extra) in enumerate(
        zip(also_input, also_source_type, declared.extras, strict=True), start=2
    ):
        origin = f", derives from {extra.derives_from}" if extra.derives_from else ""
        _console.print(
            f"[yellow]also source {i}:[/yellow] {st.value} "
            f"[dim]({reliability_for(st).value}{origin}) — {path.name}[/dim]"
        )


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
    region: list[str] = typer.Option(
        [],
        "--region",
        help="Carve --input into stretches weighed differently, as "
        "'<marker>:<source_type>' — e.g. 'Item 7.01:press_release'. A span "
        "takes the source type of the last region beginning at or before it. A "
        "filing is not one block of accountability: an 8-K's Item 7.01 exhibits "
        "are furnished rather than filed, and say so themselves. Repeatable; "
        "omit entirely to weigh the whole document as --source-type.",
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
    declared = _declare_sources(
        input,
        also_input=list(also_input),
        also_source_type=list(also_source_type),
        also_derives_from=list(also_derives_from),
        region=list(region),
    )
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
    _echo_declarations(declared, source_type, list(also_input), list(also_source_type))

    analysis = run_analysis(
        provider,
        declared.document,
        paths,
        clock=clock,
        question=question,
        extract_only=extract_only,
        source_type=source_type,
        regions=declared.regions,
        extra_documents=declared.extras,
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


#: How many distinct timestamps a replayed run is handed.
#:
#: A replay must be byte-reproducible — that is the whole reason to prefer it to
#: a live run — so it cannot use the wall clock. `FixedClock` reuses its last
#: value once exhausted, which would collapse the tail of a long audit log onto
#: one instant, so the sequence is generous: 512 is far more stamps than any
#: pipeline stage count, and an unused stamp costs nothing.
_REPLAY_TIMESTAMPS = 512


@app.command()
def replay(
    cassette: Path = typer.Option(
        ...,
        "--cassette",
        "-c",
        exists=True,
        readable=True,
        resolve_path=True,
        help="A recorded cassette (tests/fixtures/cassettes/*.json).",
    ),
    input: Path | None = typer.Option(
        None,
        "--input",
        "-i",
        exists=True,
        readable=True,
        resolve_path=True,
        help="The document the cassette was recorded against. Optional for a "
        "cassette that records its own declarations — omit it and the "
        "recording's own path is used.",
    ),
    run_id: str = typer.Option("replay_001", "--run-id", help="Run id."),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir"),
    question: str | None = typer.Option(
        None,
        "--question",
        "-q",
        help="The decision question the cassette was recorded with. Defaults "
        "to the recorded one.",
    ),
    source_type: SourceType | None = typer.Option(
        None,
        "--source-type",
        case_sensitive=False,
        help="What kind of document --input is. Defaults to the recorded "
        "declaration. Overriding it is a legitimate experiment — it changes no "
        "prompt — but it is reported as a deviation, because a *mistaken* one "
        "replays just as cleanly and hands back a different memo.",
    ),
    also_input: list[Path] = typer.Option(
        [],
        "--also-input",
        exists=True,
        readable=True,
        resolve_path=True,
        help="A further document the cassette was recorded over. Repeatable; "
        "pair each with an --also-source-type in the same order.",
    ),
    also_source_type: list[SourceType] = typer.Option(
        [],
        "--also-source-type",
        case_sensitive=False,
        help="Source type for each --also-input, in the same order.",
    ),
    region: list[str] = typer.Option(
        [],
        "--region",
        help="Carve --input into stretches weighed differently, as "
        "'<marker>:<source_type>'. Unlike the other declarations this one need "
        "not match the recording: a region is applied when spans are stamped, "
        "after the model has answered, so one cassette replays with regions "
        "and without. Repeatable.",
    ),
    also_derives_from: list[str] = typer.Option(
        [],
        "--also-derives-from",
        help="For an --also-input written off another document, the source id "
        "it came from. Repeatable, one per extra document, 'none' to skip one. "
        "Declare what the recording declared: lineage drops corroboration "
        "candidates before the skeptic pass, so changing it changes which "
        "calls the run makes and the cassette misaligns from that point on "
        "(reported as drift). Each lineage setting needs its own recording.",
    ),
    extract_only: bool = typer.Option(
        False,
        "--extract-only",
        help="Stop after extraction (skip the remaining five stages).",
    ),
) -> None:
    """Replay a recorded run offline and write its memo — no key, no network.

    Every claim this engine makes about real model output rests on a cassette,
    and until now a cassette could only be replayed from inside `pytest`. That
    made the outputs the engine exists to produce — the Decision Memo a reader
    opens, the Reasoning Receipt behind it — the one thing a contributor could
    not simply look at. `replay` is that: the same pipeline as `analyze`, driven
    from a recording instead of OpenRouter.

    It is free and deterministic. No `OPENROUTER_API_KEY` is needed, nothing is
    spent, and two replays of one cassette write byte-identical artifacts
    (the clock is fixed to the recording's own timestamp), so an output can be
    diffed across a change to the engine.

    **The declarations are yours to get right, and cannot be checked.** The
    cassette pins the documents it was recorded against — a wrong `--input` is
    refused outright — but it records nothing about how they were *declared*.
    `--source-type` and `--also-derives-from` are the caller's facts, which the
    model never sees (T14), so they reach no prompt: declare them differently
    from the recording and the replay still runs clean and hands you a
    different memo. Drift detection will not catch it, because no request
    changed. `--region` is the deliberate exception (T27): it is resolved after
    the model has answered, so varying it over one recording is the point.

    Two signals are reported after the run, and neither is an error:

      drift       - a recorded request no longer matches what the code sends
                    today, so this memo is what the *old* prompt produced.
                    Re-record (`tools/record_cassette.py record`). Drift also
                    fires when the replay makes a *different* set of calls than
                    the recording and the exchanges misalign from that point
                    on — which is what changing --also-derives-from does, and
                    why each lineage setting needs its own recording (T26).
      unreplayed  - the pipeline asked for fewer completions than the cassette
                    holds, so recorded exchanges went unused. Expected with
                    --extract-only, which stops five stages early.

    Treat a memo produced under either signal as untrustworthy: it is not what
    the recorded run produced.
    """
    # The cassette is read before the declarations are resolved, because it may
    # supply them. Its `RunSpec` is what makes `--cassette` sufficient on its
    # own; a cassette recorded before that existed still needs them passed.
    try:
        recorded_spec = Cassette.load(cassette).run_spec
    except CassetteError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if recorded_spec is None and input is None:
        raise typer.BadParameter(
            f"{cassette.name} records no declarations (it predates RunSpec), so "
            "--input is required. Re-record it, or pass the same --input, "
            "--source-type, --question and --also-* the recording was made with."
        )

    resolved = _resolve_against_spec(
        recorded_spec,
        input=input,
        question=question,
        source_type=source_type,
        also_input=list(also_input),
        also_source_type=list(also_source_type),
        also_derives_from=list(also_derives_from),
    )
    declared = _declare_sources(
        resolved.input,
        also_input=resolved.also_input,
        also_source_type=resolved.also_source_type,
        also_derives_from=resolved.also_derives_from,
        region=list(region),
    )
    question = resolved.question
    source_type = resolved.source_type

    try:
        provider = ReplayProvider.from_path(cassette, documents=declared.texts)
    except CassetteError as exc:
        raise typer.BadParameter(str(exc)) from exc

    recorded = len(provider.cassette.exchanges)
    stages = (
        "extract"
        if extract_only
        else "extract -> plan -> critique -> retrieve -> verify -> calibrate"
    )
    _console.print(
        f"[cyan]replaying {recorded} exchange(s):[/cyan] {cassette.name} "
        f"[dim]({provider.cassette.model}, recorded "
        f"{provider.cassette.recorded_at.date()})[/dim]"
    )
    if provider.cassette.note:
        _console.print(f"[cyan]note:[/cyan] [dim]{_ascii(provider.cassette.note)}[/dim]")
    _console.print(f"[cyan]stages:[/cyan] [dim]{stages}[/dim]")
    _echo_declarations(
        declared, source_type, resolved.also_input, resolved.also_source_type
    )
    if recorded_spec is None:
        _console.print(
            "[dim]this cassette records no declarations, so the ones above "
            "cannot be checked against it — see --help[/dim]"
        )
    else:
        deviations = recorded_spec.deviations(
            question=question,
            source_types=[
                source_type.value, *(t.value for t in resolved.also_source_type)
            ],
            lineage=[e.derives_from for e in declared.extras],
        )
        if deviations:
            _console.print(
                "[yellow]declared differently from the recording[/yellow] "
                "[dim](legitimate for an experiment, wrong by accident):[/dim]"
            )
            for line in deviations:
                _console.print(f"  [yellow]-[/yellow] [dim]{_ascii(line)}[/dim]")
        else:
            _console.print(
                "[green]as recorded:[/green] [dim]every declaration matches the "
                "cassette's own[/dim]"
            )

    paths = RunPaths(root=runs_dir, run_id=run_id)
    # Seeded from the recording so one cassette always replays to the same
    # bytes, and so the audit log reads as the run it captured rather than as
    # whenever someone happened to look at it.
    start = provider.cassette.recorded_at
    clock = FixedClock(
        [start + dt.timedelta(seconds=i) for i in range(_REPLAY_TIMESTAMPS)]
    )

    analysis = run_analysis(
        provider,
        declared.document,
        paths,
        clock=clock,
        question=question,
        extract_only=extract_only,
        source_type=source_type,
        regions=declared.regions,
        extra_documents=declared.extras,
    )

    _render_summary(analysis.run)

    if provider.drifted_calls:
        _console.print(
            f"[red]drift:[/red] {len(provider.drifted_calls)} of {recorded} recorded "
            f"request(s) no longer match today's prompts "
            f"[dim](indices {provider.drifted_calls})[/dim] — this memo is what "
            "the old prompt produced. Re-record the cassette."
        )
    else:
        _console.print(
            "[green]no drift:[/green] [dim]every replayed request matches what "
            "the code sends today[/dim]"
        )
    if not provider.exhausted:
        _console.print(
            f"[yellow]unreplayed:[/yellow] the pipeline asked for "
            f"{provider.call_count} completion(s) of {recorded} recorded "
            "[dim](expected with --extract-only, or when lineage denies an "
            "independence the recording assumed)[/dim]"
        )

    if analysis.artifacts is None or analysis.memo_path is None:
        _console.print(
            "[red]Nothing committed — the recorded extraction produced no valid patch.[/red]"
        )
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
