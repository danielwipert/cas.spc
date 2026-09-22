# Handoff

> **Protocol.** Read this file at the start of every session. Rewrite it at the
> close of every session. It is a **snapshot, not a ledger** — it holds only
> what was just done and what comes next. Overwrite it wholesale each time;
> never append. The durable record lives in git history, `ROADMAP.md`, and
> `TASKS.md` — not here.

**Last session:** 2026-09-16 · **Branch:** `claude/nifty-goodall-be31yp`
(branched from `main` at `3ac1066`)

---

## Where things stand

Roadmap complete through **Phase 9**. `TASKS.md` is **done through T29**.
T0–T27 are merged to `main` (PRs #2–#26); **T28 and T29 are this branch,
not yet merged.**

The live pipeline is unchanged:

```
extract (one stage per source)
  -> corroborate   (only when a run has more than one source)
  -> plan -> critique -> retrieve -> verify -> calibrate
```

All four definition-of-done gates pass, locally and in CI on every PR:

```
ruff check src tests tools  ->  All checks passed
python -m mypy              ->  Success: no issues found in 74 source files
pytest                      ->  555 passed   (was 520 at the start of the session;
                                 also green under FORCE_COLOR=1 — see gate notes)
spc-demo demo               ->  artifacts byte-identical, DEMO.md unchanged
```

## What this session did

**A direction was set before any code was written**, and it is the thing to
hold onto: everything the 520-test suite tested was **mechanism**, and nothing
tested **output quality**.

| tested before this session | not tested at all |
|---|---|
| does the patch validate and route? | is the memo *right*? |
| does a declared region reprice the number? | did we extract the facts a reader needs? |
| is the demo byte-identical? | does a cited span actually support its claim? |

`src/spc_state/evaluation/` sounds like it closes this and does not: it scores
**SPC against the JSON-handoff baseline** on architecture (provenance, drift,
audit clarity). Those are 3/3-vs-0/3 wins by construction, and **none of them
would move if the extraction got worse.**

**T28 — `spc-demo replay`.** Step 1 of four toward scoring outputs, and the
precondition for the rest: the memo and receipt could only be produced from
inside `pytest`, so the artifacts the engine exists to produce were the one
thing a contributor could not look at. `replay` drives the full pipeline from a
cassette — no key, no network, nothing spent — and writes the run tree, memo
and receipt. Details, including the sharp edge, are in `TASKS.md` T28.

Two properties are worth knowing before using it:

- **It is byte-reproducible.** The clock is fixed to the cassette's own
  `recorded_at`, so two replays write identical artifacts. That is what makes a
  replayed output a *yardstick* — diffable across a change to the engine, which
  a live run can never be.
- **The declarations were the caller's and unverifiable — T29 fixed that.**
  A cassette now records how its run was declared, so
  `spc-demo replay --cassette X` is the whole command. See below.

**T29 — a cassette records how its run was declared.** Step 1b, and it closed
T28's own footgun rather than documenting it. `source_type` and `derives_from`
are the caller's facts and reach no prompt (T14), so replaying a cassette with
a different `--source-type` gave **zero drift, a clean run, and a different
memo** — invisible to both the digest and drift detection. `RunSpec` records
them; all 8 cassettes are backfilled; `spc-demo replay --cassette X` needs no
other argument, and any override is reported as a deviation rather than
refused. Details and the verification table are in `TASKS.md` T29.

The backfill was **derived, not remembered** — document lists from digest
matching, questions proved by the no-drift gate — and the two declarations that
reach no prompt are verified against *behaviour*: a wrong source type on
`analyze_two_filings` would stop a claim reaching `VERIFIED`, and wrong lineage
on the joint-PR pair would stop corroboration flipping. Both asserted.

**A fifth defect, found while checking the deviation report — and it is the
worst one.** Overriding `--question` produced **no drift**, because the question
reaches no prompt at all. `build_analysis_operators` does not take it; no
operator receives it. It is the heading on the memo and receipt and **nothing
else**.

So defect 3 below is not a rendering choice, it is a missing wire: the planner
is never told what the reader asked, and the memo's title and its content are
unconnected by construction. Whether the question should steer extraction, the
planner, or both — and whether a recommendation should be declined when the
question asked for facts — is a **product** decision and belongs to a human.
This is the most valuable thing the session found, and it was found by reading
one output.

**Reading one replayed memo found four defects no test would catch.** This is
the argument for the whole direction, and the four are the first things a
scorer should be pointed at (`analyze_8k_complete`, region declared):

1. **"Weakly supported" flags 9 of 11 findings**, so the risks section is a
   reprint of the findings list. `WEAK_CONFIDENCE_THRESHOLD` is 0.75
   (`projection/builder.py`) against a 0.9 `REPORTED` cap, so almost nothing
   clears it — including a verbatim quote of the executed merger agreement.
2. **A material number is dropped in extraction.** E5's span contains the
   `$23.25` cash consideration; the claim built off it says "converted into
   cash and shares" with no amount. The number a reader came for reaches only
   the *Sources* section.
3. **The memo answers a question nobody asked.** Input question was *"What did
   Netflix agree to, and on what terms?"* — factual. Output leads with
   *"Proceed with the merger as planned."* A recommendation is always rendered,
   whether or not the question calls for one. **Cause now known** (T29): the
   question reaches no operator, so nothing in the pipeline could have
   answered it.
4. **Duplicate work reaches the reader.** Two of three open questions are the
   same question about the same claim (planner asks it, Retriever asks it
   again); two of three assumptions are near-paraphrases of each other.

Note 1, 3 and 4 are calibration/presentation; 2 is extraction. Today nothing
would tell us whether any of them got better or worse.

## Starting work — read this first

**T28 is unmerged on `claude/nifty-goodall-be31yp`.** If its PR has merged
since, a merged PR is finished and cannot track new work — reset and start
clean rather than stacking:

```
git fetch origin main && git checkout -B <branch> origin/main
```

**If you stack a second PR on the first, retarget it by hand.** GitHub
retargets a stacked PR to `main` automatically **only when the base branch is
deleted on merge**, and this repo keeps its branches.

## Next up

The plan is four steps and **Steps 1 and 1b are done**. Steps 2–4 are the
substance, and Step 2 is a human's judgement before it is anyone's code.

**Read one replayed memo before starting.** It is one command now
(`spc-demo replay --cassette tests/fixtures/cassettes/analyze_8k_complete.json`)
and it is how all five defects above were found.

- **Step 2 — a gold set. This is a human's judgement, not an agent's.** Pick
  documents and write down, by hand, for each: the facts that **must** appear,
  the facts that must **not** be claimed, and what each must rest on. Store
  beside the cassette. **Start with two documents, not eight** — build the
  scorer against a tiny corpus and confirm the metrics catch the four defects
  above before expanding. A 20-document gold set built before the metrics are
  known to work is wasted effort.

- **Step 3 — score against it.** A new `src/spc_state/eval/`, kept **distinct
  from today's `evaluation/`** (that one scores architecture against the
  baseline; do not overload it). Output metrics: fact recall/precision,
  citation faithfulness — does the span actually support the claim text, which
  catches defect 2 — noise rate (duplicate questions/assumptions, defect 4),
  and calibration spread (defect 1).

