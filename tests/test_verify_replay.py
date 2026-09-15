"""T25 — the `VERIFIED` pairing, reproducible from a clean clone.

Everything T19–T23 claimed rested on `verify_001`: a live two-filing run whose
documents lived in a scratchpad and whose output lived in a gitignored `runs/`.
The numbers were real and nobody else could check them, which is an awkward
position for a project about traceable reasoning.

This replays the same pairing from committed material — two counterparties' Form
8-K Item 1.01 filings on one merger agreement (`tests/fixtures/SEC_SOURCES.md`),
against a recorded cassette. No key, no network, deterministic.

**What it does and does not restore.** The original run's exact claim set cannot
come back: it came from a non-deterministic model and was never recorded. What is
reproducible is the *behaviour* it demonstrated, which is what the tasks actually
claimed — and the whole arc shows up in one replay:

| | |
|---|---|
| T19/T20 | claims reach `VERIFIED` across two independent accountable sources |
| T20 | and still read `reported` — corroboration does not overwrite acquisition |
| T21 | nothing commits at 1.00 |
| T23 | a claim about a completed act outranks one about a future event |
"""

from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from spc_state.analyze import AnalysisResult, SourceDocument, run_analysis
from spc_state.epistemics import Corroboration, corroboration_of, source_lineage
from spc_state.modality import spans_are_unsettled
from spc_state.models import EpistemicStatus, Reliability, SemanticState
from spc_state.operators.calibration import GROUNDING_FACTOR, MODALITY_FACTOR
from spc_state.providers import ReplayProvider
from spc_state.runtime import FixedClock
from spc_state.store import RunPaths

FIXTURES = Path(__file__).parent / "fixtures"
CASSETTES = FIXTURES / "cassettes"
NETFLIX = FIXTURES / "sec_8k_netflix.txt"
WBD = FIXTURES / "sec_8k_wbd.txt"
CASSETTE = CASSETTES / "analyze_two_filings.json"
QUESTION = "What did Netflix and WBD agree, and on what terms?"


def _documents() -> tuple[str, str]:
    return (
        NETFLIX.read_text(encoding="utf-8"),
        WBD.read_text(encoding="utf-8"),
    )


