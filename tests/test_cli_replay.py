"""`spc-demo replay` — the outputs this engine produces, made viewable.

Every claim the T14–T27 arc makes about *real* model output rests on a
cassette, and until now a cassette could only be replayed from inside
`pytest`. That left the two artifacts the engine exists to produce — the
Decision Memo a reader opens and the Reasoning Receipt behind it — as the one
thing a contributor could not simply look at. Judging an output is the next
piece of work; being able to see one is its precondition.

The tests here assert the properties that make a replay worth trusting rather
than the numbers one cassette happens to produce:

* it needs no key, no network and spends nothing;
* two replays of one cassette write **byte-identical** artifacts, so an output
  can be diffed across a change to the engine;
* a cassette refuses a document it was not recorded against;
* drift and unreplayed exchanges are both reported, because a memo produced
  under either is not what the recorded run produced;
* and the declarations the cassette *cannot* check are echoed back, since a
  mistyped `--source-type` reaches no prompt and so replays perfectly clean.
"""

from __future__ import annotations

import filecmp
from pathlib import Path

import pytest
from typer.testing import CliRunner

from spc_state.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
CASSETTES = FIXTURES / "cassettes"

#: Netflix's 8-K as EDGAR serves the complete submission: Item 1.01 filed,
#: Item 7.01 and Exhibit 99.1 furnished. T27's fixture, and the one cassette
#: that replays correctly both with a region declared and without.
COMPLETE_8K = FIXTURES / "sec_8k_netflix_complete.txt"
CASSETTE_8K = CASSETTES / "analyze_8k_complete.json"
QUESTION = "What did Netflix agree to, and on what terms?"
FURNISHED = "Item 7.01:press_release"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the claim: replay reaches no provider that could need a key.

    Removed for every test here, so a replay that somehow tried to talk to
    OpenRouter would fail rather than quietly succeed on a developer's key.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def _replay(runs_dir: Path, run_id: str, *extra: str) -> object:
    """Replay the 8-K cassette, with whatever declarations the test adds."""
    return runner.invoke(
        app,
        [
            "replay",
            "--cassette", str(CASSETTE_8K),
            "--input", str(COMPLETE_8K),
            "--source-type", "regulatory_filing",
            "--question", QUESTION,
            "--runs-dir", str(runs_dir),
            "--run-id", run_id,
            *extra,
        ],
    )


def _confidence(memo: Path) -> int:
    """The recommendation's confidence, read off the memo a reader opens."""
    for line in memo.read_text(encoding="utf-8").splitlines():
        if line.startswith("_Confidence:"):
            return int(line.split(":")[1].strip().rstrip("._%"))
    raise AssertionError("the memo states no confidence for its recommendation")


def test_a_replay_needs_no_key_and_writes_the_memo(tmp_path: Path) -> None:
    """The point of the command: an output you can read, for nothing."""
    result = _replay(tmp_path, "peek")
    assert result.exit_code == 0, result.output

    memo = tmp_path / "peek" / "memo.md"
    assert memo.exists(), "a replay wrote no memo"
    text = memo.read_text(encoding="utf-8")
    assert "## Key findings" in text
    assert "## Sources" in text
    # Not a number: that every finding carries a citation is the invariant.
    assert "[E1]" in text


def test_two_replays_of_one_cassette_are_byte_identical(tmp_path: Path) -> None:
    """What makes a replayed output usable as a yardstick.

    A live run cannot be a baseline — the model moves. A replay can, but only
    if nothing else moves either, so the clock is fixed to the recording's own
    timestamp rather than read off the wall.
    """
    first, second = tmp_path / "a", tmp_path / "b"
    assert _replay(first, "peek").exit_code == 0
    assert _replay(second, "peek").exit_code == 0

    left, right = first / "peek", second / "peek"
    compared = filecmp.dircmp(left, right)
    assert compared.diff_files == [], f"replays differ: {compared.diff_files}"
    assert compared.left_only == [] and compared.right_only == []
    # dircmp does not recurse on its own; the run tree is several levels deep.
    for sub in compared.subdirs.values():
        assert sub.diff_files == [], f"replays differ under {sub.left}"


def test_a_cassette_refuses_a_document_it_was_not_recorded_against(
    tmp_path: Path,
) -> None:
    """The one declaration the cassette *can* check, and does."""
    result = runner.invoke(
        app,
        [
            "replay",
            "--cassette", str(CASSETTE_8K),
            "--input", str(FIXTURES / "live_document.txt"),
            "--runs-dir", str(tmp_path),
            "--run-id", "wrong",
        ],
    )
    assert result.exit_code != 0
    assert "different source material" in result.output
    assert not (tmp_path / "wrong" / "memo.md").exists()


def test_a_region_marker_that_does_not_occur_is_refused(tmp_path: Path) -> None:
    """Refused before the run, not as a traceback from inside it (T27)."""
    result = _replay(tmp_path, "bad", "--region", "Item 99.99:press_release")
    assert result.exit_code != 0
    assert "does not occur" in result.output


def test_mismatched_extra_sources_are_refused(tmp_path: Path) -> None:
    """`replay` and `analyze` share one resolver, so both refuse this."""
    result = _replay(
        tmp_path,
        "bad",
        "--also-input", str(FIXTURES / "joint_pr_wbd.txt"),
    )
    assert result.exit_code != 0
    assert "--also-source-type" in result.output