- **Step 4 — `spc-demo eval`.** One scorecard table, run off cassettes so it
  is free and deterministic, and CI can fail on regression. Quality becomes a
  number that moves when a prompt changes.

Expanding the corpus past what is committed needs live runs, so
`OPENROUTER_API_KEY` and the record-once/replay-forever loop
(`tools/record_cassette.py record`).

### Older open threads (unchanged, none urgent)

These predate the evaluation direction and are still true. The first three are
decisions before they are code, and belong to a human.

- **The memo double-reports every corroborated fact.** Corroboration is
  one-directional, so only one claim of a linked pair gains the span, and the
  memo lists the same fact twice. T26's undeclared run is it at its worst:
  **24 findings for 15 distinct facts**. Whether linked claims should be
  *merged* in the projection, or the memo render one line per link, is a
  presentation decision — but it is the artifact a reader opens. (Note this is
  the same family as defect 4 above; a noise metric would cover both.)
- **A recommendation the pipeline cannot support still reads as "Proceed."**
  Same as defect 3 above. Whether a recommendation below some threshold should
  render at all is a **product** judgement, not a calibration one.
- **Should the extractor decline evaluative language?** T17 stopped the state
  *asserting* "one of the industry's most compelling portfolios". Whether a
  sentence with no truth value should become a `Claim` at all is a separate
  question. T20 built the shape underneath it: *asserts*, *attributes* and
  *evaluates* all land on `REPORTED` today, and the acquisition axis is a clean
  place to split them.