@pytest.fixture(scope="module")
def replayed() -> Iterator[tuple[ReplayProvider, AnalysisResult]]:
    """One replay, shared: it is deterministic, so running it once is enough."""
    nflx, wbd = _documents()
    provider = ReplayProvider.from_path(CASSETTE, documents=[nflx, wbd])
    clock = FixedClock(
        [dt.datetime(2026, 9, 15, tzinfo=dt.UTC) + dt.timedelta(seconds=10 * i)
         for i in range(80)]
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = run_analysis(
            provider,
            nflx,
            RunPaths(root=Path(tmp), run_id="verify_replay"),
            clock=clock,
            question=QUESTION,
            source_type="regulatory_filing",
            extra_documents=[SourceDocument(text=wbd, source_type="regulatory_filing")],
        )
        yield provider, result


@pytest.fixture(scope="module")
def final(replayed: tuple[ReplayProvider, AnalysisResult]) -> SemanticState:
    return replayed[1].run.final_state


# ---------------------------------------------------------------------------
# the pairing itself
# ---------------------------------------------------------------------------


def test_the_run_reads_two_independent_accountable_sources(final: SemanticState) -> None:
    """The precondition everything below rests on.

    Two registrants, each `HIGH` because a filing is accountable, and no lineage
    between them — neither was written off the other. If this stops holding,
    every `VERIFIED` below is meaningless rather than merely absent.
    """
    assert sorted({e.source_id for e in final.evidence.values()}) == ["doc_001", "doc_002"]
    assert {e.reliability for e in final.evidence.values()} == {Reliability.HIGH}
    assert set(source_lineage(final.evidence).values()) == {None}


def test_claims_reach_verified(final: SemanticState) -> None:
    """The thing that had never happened on real data until this pairing."""
    verified = [
        cid for cid, c in final.claims.items()
        if corroboration_of(c, final.evidence) is Corroboration.VERIFIED
    ]
    assert verified, "no claim reached VERIFIED — the pairing no longer demonstrates it"


def test_corroboration_links_are_across_the_two_sources(final: SemanticState) -> None:
    links = [r for r in final.relations if r.predicate == "corroborates"]
    assert links, "VERIFIED without a corroboration link would be a derivation bug"

    def source_of(claim_id: str) -> str | None:
        claim = final.claims[claim_id]
        return next(
            (final.evidence[e].source_id for e in claim.supporting_evidence
             if e in final.evidence),
            None,
        )

    for link in links:
        assert source_of(link.source) != source_of(link.target), (
            f"{link.source} -> {link.target} links one document to itself"
        )


def test_a_verified_claim_is_still_reported(final: SemanticState) -> None:
    """T20's whole point, on real output.

    Before T20 the corroboration operator overwrote `REPORTED` with `VERIFIED`,
    trading a fact about how the claim was acquired for one about its support. It
    was read out of a document either way.
    """
    for cid, claim in final.claims.items():
        if corroboration_of(claim, final.evidence) is Corroboration.VERIFIED:
            assert claim.epistemic_status is EpistemicStatus.REPORTED, cid


# ---------------------------------------------------------------------------
# what the numbers are held to
# ---------------------------------------------------------------------------


def test_nothing_commits_at_certainty(final: SemanticState) -> None:
    """T21, against real model output rather than a hand-built claim."""
    certain = [cid for cid, c in final.claims.items() if c.confidence >= 1.0]
    assert certain == [], f"read out of a document and committed at 1.00: {certain}"
    assert all(h.confidence < 1.0 for h in final.hypotheses.values())


def test_a_completed_act_outranks_a_future_event(final: SemanticState) -> None:
    """T23, and the arithmetic that produced each side, derived not typed."""
    settled, unsettled = [], []
    for claim in final.claims.values():
        quotes = [
            final.evidence[e].quote_or_span
            for e in claim.supporting_evidence if e in final.evidence
        ]
        if not quotes:
            continue
        (unsettled if spans_are_unsettled(quotes) else settled).append(claim.confidence)

    assert settled and unsettled, (
        "this recording must contain both a completed act and a future event, "
        "or it cannot demonstrate the distinction"
    )
    assert min(settled) > max(unsettled)
    assert max(settled) == pytest.approx(GROUNDING_FACTOR[EpistemicStatus.REPORTED])
    assert max(unsettled) == pytest.approx(
        GROUNDING_FACTOR[EpistemicStatus.REPORTED] * MODALITY_FACTOR
    )


def test_the_recommendation_is_held_to_its_weakest_limb(
    final: SemanticState,
) -> None:
    """T15, still binding at the end of the chain."""
    for hypothesis in final.hypotheses.values():
        cited = [
            final.claims[cid].confidence
            for cid in hypothesis.supporting_claims
            if cid in final.claims
        ]
        if cited:
            assert hypothesis.confidence == pytest.approx(min(cited))


# ---------------------------------------------------------------------------
# keeping the recording honest
# ---------------------------------------------------------------------------


def test_the_cassette_matches_the_current_prompts(
    replayed: tuple[ReplayProvider, AnalysisResult],
) -> None:
    """Drift means someone changed a prompt without re-recording."""
    provider, _ = replayed
    assert provider.drifted_calls == [], (
        f"{CASSETTE.name} predates the current prompts — re-record it with "
        "tools/record_cassette.py (see the command in TASKS.md T25)"
    )


def test_the_cassette_is_pinned_to_both_filings() -> None:
    """A multi-source cassette must refuse either document being swapped."""
    from spc_state.providers.cassette import CassetteError

    nflx, wbd = _documents()
    ReplayProvider.from_path(CASSETTE, documents=[nflx, wbd])
    for swapped in ([nflx + " tampered", wbd], [nflx, wbd + " tampered"], [wbd, nflx]):
        with pytest.raises(CassetteError, match="recorded against different"):
            ReplayProvider.from_path(CASSETTE, documents=swapped)


def test_every_committed_cassette_is_exercised_by_a_test() -> None:
    """A cassette nobody replays is a recording that can rot unnoticed.

    The same gap T24 closed for `schemas/`: the cassettes are enumerated by hand
    in the replay tests, so one added without being registered would be checked
    by nothing. Adding a cassette must mean adding it to a test.
    """
    covered = {
        "analyze_five_stage.json",
        "analyze_hyphenated.json",
        # both replayed by test_lineage_replay.py
        "analyze_joint_pr_declared.json",
        "analyze_joint_pr_undeclared.json",
        "analyze_retry_path.json",
        "analyze_truncated.json",
        CASSETTE.name,
    }
    on_disk = {p.name for p in CASSETTES.glob("*.json")}
    assert on_disk == covered, (
        f"unexercised: {sorted(on_disk - covered)}; missing from disk: "
        f"{sorted(covered - on_disk)}"
    )