def test_a_current_cassette_reports_no_drift(tmp_path: Path) -> None:
    """Drift is the signal that a memo came from a prompt no longer in use."""
    result = _replay(tmp_path, "peek")
    assert "no drift" in result.output


def test_extract_only_reports_the_exchanges_it_left_unreplayed(
    tmp_path: Path,
) -> None:
    """Stopping five stages early leaves recorded exchanges unused, and says so."""
    result = _replay(tmp_path, "eo", "--extract-only")
    assert result.exit_code == 0
    assert "unreplayed" in result.output


def test_the_declarations_are_echoed_and_checked(tmp_path: Path) -> None:
    """The command says what it was told, and whether that is the recording.

    `--source-type` is the caller's fact and reaches no prompt (T14), so a
    mistyped one replays with zero drift and hands back a different memo.
    Echoing them was T28's only defence; since T29 the cassette records its own
    declarations, so the echo is checked rather than merely printed.
    """
    result = _replay(tmp_path, "peek", "--region", FURNISHED)
    assert "regulatory_filing" in result.output
    assert "press_release" in result.output
    assert "as recorded" in result.output


def test_a_region_is_never_a_deviation(tmp_path: Path) -> None:
    """The declaration deliberately left out of the recording (T27).

    A region is resolved after the model has answered, so one cassette must
    replay with regions declared and without — that is the controlled
    experiment. Recording it would turn the experiment into a deviation
    report, so `RunSpec` holds no regions and this asserts it stays that way.
    """
    result = _replay(tmp_path, "peek", "--region", FURNISHED)
    assert "as recorded" in result.output
    assert "declared differently" not in result.output


def test_declaring_the_furnished_region_reprices_the_recommendation(
    tmp_path: Path,
) -> None:
    """T27's controlled experiment, now runnable from the command line.

    One recording, replayed twice, one declaration different — so every
    difference is attributable to the declaration. Asserted as a direction
    rather than as two numbers: pinning a cassette's exact output is what
    broke four assertions across three re-records (HANDOFF, gate notes).
    """
    assert _replay(tmp_path, "undeclared").exit_code == 0
    assert _replay(tmp_path, "declared", "--region", FURNISHED).exit_code == 0

    undeclared = tmp_path / "undeclared" / "memo.md"
    declared = tmp_path / "declared" / "memo.md"

    # The filing declares half of itself furnished; declaring it says so.
    assert "low reliability" not in undeclared.read_text(encoding="utf-8")
    assert "low reliability" in declared.read_text(encoding="utf-8")

    # And the cap carries it up to the recommendation, which nobody told it to.
    assert _confidence(declared) < _confidence(undeclared)


# --------------------------------------------------------------------------
# T29 — the cassette supplies its own declarations
# --------------------------------------------------------------------------


def test_a_cassette_alone_is_enough(tmp_path: Path) -> None:
    """The point of recording the declarations: one argument, the right run."""
    result = runner.invoke(
        app,
        [
            "replay",
            "--cassette", str(CASSETTE_8K),
            "--runs-dir", str(tmp_path),
            "--run-id", "solo",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "solo" / "memo.md").exists()
    # It found the recorded source type rather than falling back to the default.
    assert "regulatory_filing" in result.output
    assert "as recorded" in result.output
    assert "no drift" in result.output


def test_a_multi_source_cassette_brings_its_extra_documents(tmp_path: Path) -> None:
    """Including the lineage, which is the declaration T26 turns on."""
    result = runner.invoke(
        app,
        [
            "replay",
            "--cassette", str(CASSETTES / "analyze_joint_pr_declared.json"),
            "--runs-dir", str(tmp_path),
            "--run-id", "pair",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "also source 2" in result.output
    assert "derives from doc_001" in result.output
    assert "as recorded" in result.output


def test_overriding_a_declaration_is_allowed_and_reported(tmp_path: Path) -> None:
    """Not refused — a weighting experiment costs nothing and changes no prompt.

    It is only dangerous unnoticed, so the deviation is printed and the run
    goes ahead.
    """
    result = _replay(tmp_path, "dev", "--source-type", "press_release")
    assert result.exit_code == 0, result.output
    assert "declared differently" in result.output
    assert "as recorded" not in result.output
    # And it really did take the override, not the recording.
    assert "low reliability" in (tmp_path / "dev" / "memo.md").read_text(
        encoding="utf-8"
    )


def test_a_cassette_with_no_declarations_still_needs_input(tmp_path: Path) -> None:
    """`RunSpec` is optional, so the explicit path must keep working.

    A cassette written before it existed — or by hand — has to be replayable,
    and must say plainly what it needs rather than falling back to a default
    source type nobody chose.
    """
    from spc_state.providers import Cassette

    stripped = tmp_path / "no_spec.json"
    Cassette.load(CASSETTE_8K).model_copy(update={"run_spec": None}).save(stripped)

    bare = runner.invoke(
        app,
        [
            "replay",
            "--cassette", str(stripped),
            "--runs-dir", str(tmp_path),
            "--run-id", "bare",
        ],
    )
    assert bare.exit_code != 0
    assert "--input is required" in bare.output or "records no declarations" in bare.output

    given = runner.invoke(
        app,
        [
            "replay",
            "--cassette", str(stripped),
            "--input", str(COMPLETE_8K),
            "--source-type", "regulatory_filing",
            "--question", QUESTION,
            "--runs-dir", str(tmp_path),
            "--run-id", "given",
        ],
    )
    assert given.exit_code == 0, given.output
    assert "cannot be checked" in given.output