- **The corroboration matcher is the last self-judgement in the arc.** T14–T20
  replaced six model judgements with structure and stopped one step short:
  whether two claims assert *the same thing* is still an LLM's call.
  Independence and accountability are structural now; the match is not.
- **Corroboration recall is measured from both ends.** `verify_001`: two
  filings, 8 and 9 claims, **6 links** — with at least one miss visible by eye
  (`claim_004` / `d2_claim_005`, same fact, different words, unlinked). T26 is
  the other end: two copies of one document, **10 links**. So it is not timid
  when the wording is identical and misses when it is not — the matcher is the
  weak limb, not the lineage model. **A fact-recall metric (Step 3) would put a
  number on this for the first time.**
- **The Retriever's gate is narrow.** It questions a claim only when confidence
  is below 0.75 *and* nothing `HIGH` supports it, so a confidently-stated claim
  resting on a press release is never questioned. Widening it is a design
  decision, not a bug fix.
- **Cache the normalized document in `locate_span`.** It normalizes up to three
  times per call, once per hyphenation reading; the extractor calls it once per
  quote and `resolve_regions` once per declared marker. Irrelevant at fixture
  size; worth a memoised form before a book-length input.
- **Contradictions need an explicit `Relation`** to the claims they conflict
  with, or they stay visually isolated in the T4 state graph.
- **`--state-backend sqlite`** if a SQLite-backed end-to-end run is wanted; T6
  proved the seam, this would ship the user-facing switch.
- **Do not go hunting for a prose cassette.** T12 tried three ways to make a
  live model reply conversationally, with structured output off. It returned
  well-formed JSON every time and ignored the injection. Truncation is the
  realistic cause of unparseable output and is what `analyze_truncated.json`
  captures.

## Gate notes a future session still needs

**Run `python -m mypy`, never bare `mypy`.** The `mypy` on PATH is a
uv-installed tool in an isolated environment that cannot see pydantic, typer or
rich; it reports ~17 phantom `import-not-found` errors.

A fresh container has **no dev dependencies installed**: `pip install -e
".[dev]"`, plus `pip install openai` (or the `openrouter` extra) for any live
path. For PDFs, `pip install pypdf` — and the container's Debian `cryptography`
is broken, so shadow it first with `pip install --ignore-installed cffi
cryptography` or pypdf's import panics. **PyPI reads time out on this
container**: use `pip install --timeout 120 --retries 5`, which succeeds where
the default gives up mid-download.

**If you change an LLM operator's prompt, re-record the cassettes**
(`python tools/record_cassette.py record ...`, needs `OPENROUTER_API_KEY`).
`test_committed_cassettes_match_the_current_prompts` is the signal, and it is
the one thing the mock-driven suite provably cannot see. `spc-demo replay` now
reports the same drift per run, so an eyeballed memo says whether it came from
a prompt still in use. Budget a few retries: `deepseek/deepseek-chat` returns
upstream 429s intermittently and a plain retry a minute later works.

**Assert on CLI output only after stripping ANSI** (`_plain` in
`tests/test_cli_replay.py`). Rich highlights option names and digits by styling
*fragments*: `--also-source-type` is emitted as `-`, `-also`, `-source-type`,
each in its own escape sequence, so the literal flag is **not a substring** of
what `CliRunner` captured. Whether it happens at all depends on whether rich
believes it is writing to a colour terminal — **false in this container, true
in GitHub Actions**. That is a real CI-only failure mode: T28's suite was green
locally and red on both Python versions in CI for exactly this. Reproduce CI
with `FORCE_COLOR=1 TERM=xterm-256color python -m pytest -q`, and run it that
way before pushing anything that asserts on terminal output.

**Do not pin exact numbers from a cassette in a test.** Four assertions that
did (0.85, 0.60, "six claims at 1.00") broke on three successive re-records and
proved nothing about the rules when they passed. Derive the expectation from
the run instead — "the recommendation equals the weakest claim it cites", "a
filing discounts no claim where a press release discounts all of them".
`tests/test_cli_replay.py` follows this: the region experiment asserts
`declared < undeclared`, never 38 and 57. The same goes for the model's prose:
pin the *shape* of a hedge, not its wording.

