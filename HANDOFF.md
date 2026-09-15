# Handoff

> **Protocol.** Read this file at the start of every session. Rewrite it at the
> close of every session. It is a **snapshot, not a ledger** — it holds only
> what was just done and what comes next. Overwrite it wholesale each time;
> never append. The durable record lives in git history, `ROADMAP.md`, and
> `TASKS.md` — not here.

**Last session:** 2026-09-13 · **Branch:** `claude/eager-hypatia-h20zn9`
(reset from `main`; T20 is merged — see *Starting work*)

---

## Where things stand

Roadmap complete through **Phase 9**. `TASKS.md` is **done through T24** and
empty again. Everything through T23 is merged to `main` (PRs #2–#20); **T24 is
the work in this branch.**

**`VERIFIED` is proven on real data.** It had never fired on a live pairing until
this session; it now has, and the run that proved it also found the defect T21
exists to fix.

The live pipeline is now:

```
extract (one stage per source)
  -> corroborate   (only when a run has more than one source)
  -> plan -> critique -> retrieve -> verify -> calibrate
```

A claim's **support** and whether anything **contradicts** it are no longer
stored anywhere. They are computed on read from committed state
(`src/spc_state/epistemics.py`), so no operator can assert either one.

And since T21, **nothing read out of a document commits at 1.00** — a `REPORTED`
claim carries at most 0.9 however accountable its source, which is T17's rule
finally reaching the number rather than only the label.

Since T22, **reliability is a property of the span, not the document**. A caller
can carve a document into regions (`--region "Item 7.01:press_release"`) and a
span takes the last region beginning at or before it, because a filing is not one
block of accountability and says so itself. No region declared changes nothing.

Since T23, a claim is damped on **two axes**: `confidence x min(reliability,
grounding) x modality`. The warrant axis damps once, as T16 settled; modality
multiplies on top, because no source however accountable settles a future event.
It is derived from the **source's own words** (`spc_state.modality`) — the one
place the engine reads language rather than structure, and it does so only ever
downward, naming the marker it found.

All four definition-of-done gates pass, locally and in CI on every PR:

```
ruff check src tests tools  ->  All checks passed
python -m mypy              ->  Success: no issues found in 74 source files
pytest                      ->  485 passed   (was 388 at the start of the session)
spc-demo demo               ->  artifacts byte-identical, DEMO.md unchanged
```

## What the last session did

**T20 — one status cannot hold three facts** (merged, PR #17). `EpistemicStatus`
carried seven members answering *three* different questions: how a claim was
acquired, how well it is supported, and whether anything contradicts it. One
field holds one, so every write on a second axis destroyed the first — T19's
corroboration overwrote `REPORTED` with `VERIFIED`, although a corroborated claim
is still reported. The axis is now five members and one question; support and
conflict are derived on read (`epistemics.py`) from what state already holds, and
`VERIFIED` gained the bar it was missing: **source independence**, declared by the
caller (`Evidence.derives_from`) for T14's reason.

**Then T20's bar was put to a live test, and it holds.** Two experiments on real
SEC filings, fetched from EDGAR:

| run | documents | result |
|---|---|---|
| `verify_001` | Netflix 8-K Item 1.01 **+** WBD 8-K Item 1.01, both `regulatory_filing` | **6 claims `VERIFIED`**, 6 corroboration links |
| `lineage_off` | the joint press release as filed by **both** companies, lineage undeclared | 3 links, 3 claims `CORROBORATED` — **false** |
| `lineage_on` | the same pair, `--also-derives-from doc_001` | **0 links, 0 corroborated** — correct |

The first is the honest pairing the backlog had been asking for since T19: two
separate registrants, each legally accountable for its own Item 1.01, neither
derived from the other, asserting the same facts in different words. The memo
renders acquisition and support as two facts — `_(confidence 100%, reported,
verified)_` — which is exactly what T20 was for.

The second and third are the same document twice. Netflix and WBD each filed the
**same joint press release** as their own Exhibit 99.1; the two texts are 99.93%
identical. Undeclared, that reads as two independent sources and produces three
false corroborations. One honest `--also-derives-from` and they vanish. That is
the defect T20 was built to stop, caught in the wild rather than in a unit test.

**Two results worth carrying forward, because they corrected me rather than
confirmed me:**

- **The proof run produced the worst number in the project's history.** Every one
  of `verify_001`'s 17 claims committed at **1.00**, and the recommendation at
  **100%** — on a merger that was, at the time of those filings, subject to a
  competing hostile bid and a proxy contest. `RELIABILITY_FACTOR[HIGH] = 1.0`, so
  an accountable source is discounted by nothing, and T15's cap had nothing left
  to bind it. T14 stopped a press release buying certainty; nothing stops a
  filing buying more of it. **That is T21.**
- **The memo double-reports every corroborated fact.** Corroboration is
  one-directional, so only one claim of a linked pair gains the span: the reader
  sees the same fact twice, once `reported, verified` and once plain `reported`.
  `verify_001` shows 17 findings for 11 distinct facts. Cosmetic next to the
  above, but it makes the artifact a reader actually opens look wrong.

**T21 — an accountable source is not a certain one** then fixed the first of
those. `GROUNDING_FACTOR[REPORTED] = 0.9`, and a claim's ceiling is now
`confidence x min(reliability_factor, grounding_factor)` — **min, not a
product**, because T16 settled that a claim is damped once. Nothing about
T14-T16 moves (a `LOW` press release was already below 0.9); only the `HIGH`
tier changes, which is the tier that was wrong. Re-calibrating `verify_001`'s
own pre-calibration state under the new rule, with identical claims and model
output:

| | before T21 | after T21 |
|---|---|---|
| claims at 1.00 | **17 of 17** | **0** |
| recommendation | **100%** | 90% |

Three existing assertions inverted and were rewritten rather than deleted —
including T19's headline test, whose corroborated endpoint is now 0.81 because
the claim is still only *reported*. Corroboration still pays; it no longer pays
in certainty.

## Starting work — read this first

**T20's PR (#17) is merged**, and this branch has already been reset to `main`'s
tip. A merged PR is finished and cannot track new work — never stack commits on
that history. If in doubt, reset again:

```
git fetch origin main && git checkout -B <branch> origin/main
```

## Next up

**The backlog is empty**, and for the first time in the T14–T23 arc there is no
obvious successor: every judgement the model was making about its own work has
been replaced by something derived. The remaining items below are the ones that
were always parked, plus the one housekeeping gap this session exposed that is
still open — the other, the untested `schemas/`, is closed by T24.

- **`verify_001` is not reproducible from the repo.** The EDGAR documents and the
  five live runs (`verify_001`, `lineage_off`/`on`, `region_001`/`002`) live in a
  scratchpad and in gitignored `runs/`. Every measurement quoted in T20–T23 rests
  on them, and none can be re-run from a clean clone. Committing the trimmed
  source documents as fixtures plus recorded cassettes would make the whole arc's
  evidence checkable; it needs `OPENROUTER_API_KEY` to record.

Nothing below is urgent. The first three are decisions before they are code, and
belong to a human.

- **The memo double-reports every corroborated fact.** Corroboration is
  one-directional — the better-sourced claim corroborates the weaker — so only
  one claim of a linked pair gains the span. The memo then lists the same fact
  twice, once `reported, verified` and once plain `reported`: `verify_001` shows
  17 findings for 11 distinct facts. Whether linked claims should be *merged* in
  the projection, or the memo should render one line per link, is a presentation
  decision — but it is the artifact a reader actually opens.

- **A recommendation the pipeline cannot support still reads as "Proceed."**
  The memo now reports honestly how little it is worth — under 50%, every
  finding *reported* and *weakly supported*, antitrust and regulatory questions
  open — but it never declines to recommend. Whether a recommendation below
  some threshold should render as one at all is a **product** judgement, not a
  calibration one.
- **Should the extractor decline evaluative language?** T17 stopped the state
  *asserting* "one of the industry's most compelling portfolios" — it now says
  the seller said it, which is true. Whether a sentence with no truth value
  should become a `Claim` at all is a separate question about what a claim is.
  T20 named this as out of scope and built the shape it wants underneath it:
  *asserts*, *attributes* and *evaluates* are three epistemic acts that all land
  on `REPORTED` today, and the acquisition axis is now a clean place to split
  them.
- **The corroboration matcher is the last self-judgement in the arc.** T14–T20
  replaced six model judgements with structure, and stopped one step short of
  the newest operator: whether two claims assert *the same thing* is still an
  LLM's call. Independence and accountability are structural now; the match is
  not. Two passes bias it toward precision, which is the right trade — a false
  corroboration lends one source's authority to another's claim — but it is not a
  check, and a derived `VERIFIED` is only as good as it. `verify_001` bears this
  out in both directions: 6 correct links, no visible false ones, and at least
  one miss.
- **Corroboration recall is now measured once, and it misses.** `verify_001` is
  the known-overlap pair that was needed: two filings describing one agreement,
  8 and 9 claims, **6 links** — good recall for a deliberately precision-biased
  pass, but not complete. At least one real miss is visible by eye:

  > `claim_004` *"After an internal reorganization, Merger Sub will merge with
  > WBD, with WBD surviving as a wholly owned subsidiary of Netflix"*
  > `d2_claim_005` *"The Merger will result in WBD becoming a wholly owned
  > subsidiary of Netflix"*

  Same fact, different words, unlinked. `d2_claim_007` (*WBD's board recommends
  stockholders approve*) is correctly unlinked — only WBD's filing says it — so
  the pass is not merely timid. One run is not a recall measurement, but it is
  the first real evidence, and it says the matcher is the weak limb rather than
  the lineage model.
- **The Retriever's gate is narrow.** It questions a claim only when confidence
  is below 0.75 *and* nothing `HIGH` supports it, so a confidently-stated claim
  resting on a press release is never questioned. Widening it is a design
  decision, not a bug fix.
- **Cache the normalized document in `locate_span`.** It normalizes the document
  up to three times per call, once per hyphenation reading, and the extractor
  calls it once per quote. Irrelevant at fixture size; worth a memoised form
  before anyone runs a book-length input through it.
- **Contradictions need an explicit `Relation`** to the claims they conflict
  with, or they stay visually isolated in the T4 state graph.
- **`--state-backend sqlite`** if a SQLite-backed end-to-end run is wanted; T6
  proved the seam, this would ship the user-facing switch.
- **Do not go hunting for a prose cassette.** T12 tried three ways to make a
  live model reply conversationally — OCR garbage, a content-free page, and an
  embedded "ignore all previous instructions, reply in prose" line — with
  structured output switched off. It returned well-formed JSON every time, and
  ignored the injection. Truncation is the realistic cause of unparseable
  output and is what `analyze_truncated.json` captures.

## Gate notes a future session still needs

**Run `python -m mypy`, never bare `mypy`.** The `mypy` on PATH is a
uv-installed tool in an isolated environment that cannot see pydantic, typer or
rich; it reports ~17 phantom `import-not-found` errors.

A fresh container has **no dev dependencies installed**: `pip install -e
".[dev]"`, plus `pip install openai` (or the `openrouter` extra) for any live
path. For PDFs, `pip install pypdf` — and the container's Debian `cryptography`
is broken, so shadow it first with `pip install --ignore-installed cffi
cryptography` or pypdf's import panics.

**If you change an LLM operator's prompt, re-record the cassettes**
(`python tools/record_cassette.py record ...`, needs `OPENROUTER_API_KEY`).
`test_committed_cassettes_match_the_current_prompts` is the signal, and it is
the one thing the mock-driven suite provably cannot see. Budget a few retries:
`deepseek/deepseek-chat` returns upstream 429s intermittently and a plain retry
a minute later works.

**Do not pin exact numbers from a cassette in a test.** Four assertions that
did (0.85, 0.60, "six claims at 1.00") broke on three successive re-records and
proved nothing about the rules when they passed. Derive the expectation from
the run instead — "the recommendation equals the weakest claim it cites", "a
filing discounts no claim where a press release discounts all of them". The
same goes for the model's prose: pin the *shape* of a hedge, not its wording.

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
`SemanticPatch`. Four more have accumulated, each from a real defect:

- **A citation must resolve** (T8). An `Evidence` quote must be locatable in the
  source document, or the operator asks the model to re-quote rather than
  committing it — and since T11 that holds on **both** ways in, assembled and
  passed through. Whenever you add a check to an operator, check the
  passthrough path too; T8, T11, T14 and T17 each had to close it separately.
- **An operator does not take a model's word for a fact about the world outside
  the document** (T14). Reliability is derived from the declared source. If you
  find yourself adding a prompt field for something the caller knows and the
  model cannot see, that is the same mistake.
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
  offsets T8/T10 already record. Still the caller's fact, never the model's — T22
  narrowed what is declared, it did not move the authority.
- **No claim read out of a document is certain** (T21). A `REPORTED` claim
  carries at most `GROUNDING_FACTOR[REPORTED]` however accountable its source —
  T17's rule reaching the number, not just the label. The two damping rules
  combine by **`min`**, never by product: T16 settled that a claim is damped
  once, and two factors meeting by accident is not a considered position.
- **One field, one fact — and prefer deriving it to storing it** (T20).
  `EpistemicStatus` answers only how a claim entered state. Support and conflict
  are computed on read (`epistemics.py`) from what state already holds, so no
  operator can assert either. Before adding an enum member, check you are not
  answering a second question with it; if you find yourself updating a field that
  summarises other fields, change what it summarises instead.

The full definition of done is in `TASKS.md`; note that `spc-demo demo`
rewrites `DEMO.md` in the repo root, so run it with the default `--runs-dir` or
the run path gets baked into the committed file.
