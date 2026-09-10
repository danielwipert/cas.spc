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

from spc_state.analyze import run_analysis
from spc_state.providers import (
    OpenRouterConfigError,
    OpenRouterProvider,
    RecordingProvider,
    ReplayProvider,
)
from spc_state.store import RunPaths

QUESTION = "What does this announcement establish, and what is uncertain?"


def _record(args: argparse.Namespace) -> int:
    document = Path(args.input).read_text(encoding="utf-8")
    try:
        live = OpenRouterProvider(model=args.model)
    except OpenRouterConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    recorder = RecordingProvider(
        live,
        document=document,
        provider="openrouter",
        model=live.model,
        note=args.note,
    )

    with tempfile.TemporaryDirectory() as tmp:
        paths = RunPaths(root=Path(tmp), run_id="record")
        result = run_analysis(recorder, document, paths, question=QUESTION)

    final = result.run.final_state
    if final.state_version == 0:
        print("error: the run committed nothing — not writing a cassette.", file=sys.stderr)
        return 1

    out = Path(args.out)
    recorder.cassette().save(out)
    print(f"recorded {recorder.call_count} exchange(s) from {live.model} -> {out}")
    print(
        f"committed state v{final.state_version}: {len(final.claims)} claims, "
        f"{len(final.evidence)} evidence, {len(final.questions)} questions"
    )
    return 0


def _check(args: argparse.Namespace) -> int:
    document = Path(args.input).read_text(encoding="utf-8")
    provider = ReplayProvider.from_path(Path(args.cassette), document=document)
    recorded = len(provider.cassette.exchanges)

    with tempfile.TemporaryDirectory() as tmp:
        paths = RunPaths(root=Path(tmp), run_id="check")
        result = run_analysis(provider, document, paths, question=QUESTION)

    print(f"cassette: {args.cassette}")
    print(f"  recorded {recorded} exchange(s) from {provider.cassette.model}")
    print(f"  replayed {provider.call_count}, committed state v{result.run.final_state.state_version}")
    if provider.drifted_calls:
        print(
            f"  STALE: {len(provider.drifted_calls)} exchange(s) no longer match the "
            f"current prompts (indices {provider.drifted_calls}). Re-record."
        )
        return 1
    print("  current: every recorded request matches what the code sends today.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="capture a real run (needs OPENROUTER_API_KEY)")
    rec.add_argument("--input", required=True, help="document to analyze")
    rec.add_argument("--out", required=True, help="cassette path to write")
    rec.add_argument("--model", default=None, help="OpenRouter model slug")
    rec.add_argument("--note", default="", help="free-text note stored in the cassette")
    rec.set_defaults(func=_record)

    chk = sub.add_parser("check", help="replay offline and report drift")
    chk.add_argument("--input", required=True, help="document the cassette was recorded from")
    chk.add_argument("--cassette", required=True, help="cassette path to inspect")
    chk.set_defaults(func=_check)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