> ⚠ **Do not "fix" UP042.** It wants `class X(str, Enum)` → `StrEnum` across
> `models/enums.py`. Verified in a REPL: that changes `str()` and f-string
> output from `ObjectType.CLAIM` to `claim`, which would silently alter every
> rendered receipt and memo and break the byte-stable demo artifacts. The
> ignore is deliberate and documented at the rule. `SourceType` in
> `source_types.py` is the same shape and the same reasoning applies.

> ⚠ **`provenance.py`'s fold table is written as unicode escapes, not literal
> characters.** Several are invisible or ASCII-lookalikes in an editor, and
> ruff's RUF001 flags the literals as ambiguous. Keep the escapes.

## Before touching code

Read [`AGENTS.md`](./AGENTS.md). The hard invariant: **no operator mutates
`SemanticState` directly** — all change flows through a validated
`SemanticPatch`. Several more have accumulated, each from a real defect:

- **A citation must resolve** (T8). An `Evidence` quote must be locatable in the
  source document, or the operator asks the model to re-quote rather than
  committing it — and since T11 that holds on **both** ways in, assembled and
  passed through. Whenever you add a check to an operator, check the
  passthrough path too; T8, T11, T14 and T17 each had to close it separately.
- **An operator does not take a model's word for a fact about the world outside
  the document** (T14). Reliability is derived from the declared source. If you
  find yourself adding a prompt field for something the caller knows and the
  model cannot see, that is the same mistake. **T28's footgun is the cost of
  this rule**: a declaration that reaches no prompt cannot be verified by
  replay either, which is why cassettes should record it (Step 1b).
- **A confidence a model chose is re-derived, not accepted** (T15/T16). A claim
  is discounted by the source it cites; a recommendation is capped at the
  weakest claim it cites. **Only ever downward**, and every change records what
  moved it. T19 shows the way to raise something honestly: change what it rests
  on and let this rule reprice it — do not add an exception.
- **Reading a document is not observing the world** (T17). An extracted claim is
  `REPORTED`; `OBSERVED` is for an operator that genuinely sees the thing.
- **An accountable source cannot settle a future event** (T23). Modality is read
  from the cited span's own words, never asked of the model, and only ever lowers.
  It multiplies with the warrant axis rather than joining its `min` — a good
  source must not be able to mask an unsettled claim. This is the engine's one
  linguistic heuristic: keep it auditable (it names its marker), biased against
  firing (every cited span must be unsettled), and honest about its limits.
- **A document is not one block of accountability** (T22). Reliability is a
  property of the *span*, resolved from the caller's declared regions against the
  offsets T8/T10 already record. Still the caller's fact, never the model's.
- **No claim read out of a document is certain** (T21). A `REPORTED` claim
  carries at most `GROUNDING_FACTOR[REPORTED]` however accountable its source.
  The two damping rules combine by **`min`**, never by product: T16 settled that
  a claim is damped once, and two factors meeting by accident is not a
  considered position.
- **One field, one fact — and prefer deriving it to storing it** (T20).
  `EpistemicStatus` answers only how a claim entered state. Support and conflict
  are computed on read (`epistemics.py`) from what state already holds, so no
  operator can assert either. Before adding an enum member, check you are not
  answering a second question with it.
- **Two commands that describe the same run share one resolver** (T28).
  `analyze` and `replay` both take the source declarations, and a replay that
  describes its sources differently from the recording replays against material
  the recording never saw. `_declare_sources` is the single definition, for the
  same reason `tools/record_cassette.py` shares `_add_source_args` between
  `record` and `check`.
- **A declaration that reaches no prompt must be recorded, not remembered**
  (T29). T14's rule — that the caller's facts never enter a prompt — has a
  cost: nothing about the *request* changes, so no digest and no drift check
  can tell whether a replay was declared the way its recording was. Anything
  the caller declares therefore belongs in the cassette (`RunSpec`), and a
  deviation is reported rather than refused. If you add a new declaration to
  `analyze`, add it to `RunSpec` in the same change — unless, like a region,
  it is deliberately meant to vary over one recording.

The full definition of done is in `TASKS.md`; note that `spc-demo demo`
rewrites `DEMO.md` in the repo root, so run it with the default `--runs-dir` or
the run path gets baked into the committed file.
