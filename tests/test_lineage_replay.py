"""T26 — the lineage gate, reproducible from a clean clone.

T20 gave corroboration a bar it was missing: two sources only count as two when
neither was written off the other. The evidence that the bar *works* was a pair
of live runs, `lineage_off` and `lineage_on`, whose documents lived in a
scratchpad and whose output lived in a gitignored `runs/` — the same position
T25 found `verify_001` in, and for the same reason nobody could check it.

This replays that pair from committed material. The documents are the **one
joint press release** Netflix and WBD each filed as their own Exhibit 99.1
(`tests/fixtures/SEC_SOURCES.md`): two `source_id`s, two accession numbers, one
document. Every corroboration between them is false by construction, which is
what makes the pair worth keeping.

The runs differ in exactly one input — whether the caller declares that WBD's
copy derives from Netflix's — and that difference is the whole test:

| | |
|---|---|
| undeclared | the pipeline commits corroboration links, and a reader's memo says `corroborated` |
| declared | no link survives, and every claim reads `uncorroborated` |
| T20 | the model proposed those pairs in **both** runs; the operator refused them in one |
| T20 | neither run reaches `VERIFIED` — two interested parties are not an accountable source |

**Two recordings, not one.** Lineage changes no prompt, so the extraction and
the first corroboration request are identical in both runs. It changes what
commits, and from there the runs genuinely diverge — the planner in the
undeclared run reads a state carrying ten corroboration links. A single cassette
cannot cover both, and pretending otherwise would replay one run's model output
against the other's state.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from spc_state.analyze import AnalysisResult, SourceDocument, run_analysis
from spc_state.epistemics import Corroboration, corroboration_of, source_lineage
from spc_state.models import EpistemicStatus, Reliability, SemanticState
from spc_state.providers import ReplayProvider
from spc_state.runtime import FixedClock
from spc_state.store import RunPaths

FIXTURES = Path(__file__).parent / "fixtures"
CASSETTES = FIXTURES / "cassettes"
AS_FILED_BY_NETFLIX = FIXTURES / "joint_pr_netflix.txt"
AS_FILED_BY_WBD = FIXTURES / "joint_pr_wbd.txt"
UNDECLARED = CASSETTES / "analyze_joint_pr_undeclared.json"
DECLARED = CASSETTES / "analyze_joint_pr_declared.json"
QUESTION = "What did Netflix and WBD announce, and on what terms?"


@dataclass(frozen=True)
class Replay:
    """One replayed run, plus the artifact a reader would actually open."""

    provider: ReplayProvider
    result: AnalysisResult
    memo: str

    @property
    def final(self) -> SemanticState:
        return self.result.run.final_state

    @property
    def links(self) -> list[str]:
        return [
            r.id for r in self.final.relations if r.predicate == "corroborates"
        ]

    def claims_reading(self, support: Corroboration) -> list[str]:
        return [
            cid
            for cid, claim in self.final.claims.items()
            if corroboration_of(claim, self.final.evidence) is support
        ]


def _documents() -> tuple[str, str]:
    return (
        AS_FILED_BY_NETFLIX.read_text(encoding="utf-8"),
        AS_FILED_BY_WBD.read_text(encoding="utf-8"),
    )


def _replay(cassette: Path, *, derives_from: str | None) -> Replay:
    """Run the pipeline over the pair, with lineage declared or not."""
    netflix, wbd = _documents()
    provider = ReplayProvider.from_path(cassette, documents=[netflix, wbd])
    clock = FixedClock(
        [dt.datetime(2026, 9, 15, tzinfo=dt.UTC) + dt.timedelta(seconds=10 * i)
         for i in range(120)]
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = run_analysis(
            provider,
            netflix,
            RunPaths(root=Path(tmp), run_id=cassette.stem),
            clock=clock,
            question=QUESTION,
            source_type="press_release",
            extra_documents=[
                SourceDocument(
                    text=wbd, source_type="press_release", derives_from=derives_from
                )
            ],
        )
        # Read inside the context: the memo is projected onto disk, and the
        # directory goes with the block.
        memo = (
            Path(result.memo_path).read_text(encoding="utf-8")
            if result.memo_path is not None
            else ""
        )
    return Replay(provider=provider, result=result, memo=memo)


@pytest.fixture(scope="module")
def undeclared() -> Iterator[Replay]:
    """The generous default: nobody said where the second copy came from."""
    yield _replay(UNDECLARED, derives_from=None)


@pytest.fixture(scope="module")
def declared() -> Iterator[Replay]:
    """The same pair, with one honest `--also-derives-from doc_001`."""
    yield _replay(DECLARED, derives_from="doc_001")


# ---------------------------------------------------------------------------
# the precondition: this is one document wearing two hats
# ---------------------------------------------------------------------------


def test_the_two_documents_are_one_press_release() -> None:
    """What makes every corroboration between this pair false.

    Netflix and WBD each filed the same joint release as their own Exhibit 99.1.
    The two files are not byte-identical — each filer's HTML wraps the headline
    differently, and the fixtures keep that — but the words are the same words.
    If this ever stops holding, the pair stops demonstrating anything and the
    runs below are measuring an ordinary disagreement between two sources.
    """
    def squashed(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    netflix, wbd = _documents()
    assert netflix != wbd, "the fixtures should keep each filer's own rendering"
    assert squashed(netflix) == squashed(wbd)


def test_neither_source_is_accountable(undeclared: Replay) -> None:
    """Both copies are declared `press_release`, so every span is `LOW`.

    A press release is written by a party with a stake in the conclusion (T14).
    This is why nothing below reaches `VERIFIED` even when corroboration fires.
    """
    final = undeclared.final
    assert sorted({e.source_id for e in final.evidence.values()}) == [
        "doc_001",
        "doc_002",
    ]
    assert {e.reliability for e in final.evidence.values()} == {Reliability.LOW}


# ---------------------------------------------------------------------------
# the contrast, which is the whole test
# ---------------------------------------------------------------------------


def test_undeclared_lineage_manufactures_corroboration(undeclared: Replay) -> None:
    """The defect, on real output: one source counted as two.

    Nothing here is a bug in the pipeline — undeclared lineage counts as
    independent on purpose (`spc_state.epistemics`), because "we do not know
    where this came from" is not "we know it is derivative". It is the cost of
    that generous default, and the reason the declaration has to exist.
    """
    assert undeclared.links, (
        "the pair no longer produces the false corroborations it exists to show"
    )
    assert undeclared.claims_reading(Corroboration.CORROBORATED)
    assert set(source_lineage(undeclared.final.evidence).values()) == {None}


def test_declaring_the_lineage_removes_every_corroboration(declared: Replay) -> None:
    """One honest declaration, and the whole false picture goes."""
    assert source_lineage(declared.final.evidence) == {
        "doc_001": None,
        "doc_002": "doc_001",
    }
    assert declared.links == []
    assert declared.claims_reading(Corroboration.CORROBORATED) == []
    assert declared.claims_reading(Corroboration.VERIFIED) == []
    assert declared.claims_reading(Corroboration.UNCORROBORATED) == sorted(
        declared.final.claims
    )


def test_the_declared_run_still_holds_the_same_claims(declared: Replay) -> None:
    """Lineage removes the *link*, not the reading.

    Both documents are still extracted, and both still say the same things —
    what the declaration denies is that saying it twice is evidence.
    """
    sources = {
        e.source_id
        for claim in declared.final.claims.values()
        for eid in claim.supporting_evidence
        if (e := declared.final.evidence.get(eid)) is not None
    }
    assert sources == {"doc_001", "doc_002"}


# ---------------------------------------------------------------------------
# whose refusal it is
# ---------------------------------------------------------------------------


def _proposed_pairs(cassette: Path) -> list[dict[str, str]]:
    """The corroborations the model offered, read back out of the recording."""
    recorded = json.loads(cassette.read_text(encoding="utf-8"))
    for exchange in recorded["exchanges"]:
        try:
            payload = json.loads(exchange["response_text"])
        except ValueError:
            continue
        if isinstance(payload, dict) and "corroborations" in payload:
            return list(payload["corroborations"])
    raise AssertionError(f"{cassette.name} records no corroboration pass")


def test_the_model_proposed_the_pairs_the_operator_refused() -> None:
    """The rule is the operator's, not the model's — and the recording proves it.

    The model sees two documents saying the same thing and pairs them, in both
    runs; it cannot do otherwise, because whether one document was written off
    another is a fact about the world outside both of them (T14). The declared
    run's cassette holds those proposals and its committed state holds none of
    them, so the refusal is `_candidates` reading the caller's lineage.
    """
    assert _proposed_pairs(DECLARED), (
        "the declared run must have been offered corroborations, or it shows "
        "only that the model happened to propose nothing"
    )


def test_the_gate_runs_before_the_second_model_call(
    undeclared: Replay, declared: Replay
) -> None:
    """Refusing costs nothing: the skeptic pass never happens.

    `LLMCorroborationOperator` drops non-independent pairs in `_candidates`,
    before the verification pass it would otherwise pay for — so the declared
    run makes one model call fewer over identical documents.
    """
    assert declared.provider.call_count == undeclared.provider.call_count - 1
    assert undeclared.provider.exhausted and declared.provider.exhausted


# ---------------------------------------------------------------------------
# what the false corroboration could and could not buy
# ---------------------------------------------------------------------------


def test_two_interested_parties_never_reach_verified(undeclared: Replay) -> None:
    """T20's second bar, holding where the first one failed.

    Even with ten false links committed, no claim reaches `VERIFIED`:
    corroboration across two parties with a stake in the conclusion is
    corroboration, not verification. The lineage gate is one of two things
    standing between this run and a warrant it never earned.
    """
    assert undeclared.claims_reading(Corroboration.VERIFIED) == []


def test_a_corroborated_claim_is_still_reported(undeclared: Replay) -> None:
    """T20: support is a second axis, and it does not overwrite the first."""
    for cid in undeclared.claims_reading(Corroboration.CORROBORATED):
        assert undeclared.final.claims[cid].epistemic_status is EpistemicStatus.REPORTED


def test_nothing_commits_at_certainty(undeclared: Replay, declared: Replay) -> None:
    """T21, and T14's cap under it — a press release buys no certainty."""
    for replay in (undeclared, declared):
        assert all(c.confidence < 1.0 for c in replay.final.claims.values())
        assert all(h.confidence < 1.0 for h in replay.final.hypotheses.values())


