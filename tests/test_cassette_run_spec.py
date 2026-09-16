"""T29 — a cassette records how its run was *declared*, not just what it read.

A cassette has always pinned the documents it read (`document_sha256`), so
replaying it against the wrong material is refused. It pinned nothing about how
those documents were **declared** — and that is the more dangerous half.
`source_type` and `derives_from` are the caller's facts, which the model never
sees (T14), so they reach no prompt: replay a cassette with a different
`--source-type` and every recorded request still matches, giving zero drift, a
clean run, and a different memo. Nothing could catch it.

`RunSpec` closes that. The tests here hold two lines:

* **the recording is sufficient** — every committed cassette carries its
  declarations, and replays from them alone with no drift; and
* **the backfilled declarations are the right ones**, checked against
  *behaviour* rather than against the table that wrote them. A wrong
  `source_type` on `analyze_two_filings` would stop a claim reaching
  `VERIFIED`; a wrong `derives_from` on the joint-PR pair would let one
  document corroborate itself. Both are asserted below, so neither could be
  backfilled wrong and still pass.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

import pytest

from spc_state.analyze import SourceDocument, run_analysis
from spc_state.epistemics import Corroboration, corroboration_of
from spc_state.models import SemanticState
from spc_state.providers import Cassette, ReplayProvider, RunSpec, SourceSpec
from spc_state.runtime import FixedClock
from spc_state.source_types import coerce_source_type
from spc_state.store import RunPaths

CASSETTES = Path(__file__).parent / "fixtures" / "cassettes"
ALL_CASSETTES = sorted(p.name for p in CASSETTES.glob("*.json"))

#: The one cassette that deliberately never commits: recorded with
#: `max_tokens=90`, so all three extract attempts fail on truncated JSON.
NEVER_COMMITS = "analyze_truncated.json"


def _spec(name: str) -> RunSpec:
    spec = Cassette.load(CASSETTES / name).run_spec
    assert spec is not None, f"{name} records no declarations"
    return spec


def _replay_from_spec(name: str) -> tuple[ReplayProvider, SemanticState]:
    """Replay a cassette driven **only** by what it records about itself.

    This is the property that matters: a caller who knows nothing but the
    cassette's path gets the run that was captured.
    """
    spec = _spec(name)
    texts = [Path(s.path).read_text(encoding="utf-8") for s in spec.sources]
    provider = ReplayProvider.from_path(CASSETTES / name, documents=texts)
    clock = FixedClock(
        [dt.datetime(2026, 9, 16, tzinfo=dt.UTC) + dt.timedelta(seconds=i)
         for i in range(512)]
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = run_analysis(
            provider,
            texts[0],
            RunPaths(root=Path(tmp), run_id="spec_replay"),
            clock=clock,
            question=spec.question,
            source_type=coerce_source_type(spec.sources[0].source_type),
            extra_documents=[
                SourceDocument(
                    text=text,
                    source_type=coerce_source_type(source.source_type),
                    derives_from=source.derives_from,
                )
                for source, text in zip(spec.sources[1:], texts[1:], strict=True)
            ],
        )
    return provider, result.run.final_state


@pytest.mark.parametrize("name", ALL_CASSETTES)
def test_every_committed_cassette_records_its_declarations(name: str) -> None:
    """No cassette may be self-describing only by accident.

    Parametrized over what is on disk rather than a list, so a cassette added
    without a `RunSpec` fails here instead of being found later by someone
    whose memo came out wrong.
    """
    spec = _spec(name)
    assert spec.question.strip(), f"{name} records an empty question"
    assert spec.sources, f"{name} records no sources"
    for source in spec.sources:
        assert Path(source.path).exists(), f"{name}: {source.path} is missing"
        # Coercion, not equality: an unreadable source type would otherwise
        # sit in the cassette until a replay quietly weighed it as default.
        assert coerce_source_type(source.source_type).value == source.source_type

    # Only the extra documents can derive from anything; doc_001 is first.
    assert spec.sources[0].derives_from is None, (
        f"{name}: the primary document cannot derive from a later one"
    )


@pytest.mark.parametrize("name", ALL_CASSETTES)
def test_a_cassette_replays_from_its_own_declarations_without_drift(
    name: str,
) -> None:
    """The recorded declarations reproduce the recorded run.

    Drift is the check that the *question* and documents are right — both reach
    the request digest. It cannot check `source_type` or lineage, which is what
    the two behavioural tests below are for.
    """
    provider, final = _replay_from_spec(name)
    assert provider.drifted_calls == [], (
        f"{name} replays from its own declarations with drift at "
        f"{provider.drifted_calls} — the recorded declarations are not the "
        "ones it was recorded with, or the prompts have changed."
    )
    assert provider.exhausted, f"{name} left recorded exchanges unreplayed"
    if name != NEVER_COMMITS:
        assert final.state_version > 0, f"{name} committed nothing"


def test_the_two_filings_declaration_is_what_lets_a_claim_be_verified() -> None:
    """`analyze_two_filings` must be declared `regulatory_filing`, and is.

    Not checked against the table that backfilled it — checked against T19's
    rule. `VERIFIED` needs two independent sources, one of them *accountable*.
    Declare these two 8-Ks anything less and no claim can reach it, so this
    would fail if the backfill had guessed the source type.
    """
    spec = _spec("analyze_two_filings.json")
    assert [s.source_type for s in spec.sources] == [
        "regulatory_filing",
        "regulatory_filing",
    ]

    _, final = _replay_from_spec("analyze_two_filings.json")
    verified = [
        cid
        for cid, claim in final.claims.items()
        if corroboration_of(claim, final.evidence) is Corroboration.VERIFIED
    ]
    assert verified, (
        "no claim reached VERIFIED — the recorded source types cannot be right, "
        "since that is the pairing this cassette exists to demonstrate (T25)"
    )


def test_the_joint_pr_pair_differs_only_in_the_lineage_it_records() -> None:
    """The one declaration that separates T26's two runs, and its effect.

    The pair is the same joint press release filed by both counterparties. The
    `undeclared` cassette records both as independent; the `declared` one
    records WBD's copy as written off Netflix's. That single field is the
    difference between a reader being told these findings are *corroborated*
    and not, so it is asserted from the committed state rather than from the
    cassette alone.
    """
    undeclared = _spec("analyze_joint_pr_undeclared.json")
    declared = _spec("analyze_joint_pr_declared.json")

    assert [s.derives_from for s in undeclared.sources] == [None, None]
    assert [s.derives_from for s in declared.sources] == [None, "doc_001"]
    # Everything else about the two runs was declared identically.
    assert undeclared.question == declared.question
    assert [s.source_type for s in undeclared.sources] == [
        s.source_type for s in declared.sources
    ]

    _, off = _replay_from_spec("analyze_joint_pr_undeclared.json")
    _, on = _replay_from_spec("analyze_joint_pr_declared.json")

    def corroborated(state: SemanticState) -> list[str]:
        return [
            cid
            for cid, claim in state.claims.items()
            if corroboration_of(claim, state.evidence)
            is not Corroboration.UNCORROBORATED
        ]

    corroborated_off = corroborated(off)
    corroborated_on = corroborated(on)

    assert corroborated_off, (
        "the undeclared run corroborated nothing — then the recorded lineage "
        "cannot be what makes the pair differ (T26)"
    )
    assert not corroborated_on, (
        "the declared run still corroborates: one document counted twice, "
        "which is exactly what declaring the lineage exists to refuse"
    )


def test_a_changed_source_type_is_reported_as_a_deviation() -> None:
    """The defence against the failure mode `RunSpec` exists for.

    A caller who declares differently from the recording is told. Not refused:
    asking what the memo would say under a different weighting costs nothing
    and changes no prompt. It is only dangerous unnoticed.
    """
    spec = RunSpec(
        question="q",
        sources=[
            SourceSpec(path="a.txt", source_type="regulatory_filing"),
            SourceSpec(path="b.txt", source_type="press_release",
                       derives_from="doc_001"),
        ],
    )
    assert spec.deviations(
        question="q",
        source_types=["regulatory_filing", "press_release"],
        lineage=["doc_001"],
    ) == []

    found = spec.deviations(
        question="q",
        source_types=["press_release", "press_release"],
        lineage=[None],
    )
    assert len(found) == 2
    assert any("doc_001 source type" in line for line in found)
    assert any("doc_002 derives from" in line for line in found)


def test_a_deviating_question_says_it_only_moves_the_heading() -> None:
    """Honest about what the question does, which is less than it looks.

    `build_analysis_operators` does not take the question: no operator sees it.
    It is the heading on the memo and receipt, so a deviation there changes the
    rendered output and not one step of the analysis — and the report says so
    rather than implying the run was different.
    """
    spec = RunSpec(
        question="What did they agree?",
        sources=[SourceSpec(path="a.txt", source_type="unclassified")],
    )
    found = spec.deviations(
        question="Something else?", source_types=["unclassified"], lineage=[]
    )
    assert len(found) == 1
    assert "heading only" in found[0]


def test_a_mismatched_source_count_is_reported_and_stops_there() -> None:
    """Pairing declarations by index across different lengths invents a run."""
    spec = RunSpec(
        question="q", sources=[SourceSpec(path="a.txt", source_type="unclassified")]
    )
    found = spec.deviations(
        question="q", source_types=["unclassified", "press_release"], lineage=[None]
    )
    assert len(found) == 1
    assert "source count" in found[0]
