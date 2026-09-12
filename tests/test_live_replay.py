"""T9 — the live-run regression harness: replay real model output offline.

Every other LLM-path test drives the pipeline with hand-written payloads that
are, by construction, already well-formed. This one replays a cassette of
*genuine* `deepseek/deepseek-chat` completions captured from a real five-stage
`analyze` run — markdown habits, typographic quotes, terminal periods added to
bullets and all — with no key and no network.

The T8 provenance defect is the worked example of why this exists: it was
invisible to mock-driven tests and obvious the first time a real document went
through. `test_every_committed_quote_locates_in_the_document` is the guard
that would have caught it.

Four cassettes, because a harness that only ever records success proves only
that the happy path works:

- `analyze_five_stage.json` — a clean run, every stage committing first time.
- `analyze_hyphenated.json` — a document hyphenated at line ends, the way PDF
  extraction of justified text is. The model de-hyphenates when it quotes;
  `locate_span` reads such a hyphen both ways, so every span still resolves.
  Before that rule existed this same document cost half its claims.
- `analyze_retry_path.json` — a real failure and recovery, and the **boundary**
  of that leniency. A German filing carries an in-word hyphen with no line
  break ("ausserplan-maessige"), which the model quotes joined. Dropping a
  hyphen that is part of a word is an alteration, not a transport artifact, so
  it is refused and the extractor retries.
- `analyze_truncated.json` — a failure that never recovers. Recorded with a low
  token cap, so the reply is cut off mid-string: truncation is the commonest
  real cause of output the JSON_DECODE retry path exists for. All three extract
  attempts fail, that step commits nothing, and the run carries on to project a
  memo from empty state.

Re-record either with `tools/record_cassette.py` (see that script's docstring).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spc_state.analyze import run_analysis
from spc_state.provenance import locate_span
from spc_state.providers import (
    Cassette,
    CassetteError,
    MockProvider,
    ProviderRequest,
    RecordingProvider,
    ReplayProvider,
)
from spc_state.runtime import FixedClock
from spc_state.store import RunPaths

FIXTURES = Path(__file__).parent / "fixtures"
DOCUMENT_PATH = FIXTURES / "live_document.txt"
CASSETTE_PATH = FIXTURES / "cassettes" / "analyze_five_stage.json"

HYPHEN_DOCUMENT_PATH = FIXTURES / "live_document_hyphenated.txt"
HYPHEN_CASSETTE_PATH = FIXTURES / "cassettes" / "analyze_hyphenated.json"

RETRY_DOCUMENT_PATH = FIXTURES / "live_document_german.txt"
RETRY_CASSETTE_PATH = FIXTURES / "cassettes" / "analyze_retry_path.json"

# Recorded from the same document as the five-stage cassette, so the token cap
# that truncated it is the only variable between them.
TRUNCATED_CASSETTE_PATH = FIXTURES / "cassettes" / "analyze_truncated.json"

QUESTION = "What does this announcement establish, and what is uncertain?"


@pytest.fixture
def document() -> str:
    return DOCUMENT_PATH.read_text(encoding="utf-8")


@pytest.fixture
def retry_document() -> str:
    return RETRY_DOCUMENT_PATH.read_text(encoding="utf-8")


@pytest.fixture
def hyphen_document() -> str:
    return HYPHEN_DOCUMENT_PATH.read_text(encoding="utf-8")


def _clock() -> FixedClock:
    start = dt.datetime(2026, 9, 10, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(40)])


def _replay(
    tmp_path: Path,
    document: str,
    run_id: str = "replay",
    cassette: Path = CASSETTE_PATH,
):
    """Run the real five-stage pipeline against the recorded completions."""
    provider = ReplayProvider.from_path(cassette, document=document)
    paths = RunPaths(root=tmp_path, run_id=run_id)
    result = run_analysis(
        provider, document, paths, clock=_clock(), question=QUESTION
    )
    return provider, paths, result


# ---------------------------------------------------------------------------
# the harness itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cassette_path", "document_path"),
    [
        (CASSETTE_PATH, DOCUMENT_PATH),
        (HYPHEN_CASSETTE_PATH, HYPHEN_DOCUMENT_PATH),
        (RETRY_CASSETTE_PATH, RETRY_DOCUMENT_PATH),
        (TRUNCATED_CASSETTE_PATH, DOCUMENT_PATH),
    ],
    ids=["five_stage", "hyphenated", "retry_path", "truncated"],
)
def test_cassette_is_recorded_from_its_document(
    cassette_path: Path, document_path: Path
) -> None:
    """A cassette replayed against the wrong document is a confusing failure."""
    text = document_path.read_text(encoding="utf-8")
    cassette = Cassette.load(cassette_path)
    assert cassette.exchanges, "the committed cassette must hold real exchanges"
    # from_path verifies the digest; a different document must be refused.
    ReplayProvider.from_path(cassette_path, document=text)
    with pytest.raises(CassetteError, match="different document"):
        ReplayProvider.from_path(cassette_path, document=text + " tampered")


def test_real_model_output_drives_all_six_stages(tmp_path: Path, document: str) -> None:
    """The end-to-end guard: genuine completions still commit every stage."""
    provider, _, result = _replay(tmp_path, document)

    committed = [s for s in result.run.steps if s.next_state is not None]
    assert len(committed) == 6, (
        "extract -> plan -> critique -> retrieve -> verify -> calibrate"
    )
    assert result.run.final_state.state_version == 6
    assert provider.exhausted, "every recorded exchange should have been consumed"

    final = result.run.final_state
    assert final.claims and final.evidence and final.questions
    assert result.memo_path is not None and result.memo_path.exists()
    assert result.artifacts is not None and result.artifacts.receipt_path.exists()


def test_every_committed_quote_locates_in_the_document(
    tmp_path: Path, document: str
) -> None:
    """T8, held against real output — the regression this harness exists for.

    A hand-written mock payload cannot prove the normalization is neither too
    strict (rejecting faithful quotes) nor too loose (admitting invented ones);
    only a real model's quoting habits can.
    """
    _, _, result = _replay(tmp_path, document)
    evidence = result.run.final_state.evidence
    assert evidence, "the extraction must have committed citations to check"

    for eid, item in sorted(evidence.items()):
        match = locate_span(item.quote_or_span, document)
        assert match is not None, f"{eid} cites a span that is not in the document"
        # The recorded offsets must resolve, not merely exist.
        start, end = item.location["start"], item.location["end"]
        assert isinstance(start, int) and isinstance(end, int)
        assert locate_span(document[start:end], document) is not None


def test_normalization_is_load_bearing_on_real_output(
    tmp_path: Path, document: str
) -> None:
    """Guards the T8 design decision, not just its outcome.

    If every real quote were byte-exact, the normalization would be untested
    dead weight and a naive `quote in document` check would do. It is not: real
    output routinely differs in whitespace, quote characters or trailing
    punctuation, which is exactly why exact matching was rejected.
    """
    _, _, result = _replay(tmp_path, document)
    quotes = [e.quote_or_span for e in result.run.final_state.evidence.values()]
    assert quotes

    inexact = [q for q in quotes if q not in document]
    assert inexact, (
        "no recorded quote needed normalization — re-record against a document "
        "whose formatting a model actually alters, or this guard proves nothing"
    )


def test_replay_is_deterministic(tmp_path: Path, document: str) -> None:
    """Same cassette, same committed state — the harness must not drift itself."""
    _, _, first = _replay(tmp_path / "a", document, run_id="first")
    _, _, second = _replay(tmp_path / "b", document, run_id="second")
    assert first.run.final_state.model_dump_json(
        by_alias=True
    ) == second.run.final_state.model_dump_json(by_alias=True)


def test_memo_citations_resolve(tmp_path: Path, document: str) -> None:
    """The projected memo must not cite evidence the state does not hold."""
    _, _, result = _replay(tmp_path, document)
    assert result.memo_path is not None
    memo = result.memo_path.read_text(encoding="utf-8")
    for eid, item in result.run.final_state.evidence.items():
        assert item.quote_or_span[:40] in memo, f"{eid} is missing from the memo sources"


def test_cost_ledger_counts_the_recorded_usage(tmp_path: Path, document: str) -> None:
    """Replay carries the recorded token usage, so T5 accounting stays exercised."""
    _, _, result = _replay(tmp_path, document)
    ledger = result.cost_ledger
    assert ledger is not None
    assert ledger.total_tokens > 0
    assert all(e.total_tokens > 0 for e in ledger.entries)


# ---------------------------------------------------------------------------
# hyphenation: the artifact that once cost half a document's claims
# ---------------------------------------------------------------------------


def _replay_hyphenated(tmp_path: Path, document: str, run_id: str = "hyphen"):
    return _replay(tmp_path, document, run_id=run_id, cassette=HYPHEN_CASSETTE_PATH)


def test_line_end_hyphenation_no_longer_costs_claims(
    tmp_path: Path, hyphen_document: str
) -> None:
    """The soft-hyphen rule, measured on real output rather than asserted.

    This document is hyphenated at line ends the way PDF extraction of
    justified text is. Before `locate_span` read such a hyphen both ways, a
    recorded run over it proposed 10 claims, was rejected twice, and committed
    5. Now the extraction commits first time with nothing dropped.
    """
    provider, _, result = _replay_hyphenated(tmp_path, hyphen_document)

    extract = result.run.steps[0]
    assert extract.attempts == 1, "no retry: every span resolves on the first pass"
    assert result.run.final_state.state_version == 6
    assert provider.exhausted

    proposed = json.loads(
        Cassette.load(HYPHEN_CASSETTE_PATH).exchanges[0].response_text
    )["claims"]
    assert len(result.run.final_state.claims) == len(proposed), (
        "every proposed claim should survive — none lost to hyphenation"
    )


def test_dehyphenated_quotes_resolve_to_the_hyphenated_source(
    tmp_path: Path, hyphen_document: str
) -> None:
    """The rule is load-bearing here, and the offsets still point at real text.

    At least one committed quote must differ from the document by exactly the
    hyphenation — otherwise this fixture is not exercising the rule at all, and
    the guard above would pass for the wrong reason.
    """
    _, _, result = _replay_hyphenated(tmp_path, hyphen_document)
    evidence = list(result.run.final_state.evidence.values())
    assert evidence

    dehyphenated = 0
    for item in evidence:
        assert locate_span(item.quote_or_span, hyphen_document) is not None
        start, end = item.location["start"], item.location["end"]
        span = hyphen_document[int(start) : int(end)]
        # The recorded span is the *document's* text, hyphen and line break intact.
        if "-\n" in span:
            dehyphenated += 1
            assert "-\n" not in item.quote_or_span, "the model quoted it joined"

    assert dehyphenated, (
        "no committed quote spans a line-end hyphen — re-record against a "
        "document whose hyphenation a model actually joins, or this proves nothing"
    )


# ---------------------------------------------------------------------------
# the failure path: real rejection, real repair
# ---------------------------------------------------------------------------


def _replay_retry(tmp_path: Path, document: str, run_id: str = "retry"):
    return _replay(tmp_path, document, run_id=run_id, cassette=RETRY_CASSETTE_PATH)


def test_in_word_hyphen_is_not_forgiven(tmp_path: Path, retry_document: str) -> None:
    """The boundary of the soft-hyphen rule, on output a model really produced.

    A hyphen against a line break is a transport artifact and is read both ways.
    A hyphen inside a word on a single line is part of the word: quoting
    "ausserplanmaessige" for "ausserplan-maessige" drops a character the source
    contains, so it is refused — and the model, told which span failed, quotes
    it correctly on the retry.
    """
    provider, _, result = _replay_retry(tmp_path, retry_document)

    extract = result.run.steps[0]
    assert extract.attempts == 2, "one rejected attempt, then one that committed"
    assert extract.next_state is not None
    assert result.run.final_state.state_version == 6
    assert provider.exhausted

    # The offending span really is present in the first attempt and gone after.
    first = json.loads(
        Cassette.load(RETRY_CASSETTE_PATH).exchanges[0].response_text
    )["claims"]
    rejected = [
        c["evidence_quote"]
        for c in first
        if locate_span(c["evidence_quote"], retry_document) is None
    ]
    assert rejected, "attempt 1 must really have contained an unlocatable span"
    committed = {e.quote_or_span for e in result.run.final_state.evidence.values()}
    assert not (committed & set(rejected))


def test_rejected_attempt_stays_on_the_record(
    tmp_path: Path, retry_document: str
) -> None:
    """A rejected proposal is evidence of how the state got here (AGENTS.md III)."""
    _, paths, _ = _replay_retry(tmp_path, retry_document)
    attempts = sorted(p.name for p in paths.patches_dir.glob("attempt_001_*.txt"))
    assert attempts == ["attempt_001_01.txt", "attempt_001_02.txt"]
    assert "ausserplanmaessige" in paths.patch_attempt_file(1, 1).read_text(
        encoding="utf-8"
    ), "the model's joined spelling is preserved verbatim, not erased"


def test_the_repair_hint_named_a_real_unlocatable_span(
    tmp_path: Path, retry_document: str
) -> None:
    """What the model was actually told, on output it actually produced."""
    _, paths, _ = _replay_retry(tmp_path, retry_document)
    audit = (paths.audit_dir / "audit_log.jsonl").read_text(encoding="utf-8")
    retries = [
        json.loads(line)
        for line in audit.splitlines()
        if json.loads(line)["event"] == "patch.retry"
    ]
    assert len(retries) == 1
    assert "do not appear in the document" in retries[0]["repair_hint"]


def test_every_retry_attempt_is_billed(tmp_path: Path, retry_document: str) -> None:
    """T5: a retry is a real call. Both attempts must reach the ledger."""
    _, _, result = _replay_retry(tmp_path, retry_document)
    ledger = result.cost_ledger
    assert ledger is not None
    extract = next(e for e in ledger.entries if e.operator == "llm_extract_transform")

    recorded = Cassette.load(RETRY_CASSETTE_PATH).exchanges[:2]
    expected = sum(
        (x.usage.prompt_tokens + x.usage.completion_tokens)
        for x in recorded
        if x.usage is not None
    )
    assert extract.total_tokens == expected


# ---------------------------------------------------------------------------
# output that never parses: a failure with no recovery
# ---------------------------------------------------------------------------


def _replay_truncated(tmp_path: Path, document: str, run_id: str = "truncated"):
    return _replay(tmp_path, document, run_id=run_id, cassette=TRUNCATED_CASSETTE_PATH)


def test_the_recorded_replies_really_are_unparseable(document: str) -> None:
    """Guards the fixture itself, not the code.

    If a re-record ever captured parseable output here, every test below would
    pass while proving nothing. The three extract attempts must genuinely fail
    to parse.
    """
    attempts = Cassette.load(TRUNCATED_CASSETTE_PATH).exchanges[:3]
    assert len(attempts) == 3
    for exchange in attempts:
        with pytest.raises(json.JSONDecodeError):
            json.loads(exchange.response_text)


def test_unparseable_output_exhausts_the_retries_and_commits_nothing(
    tmp_path: Path, document: str
) -> None:
    """The JSON_DECODE path on real output, driven to the end of its rope.

    Mock payloads cover prose that cannot parse. This is a model's own reply,
    cut off mid-string by the token cap — the commonest way real output fails
    to parse — and it fails all three times.
    """
    provider, _, result = _replay_truncated(tmp_path, document)

    extract = result.run.steps[0]
    assert extract.attempts == 3, "every attempt was spent"
    assert extract.next_state is None, "the step committed nothing"
    assert extract.patch is None, "no attempt even parsed into a patch"

    final = result.run.final_state
    assert final.claims == {} and final.evidence == {}
    assert provider.exhausted


def test_the_run_survives_an_extraction_that_never_committed(
    tmp_path: Path, document: str
) -> None:
    """A failed first stage must not take the run down with it.

    The later operators still run, against empty state, and commit — so the
    final version reflects five committed steps rather than six.
    """
    _, _, result = _replay_truncated(tmp_path, document)
    committed = [s for s in result.run.steps if s.next_state is not None]
    assert len(committed) == 5, "everything except the extraction committed"
    assert result.run.final_state.state_version == 5


def test_the_memo_invents_no_findings_from_an_empty_state(
    tmp_path: Path, document: str
) -> None:
    """What the *code* guarantees when the extraction produced nothing.

    The writer projects only what state holds, so with no claims and no
    evidence it must render neither — and say so — rather than filling the
    sections from anywhere else. These strings all come from `memo.py`.
    """
    _, _, result = _replay_truncated(tmp_path, document)
    assert result.memo_path is not None
    memo = result.memo_path.read_text(encoding="utf-8")

    assert "0 claims, 0 evidence spans" in memo
    assert "- _No claims were extracted._" in memo
    assert "- _No evidence spans were recorded._" in memo
    # No citation can appear when no evidence exists.
    assert "[E1]" not in memo


def test_the_recorded_planner_hedged_rather_than_inventing_a_recommendation(
    tmp_path: Path, document: str
) -> None:
    """What the *model* did, which is a separate thing and worth pinning apart.

    Handed an empty state, the planner proposed "no recommended course of
    action due to insufficient information" at zero confidence. That hedge is
    the model's, not a guarantee of this code: the recommendation line renders
    whatever hypothesis was committed. Pinned so that a re-record which starts
    asserting something confident out of nothing is visible rather than
    silently shipped in a memo.

    The *shape* of the hedge is asserted, not its wording. Three recordings have
    now said "insufficient data", "insufficient information", and "lack of
    claims and assumptions"; a test that fails on the synonym is pinning the
    model's prose style rather than its refusal to invent, and has broken twice
    doing so. What must hold is that it named a shortfall and staked nothing on
    it.
    """
    _, _, result = _replay_truncated(tmp_path, document)
    memo = result.memo_path.read_text(encoding="utf-8") if result.memo_path else ""

    lead = max(result.run.final_state.hypotheses.values(), key=lambda h: h.confidence)
    assert lead.confidence == 0.0
    assert lead.supporting_claims == []
    assert any(
        word in lead.text.lower()
        for word in ("insufficient", "lack", "no recommended", "cannot", "unable")
    ), "the planner named a shortfall rather than recommending something"
    assert "_Confidence: 0%._" in memo


def test_three_billed_attempts_are_counted_even_though_nothing_committed(
    tmp_path: Path, document: str
) -> None:
    """T13 on real money: the extraction's three failed calls are in the ledger.

    Until T13 the ledger held one row per `TransformRecord`, so a step that
    never committed produced none and its spend vanished — this run reported
    the cost of the other four steps and called it the total. The row now
    exists, is marked uncommitted, and matches the usage recorded in the
    cassette exactly.
    """
    _, _, result = _replay_truncated(tmp_path, document)
    ledger = result.cost_ledger
    assert ledger is not None

    extract = next(e for e in ledger.entries if e.operator == "llm_extract_transform")
    assert extract.committed is False
    assert extract.transform_id is None, "nothing committed, so nothing to name"
    assert extract.attempts == 3

    spent = sum(
        x.usage.prompt_tokens + x.usage.completion_tokens
        for x in Cassette.load(TRUNCATED_CASSETTE_PATH).exchanges[:3]
        if x.usage is not None
    )
    assert spent > 0, "the attempts really did cost tokens"
    assert extract.total_tokens == spent, "counted to the token, not approximated"

    # The run's total now includes money that bought nothing, and says how much.
    assert ledger.uncommitted_tokens == spent
    assert ledger.total_tokens > ledger.uncommitted_tokens > 0


def test_committed_and_uncommitted_spend_stay_separable(
    tmp_path: Path, document: str
) -> None:
    """Counting failed calls must not blur what the committed state cost.

    Reconciling against a provider invoice wants every row; attributing cost to
    the state that exists wants only the committed ones. Both have to be
    answerable from the same ledger.
    """
    _, _, result = _replay_truncated(tmp_path, document)
    ledger = result.cost_ledger
    assert ledger is not None

    committed = [e for e in ledger.entries if e.committed]
    uncommitted = [e for e in ledger.entries if not e.committed]
    assert committed and uncommitted, "this run has both kinds"
    assert all(e.transform_id is not None for e in committed)

    assert ledger.total_tokens == sum(e.total_tokens for e in ledger.entries)
    assert ledger.uncommitted_tokens == sum(e.total_tokens for e in uncommitted)
    assert ledger.uncommitted_estimated_cost_usd > 0.0
    assert ledger.total_estimated_cost_usd > ledger.uncommitted_estimated_cost_usd


# ---------------------------------------------------------------------------
# cassette mechanics
# ---------------------------------------------------------------------------


def test_exhausted_cassette_raises_rather_than_repeating(document: str) -> None:
    """An extra provider call is a real change; a stale repeat would hide it."""
    provider = ReplayProvider.from_path(CASSETTE_PATH, document=document)
    for _ in provider.cassette.exchanges:
        provider.complete(ProviderRequest(user="anything"))
    assert provider.exhausted
    with pytest.raises(CassetteError, match="exhausted"):
        provider.complete(ProviderRequest(user="one too many"))


def test_drift_is_reported_but_not_fatal(document: str) -> None:
    """A changed prompt makes a cassette stale, not unusable.

    Fatal drift would break the suite for every contributor without an API key,
    who cannot re-record.
    """
    provider = ReplayProvider.from_path(CASSETTE_PATH, document=document)
    response = provider.complete(ProviderRequest(user="not the recorded prompt"))
    assert response.text == provider.cassette.exchanges[0].response_text
    assert provider.drifted_calls == [0]


@pytest.mark.parametrize(
    ("cassette_path", "document_path"),
    [
        (CASSETTE_PATH, DOCUMENT_PATH),
        (HYPHEN_CASSETTE_PATH, HYPHEN_DOCUMENT_PATH),
        (RETRY_CASSETTE_PATH, RETRY_DOCUMENT_PATH),
        (TRUNCATED_CASSETTE_PATH, DOCUMENT_PATH),
    ],
    ids=["five_stage", "hyphenated", "retry_path", "truncated"],
)
def test_committed_cassettes_match_the_current_prompts(
    tmp_path: Path, cassette_path: Path, document_path: Path
) -> None:
    """The staleness signal, asserted where it is cheap to fix: in this repo.

    Drift here means someone changed an operator's prompt without re-recording,
    so the committed cassette no longer reflects what a live model would be
    asked. Re-record with `tools/record_cassette.py record`.
    """
    text = document_path.read_text(encoding="utf-8")
    provider, _, _ = _replay(tmp_path, text, cassette=cassette_path)
    assert provider.drifted_calls == [], (
        f"{cassette_path.name} predates the current prompts — re-record it with "
        "tools/record_cassette.py"
    )


def test_recording_round_trips(tmp_path: Path) -> None:
    """`RecordingProvider` captures verbatim; the cassette reloads unchanged."""
    inner = MockProvider(["first completion", "second completion"], model="m")
    recorder = RecordingProvider(inner, document="doc", provider="test", model="m")
    recorder.complete(ProviderRequest(user="one"))
    recorder.complete(ProviderRequest(user="two"))
    assert recorder.call_count == 2

    out = tmp_path / "nested" / "cassette.json"
    recorder.cassette().save(out)

    replay = ReplayProvider.from_path(out, document="doc")
    assert [e.response_text for e in replay.cassette.exchanges] == [
        "first completion",
        "second completion",
    ]
    assert replay.complete(ProviderRequest(user="one")).text == "first completion"
    assert replay.call_count == 1
    assert replay.drifted_calls == [], "an identical request must not read as drift"


def test_malformed_and_empty_cassettes_are_refused(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(CassetteError, match="Could not load"):
        Cassette.load(missing)

    garbage = tmp_path / "garbage.json"
    garbage.write_text("not json at all", encoding="utf-8")
    with pytest.raises(CassetteError, match="Could not load"):
        Cassette.load(garbage)

    empty = tmp_path / "empty.json"
    Cassette(
        recorded_at=dt.datetime(2026, 9, 10, tzinfo=dt.UTC),
        provider="test",
        model="m",
        document_sha256="0" * 64,
    ).save(empty)
    with pytest.raises(CassetteError, match="no exchanges"):
        Cassette.load(empty)


def test_future_cassette_version_is_refused(tmp_path: Path) -> None:
    """A format change must announce itself, not silently misread old data."""
    path = tmp_path / "v99.json"
    cassette = Cassette.load(CASSETTE_PATH)
    bumped = cassette.model_copy(update={"version": 99})
    bumped.save(path)
    with pytest.raises(CassetteError, match="version 99"):
        Cassette.load(path)