def test_the_word_reaches_the_reader(undeclared: Replay, declared: Replay) -> None:
    """Why this matters outside the state graph.

    The memo is the artifact a stakeholder opens, and in the undeclared run it
    tells them findings are corroborated when one press release is all there is.
    """
    assert "corroborated" in undeclared.memo
    assert "corroborated" not in declared.memo


# ---------------------------------------------------------------------------
# keeping the recordings honest
# ---------------------------------------------------------------------------


def test_the_cassettes_match_the_current_prompts(
    undeclared: Replay, declared: Replay
) -> None:
    """Drift means someone changed a prompt without re-recording."""
    for cassette, replay in ((UNDECLARED, undeclared), (DECLARED, declared)):
        assert replay.provider.drifted_calls == [], (
            f"{cassette.name} predates the current prompts — re-record it with "
            "tools/record_cassette.py (see the commands in TASKS.md T26)"
        )


def test_the_cassettes_are_pinned_to_both_filings() -> None:
    """Neither copy may be swapped for the other's, or for anything else."""
    from spc_state.providers.cassette import CassetteError

    netflix, wbd = _documents()
    for cassette in (UNDECLARED, DECLARED):
        ReplayProvider.from_path(cassette, documents=[netflix, wbd])
        for swapped in (
            [netflix + " tampered", wbd],
            [netflix, wbd + " tampered"],
            [wbd, netflix],
        ):
            with pytest.raises(CassetteError, match="recorded against different"):
                ReplayProvider.from_path(cassette, documents=swapped)
