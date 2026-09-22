"""Record (or inspect) a provider cassette for the live-run regression harness.

Recording needs `OPENROUTER_API_KEY`, a network, and a few tenths of a cent.
Replaying needs none of those, which is the whole point: the cassette lets CI
regression-test the pipeline against genuine model output.

    # capture a real five-stage run
    python tools/record_cassette.py record \
        --input tests/fixtures/live_document.txt \
        --out tests/fixtures/cassettes/analyze_five_stage.json

    # offline: has the cassette gone stale against today's prompts?
    python tools/record_cassette.py check \
        --input tests/fixtures/live_document.txt \
        --cassette tests/fixtures/cassettes/analyze_five_stage.json

A multi-source run is captured with `--also-input`, one `--also-source-type`
each, and `--also-derives-from` where the caller knows a document was written
off another. That last one changes no prompt — it is the caller's fact, which
the model cannot see — but it decides which corroborations survive and so which
calls the run makes, which means each lineage setting is its own recording.
`check` takes the same arguments, and must be given the same ones: a check that
describes different sources replays against material the recording never saw.
Since T29 it no longer has to be *remembered*: `record` writes the declarations
into the cassette (`RunSpec`), so `check` compares what it was given against
what was captured and says so — a `source_type` declared differently produces a
perfectly drift-free replay of a run that never happened, and that is the one
failure neither the digest nor drift can see. `spc-demo replay --cassette X`
reads the same record and needs no other argument.

`--region` (T22) is the one declaration that needs no recording of its own. It
is applied when spans are stamped, after the model has answered, so it changes
neither the prompts nor the calls — one cassette replays with regions declared
and without, which is what `tests/test_region_replay.py` does.

`check` replays the cassette and reports drift — exchanges whose recorded
request no longer matches what the code now sends. Drift is not a failure (a
contributor without a key must still be able to run the suite); it means the
recording no longer reflects live behaviour and should be re-recorded.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from spc_state.analyze import SourceDocument, run_analysis
from spc_state.providers import (
    OpenRouterConfigError,
    OpenRouterProvider,
    RecordingProvider,
    ReplayProvider,
    RunSpec,
    SourceSpec,
)
from spc_state.regions import SourceRegion, parse_region, resolve_regions
from spc_state.source_types import DEFAULT_SOURCE_TYPE
from spc_state.store import RunPaths

QUESTION = "What does this announcement establish, and what is uncertain?"


def _lineage(value: str, known: set[str]) -> str | None:
    """One `--also-derives-from` value: a known source id, or nothing.

    Validated rather than swallowed, exactly as `cli._lineage_arg` does it: a
    typo'd parent silently buys back the independence the flag was passed to
    deny, and the failure mode is a corroboration nobody checked.
    """
    cleaned = value.strip()
    if cleaned.lower() in ("", "none", "-"):
        return None
    if cleaned not in known:
        raise ValueError(
            f"--also-derives-from {value!r} is not a source in this run. Known "
            f"sources: {', '.join(sorted(known))} (doc_001 is --input, extras "
            "follow in the order given), or 'none'."
        )
    return cleaned


def _sources(
    args: argparse.Namespace,
) -> tuple[str, list[SourceDocument], list[str], tuple[SourceRegion, ...], RunSpec]:
    """The primary document, the extra ones, every text in reading order, regions, spec.

    The third is what the cassette pins: a multi-source run has no single
    document, so it records all of them, in the order the pipeline reads them.
    The fourth carves `--input` into stretches weighed differently (T22). It is
    located here as well as by the run, so a marker that does not occur is
    refused before anything is spent — never silently dropped, which would leave
    a run that looks region-aware and is not.

    The fifth is the half a digest cannot pin: how the caller *declared* those
    documents. `record` stores it in the cassette so a replay needs no other
    argument and cannot silently contradict the recording — see `RunSpec`.
    Regions are deliberately not part of it.
    """
    document = Path(args.input).read_text(encoding="utf-8")
    extra_paths = list(getattr(args, "also_input", []) or [])
    extra_types = list(getattr(args, "also_source_type", []) or [])
    parents = list(getattr(args, "also_derives_from", []) or [])
    if len(extra_paths) != len(extra_types):
        raise ValueError(
            f"{len(extra_paths)} --also-input but {len(extra_types)} "
            "--also-source-type: give one source type per extra document."
        )
    if parents and len(parents) != len(extra_paths):
        raise ValueError(
            f"{len(extra_paths)} --also-input but {len(parents)} "
            "--also-derives-from: give one per extra document, in the same "
            "order, using 'none' for a document that stands on its own. Omit "
            "the option entirely to declare every document independent."
        )
    known = {f"doc_{i:03d}" for i in range(1, len(extra_paths) + 2)}
    lineage = [_lineage(v, known) for v in parents] or [None] * len(extra_paths)
    extras = [
        SourceDocument(
            text=Path(p).read_text(encoding="utf-8"),
            source_type=st,
            derives_from=parent,
        )
        for p, st, parent in zip(extra_paths, extra_types, lineage, strict=True)
    ]
    regions = tuple(
        parse_region(spec) for spec in (getattr(args, "region", []) or [])
    )
    # Located here rather than left to the pipeline, so a marker that does not
    # occur is reported before the first billed call rather than as a traceback
    # after several. The result is discarded: the run resolves them itself,
    # against the same document.
    resolve_regions(document, regions)
    spec = RunSpec(
        question=args.question,
        sources=[
            SourceSpec(path=str(args.input), source_type=str(args.source_type)),
            *(
                SourceSpec(path=str(p), source_type=str(st), derives_from=parent)
                for p, st, parent in zip(
                    extra_paths, extra_types, lineage, strict=True
                )
            ),
        ],
    )
    return document, extras, [document, *(e.text for e in extras)], regions, spec


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    """The arguments that say what the run reads — identical on both commands.

    `check` must describe the same sources as the `record` that made the
    cassette, or it replays against material the recording never saw. Sharing
    one definition is what keeps the two from drifting apart.
    """
    parser.add_argument("--input", required=True, help="document to analyze")
    parser.add_argument(
        "--source-type",
        default=DEFAULT_SOURCE_TYPE.value,
        help="what kind of document --input is (default: %(default)s)",
    )
    parser.add_argument(
        "--also-input",
        action="append",
        default=[],
        help="a further document read into the same state; repeatable, and "
        "pair each with an --also-source-type in the same order",
    )
    parser.add_argument(
        "--also-source-type",
        action="append",
        default=[],
        help="source type for each --also-input, in the same order",
    )
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        help="carve --input into stretches weighed differently, as "
        "'<marker>:<source_type>' — e.g. 'Item 7.01:press_release'. A span takes "
        "the source type of the last region beginning at or before it. "
        "Repeatable; omit entirely to weigh the whole document as "
        "--source-type. Like lineage, this changes no prompt — but unlike "
        "lineage it changes no call either, so one recording replays with "
        "regions declared and without",
    )
    parser.add_argument(
        "--also-derives-from",
        action="append",
        default=[],
        help="for an --also-input written off another document, the source id "
        "it came from (doc_001 is --input; extras are doc_002, ... in order). "
        "Repeatable, one per extra document, 'none' to skip one; omit entirely "
        "to declare every document independent. Lineage changes no prompt — it "
        "is the caller's fact — but it changes which corroborations survive, "
        "and so which calls the run makes: record each setting separately",
    )
    parser.add_argument(
        "--question",
        default=QUESTION,
        help="the decision question recorded in the receipt",
    )


def _record(args: argparse.Namespace) -> int:
    try:
        document, extras, documents, regions, spec = _sources(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        # `json_object` off is a real supported configuration, not a hack: the
        # provider requests structured output because it is *broadly*, not
        # universally, supported. Turning it off is how the pipeline behaves
        # against a model that cannot honour it — and the only way to capture
        # output the JSON_DECODE retry path exists for.
        live = OpenRouterProvider(
            model=args.model,
            json_object=not args.no_json_object,
            max_tokens=args.max_tokens,
        )
    except OpenRouterConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    recorder = RecordingProvider(
        live,
        documents=documents,
        provider="openrouter",
        model=live.model,
        note=args.note,
        run_spec=spec,
    )

    with tempfile.TemporaryDirectory() as tmp:
        paths = RunPaths(root=Path(tmp), run_id="record")
        result = run_analysis(
            recorder,
            document,
            paths,
            question=args.question,
            source_type=args.source_type,
            regions=regions,
            extra_documents=extras,
        )

    final = result.run.final_state
    if final.state_version == 0 and not args.allow_uncommitted:
        print(
            "error: the run committed nothing — not writing a cassette. Pass "
            "--allow-uncommitted to capture a failure path deliberately.",
            file=sys.stderr,
        )
        return 1

    out = Path(args.out)
    recorder.cassette().save(out)
    print(f"recorded {recorder.call_count} exchange(s) from {live.model} -> {out}")
    print(
        f"committed state v{final.state_version}: {len(final.claims)} claims, "
        f"{len(final.evidence)} evidence, {len(final.questions)} questions"
    )
    for step in result.run.steps:
        flag = " <- RETRIED" if step.attempts > 1 else ""
        print(
            f"  step {step.ordinal}: {step.decision.value} "
            f"after {step.attempts} attempt(s){flag}"
        )
    return 0


def _check(args: argparse.Namespace) -> int:
    try:
        document, extras, documents, regions, _spec = _sources(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    extra_types = list(getattr(args, "also_source_type", []) or [])
    provider = ReplayProvider.from_path(Path(args.cassette), documents=documents)
    recorded = len(provider.cassette.exchanges)

    # A check that describes the run differently from the recording is checking
    # something else. `source_type` and `--also-derives-from` reach no prompt,
    # so no amount of drift reporting would reveal it — only the recorded
    # declarations can.
    recorded_spec = provider.cassette.run_spec
    deviations = (
        recorded_spec.deviations(
            question=args.question,
            source_types=[str(args.source_type), *(str(t) for t in extra_types)],
            lineage=[e.derives_from for e in extras],
        )
        if recorded_spec is not None
        else []
    )

    with tempfile.TemporaryDirectory() as tmp:
        paths = RunPaths(root=Path(tmp), run_id="check")
        result = run_analysis(
            provider,
            document,
            paths,
            question=args.question,
            source_type=args.source_type,
            regions=regions,
            extra_documents=extras,
        )

    print(f"cassette: {args.cassette}")
    print(f"  recorded {recorded} exchange(s) from {provider.cassette.model}")
    print(f"  replayed {provider.call_count}, committed state v{result.run.final_state.state_version}")
    if provider.drifted_calls:
        print(
            f"  STALE: {len(provider.drifted_calls)} exchange(s) no longer match the "
            f"current prompts (indices {provider.drifted_calls}). Re-record."
        )
    else:
        print("  current: every recorded request matches what the code sends today.")

    # Reported last and after the drift verdict, because it changes what that
    # verdict is worth: a differently-declared run can be perfectly drift-free
    # and still not be the run that was recorded, and a reader who saw
    # "current" first would take it as an all-clear.
    if recorded_spec is None:
        print(
            "  note: this cassette records no declarations (predates RunSpec), "
            "so the ones given cannot be checked."
        )
    elif deviations:
        print(
            "  DECLARED DIFFERENTLY from the recording — the run above is not "
            "the one that was captured, whatever the drift verdict says:"
        )
        for line in deviations:
            print(f"    {line}")

    return 1 if (provider.drifted_calls or deviations) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="capture a real run (needs OPENROUTER_API_KEY)")
    _add_source_args(rec)
    rec.add_argument("--out", required=True, help="cassette path to write")
    rec.add_argument("--model", default=None, help="OpenRouter model slug")
    rec.add_argument("--note", default="", help="free-text note stored in the cassette")
    rec.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help=(
            "completion token cap. Lower it to capture a truncated reply, the "
            "commonest real cause of unparseable model output."
        ),
    )
    rec.add_argument(
        "--no-json-object",
        action="store_true",
        help="do not request structured output (captures unstructured replies)",
    )
    rec.add_argument(
        "--allow-uncommitted",
        action="store_true",
        help="write the cassette even if the run committed nothing (failure paths)",
    )
    rec.set_defaults(func=_record)

    chk = sub.add_parser("check", help="replay offline and report drift")
    _add_source_args(chk)
    chk.add_argument("--cassette", required=True, help="cassette path to inspect")
    chk.set_defaults(func=_check)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
