# TASKS.md — contributor backlog for cas.spc

These are narrow, test-backed units of work for anyone — a human or a coding
agent — extending the SPC engine past the v0.1 pilot. **Read
[`AGENTS.md`](./AGENTS.md) first.** Every task below must keep the hard
invariant: no operator mutates `SemanticState` directly; all change flows
through a validated `SemanticPatch`.

## How to pick up a task

1. Read `AGENTS.md` (architectural invariants) and the relevant `PILOT_SPEC.md`
   section linked in the task.
2. Branch off `main`. Keep the change scoped to the files listed.
3. Write the acceptance test first; make it pass.
4. **Definition of done** for every task:
   - the stated acceptance test passes;
   - `pytest` is green and `ruff check src tests tools` + `python -m mypy` are
     clean (**`python -m mypy`, not bare `mypy`** — a uv/pipx-installed mypy
     runs isolated from the project's dependencies and reports ~17 phantom
     import errors);
   - the deterministic demo stays byte-for-byte reproducible
     (`spc-demo demo` → identical `DEMO.md`) unless the task explicitly changes
     it;
   - no run output committed (`runs/` is gitignored).

   All four run in CI on every pull request and on `main`
   (`.github/workflows/gates.yml`), across Python 3.11 and 3.12. They are the
   same commands you run locally — nothing there is CI-only, so a green run
   means what a clean working copy means.

Tasks are roughly ordered easiest → hardest. Size is a rough estimate, not a
promise. A ⚠ marks a task that requires a deliberate decision to relax a
documented v0.1 constraint — get sign-off before starting.

---

## T0 — Generalize Planner & Critic to arbitrary input (LLM-backed) · ✅ DONE

`LLMExtractOperator`, `LLMPlannerOperator`, and `LLMReviewCriticOperator`
(`operators/*_llm.py`, sharing `operators/_assembly.py`) now run the **full**
live pipeline on any document — `spc-demo analyze` drives extract → plan →
critique → receipt. Verified live and with injected-provider tests
(`tests/test_extract_llm.py`, `tests/test_planner_critic_llm.py`). The model
supplies content; the operator owns ids/transform bookkeeping; everything
flows through `Runtime.step_llm`.

Follow-on ✅ **DONE** — shape-invalid LLM output now retries. The planner used
to **REJECT** when the model returned valid JSON in the wrong shape, because
the runtime only RETRYd on `JSON_DECODE`, spending 1 of 3 attempts. Two halves,
both needed:

- **Routing.** `router.decide_llm` (spec §15.6) routes *any* L1 schema failure
  to RETRY on the LLM path — a model can repair its own output. `router.decide`
  is unchanged for deterministic operators, where the same failure is a code
  bug. L2 failures still REJECT on both paths.
- **Feedback.** The validation issues are pydantic errors about `SemanticPatch`
  fields the operator never asked the model for, so feeding them back would
  misdirect it. Operators that assemble a patch from a compact content shape
  now return an `OperatorCompletion` with a `repair_hint` (from
  `LLMAssemblyError`), and `Runtime.step_llm` prefers it. The planner asks for
  a hypothesis by name; extract, critic and the contradiction verifier carry
  their own hints.

Tests: `tests/test_router.py` (the `decide_llm` table) and
`tests/test_planner_critic_llm.py` (retry-then-commit, exhaustion, and that the
repair prompt carries no `SemanticPatch` noise).

---

## T1 — RetrieverOperator (complete the §8.3 SPC flow) · S

✅ **DONE.** `src/spc_state/operators/retriever.py` (`RetrieverOperator`,
deterministic — no model) reads its `RETRIEVER` projection and opens a
`needs_evidence` question for each evidence-gap claim (no evidence on record →
high priority; under-confident on lower-reliability evidence → medium). Wired
into `spc-demo analyze` as the 4th stage (extract → plan → critique → retrieve
→ v4); the gaps surface in the Decision Memo's open questions. Tests in
`tests/test_retriever.py` (flags gaps not grounded claims, priority, clean
state flags nothing, no direct mutation). Deliberately **not** added to the
deterministic `spc-demo demo`, so the frozen pilot artifacts (DEMO.md, pilot
report, §8.4 v1→v3 follow-ups) stay byte-stable.

---

## T2 — Writer: project the citation-backed memo from state · ✅ DONE

`src/spc_state/memo.py` (`render_memo` / `write_memo`) projects committed state
into a stakeholder Decision Memo: recommendation (leading hypothesis), key
findings with inline `[E#]` citations, risks (weak claims + contradictions),
assumptions with what they affect, prioritized open questions, and a numbered
Sources list. Wired into `spc-demo analyze`; also a standalone `spc-demo memo
--run-id` to regenerate from any run. Pure read, deterministic, no model call —
the memo asserts nothing absent from state. Tests in `tests/test_memo.py`.

Possible follow-on: an *optional* LLM-narrated prose version layered on top
(kept off by default, since re-prompting risks the drift SPC prevents).

---

## T3 — Formal Contradiction objects · ✅ DONE

`src/spc_state/operators/contradiction_llm.py` (`LLMContradictionOperator`,
LLM-backed — conflict is a semantic judgement) reads the verifier projection
(all claims), asks for conflicting pairs, and commits first-class
`Contradiction` objects with status `unresolved` — that unresolved status *is*
the standing review flag (spec §20.5 counts these). It references only existing
claim ids, skips self-pairs, and never re-adds a pair already in state. Wired
into `spc-demo analyze` as the 5th stage (→ v5); contradictions render in the
Decision Memo's risks with claim text + resolution options. Tests in
`tests/test_contradiction_llm.py`. Verified live: a marketing-vs-finance
revenue memo surfaced a high-severity `factual_conflict` and a medium
`tension`, and the recommendation turned cautious.

Note on "routed for REVIEW": rather than withholding the patch (which would
lose the object), the conflict is committed *as* an unresolved object — the
queryable, review-pending record. A future L3/L4 validator could additionally
route the patch to REVIEW.

---

## T4 — State-graph visualizer (Mermaid export) · ✅ DONE

`src/spc_state/receipt/graph.py` (`render_mermaid_graph`) projects a
`SemanticState` to a Mermaid `flowchart TD`: one node per active object
(entities, claims, evidence, assumptions, inferences, hypotheses, questions,
contradictions — grouped in that fixed order, sorted by id within each
group), one edge per active `Relation` whose endpoints are both active nodes.
Nodes are styled per type via Mermaid `classDef`/`class`. Edges come only
from `state.relations` — the explicit, predicate-labeled graph the operators
already build — never from a claim's `assumptions`/`supporting_evidence`
fields or similar; that stays a faithful projection rather than inventing
edge semantics the state doesn't assert. "Active" follows `memo.py`'s
existing convention (`status != ARCHIVED`), so a resolved question or a
rejected hypothesis still renders — it's still part of how the state got
here.

Embedded into `render_markdown()` as a new "State Graph" section (right
after the Q/A summary), so it appears in every Reasoning Receipt written by
`write_run_artifacts` — both `spc-demo demo` and `spc-demo analyze`, with no
CLI changes needed. `tests/fixtures/reasoning_receipt_demo.md` was
regenerated to include it. Verified this does **not** touch `DEMO.md` byte
stability: `DEMO.md` reports the receipt only as a metric count, never its
rendered content.

12 tests in `tests/test_graph.py`: node/edge presence and stable ordering
against the `demo_history` fixture (including the two examples this task
originally named, both present in that fixture verbatim); an archived
object gets no node; a relation to an archived object, or an archived
relation itself, gets no edge; output is deterministic across calls; an
empty state renders a bare `flowchart TD`; long/quoted claim text is
truncated and escaped; entity and contradiction nodes (no shipped operator
populates either today) render correctly from hand-built state. 100% line
coverage on `graph.py`.

**Invariants held.** Read-only projection of state; deterministic (sorted)
output — never touches state, never calls a model.

---

## T5 — Per-operator model routing + cost ledger · ✅ DONE

**Per-operator model routing needed no new mechanism.** Every operator
already takes its own `LLMProvider` instance, and a provider carries its own
`model` — handing two operators two differently-configured providers already
runs two different models; verified directly in
`tests/test_cost_ledger.py::test_two_operators_with_different_models_get_different_fingerprints_and_costs`.
What T5 actually added is the accounting:

- **`TokenUsage`** (`models/transform.py`) — `prompt_tokens` /
  `completion_tokens`, plus `sum_token_usage(a, b)` for combining two calls'
  usage. `ProviderResponse.usage: TokenUsage | None` (`providers/base.py`);
  `MockProvider` estimates it via the existing `tokens.py` heuristic,
  `OpenRouterProvider` prefers the API's own reported usage and falls back to
  the same estimate when a response omits it (a bare/older SDK shape).
- **`TransformRecord.token_usage`** — `Runtime.step_llm` sums usage across
  *every* attempt of a step (a retry is a real, separately billed call, not
  a free do-over) and stamps the total on the final patch, the same place and
  the same way `model_fingerprint` is stamped — including on a REJECTed
  patch, which still cost real tokens (composes with the audit-trail fix
  earlier this session: `step.patch` survives rejection, so its cost does
  too). `LLMContradictionOperator`'s two-pass detection (propose, then an
  adversarial verify call) sums both passes into the one `TransformRecord`
  they share.
- **Pricing** — `providers/openrouter.py::MODEL_PRICING_PER_MILLION_USD` +
  `estimate_cost_usd(model, usage)`; an unlisted model gets a documented
  conservative default rather than a misleading $0.00.
- **The ledger** — `src/spc_state/cost_ledger.py` (`build_cost_ledger`,
  `write_cost_ledger`): one entry per `TransformRecord` that carries a
  `model_fingerprint` (a deterministic step, e.g. the Retriever, contributes
  nothing); writes `runs/<id>/cost_ledger.json`. Wired into
  `analyze.py::run_analysis` (always, since `analyze` is always LLM-backed)
  and into `cli.py run` / `demo.py run_full_demo`'s `--live-critic` paths
  only — the deterministic default writes no new file, so `DEMO.md` is
  unaffected (verified with a real `spc-demo demo` run).

**Known scope boundary**, documented rather than silently missed: a step
where *every* attempt was unparseable prose never assembles a patch, so
there is no `TransformRecord` to attach cost to, even though real tokens
were spent. The ledger sums per `TransformRecord`, per its literal scope —
not a full attempt-by-attempt accounting outside that.

22 tests: `tests/test_cost_ledger.py` (the acceptance scenario, retries
summed not just the winner, a rejected step still ledgers, deterministic and
fully-exhausted steps ledger nothing, pricing) plus two in
`test_openrouter_provider.py` (real usage preferred over the estimate, and
the estimate used when usage is absent) and one in
`test_analyze_pipeline.py` (all four LLM stages of a real five-stage run
ledgered). `cost_ledger.py` and `runtime/loop.py` are 100% covered.

**Invariants held.** Model choice stays per-task and configurable — no
hardcoded flagship anywhere. No network in any test — every provider is
`MockProvider` or a fake OpenAI-compatible client.

---

## T6 ⚠ — SQLite-backed StateStore · ✅ DONE (sign-off given 2026-09-03)

`StateStoreProtocol` (`store/store.py`) is the interface `Runtime` actually
depends on — a structural `Protocol` (three methods: `write`, `read`,
`latest_version`), not a base class, so the existing file-based `StateStore`
satisfies it with zero changes. `Runtime.__init__` gained one optional
keyword, `state_store: StateStoreProtocol | None = None`; when omitted it
builds the file-based store exactly as before, so every existing caller is
untouched — this is the whole extent of the runtime-side change, matching
the invariant literally.

`src/spc_state/store/sqlite_store.py` (`SQLiteStateStore`) implements that
same protocol against a **per-run** `.sqlite3` file
(`RunPaths.state_db_file`) — one table, one row per state version, the row
payload the exact same `model_dump_json(by_alias=True)` text the file
backend writes; only where it lives differs, not what it says. `close()`
releases the connection. A missing version raises
`StateVersionNotFoundError` (a `KeyError`), read alongside the file
backend's `FileNotFoundError` in tests. Everything else — patches,
validation reports, the audit log, diffs, receipts — stays file-based
regardless of which state backend is chosen; nothing wires a `--state-backend`
CLI flag, since T6 is about proving the seam exists, not shipping a new
user-facing switch.

One incidental fix discovered while testing: `RunPaths.ensure_dirs()` used to
unconditionally pre-create `state_dir`, which left a stray empty `state/`
directory sitting next to `state.sqlite3` on a SQLite-backed run. Removed —
the file-based `StateStore` already creates that directory lazily on first
write (`_write_model`'s `mkdir(parents=True, exist_ok=True)`), so the
pre-creation was already redundant for the file backend and actively
misleading for any other backend.

Tests in `tests/test_store_backends.py`: a generic behavioral suite
(`latest_version` before any write, round-trip, out-of-order writes,
overwriting a version, a missing version raises, two runs never share
state) parametrized over both backends via
`@pytest.fixture(params=[StateStore, SQLiteStateStore])` — 6 tests × 2
backends. Plus the literal acceptance scenario: the full deterministic demo
pipeline run once per backend (`tests/_demo_helpers.py::run_demo` gained an
optional `state_store_factory` parameter for this), asserting the committed
state history is identical version-for-version and object-for-object, while
confirming the storage medium genuinely differs (one leaves a `.sqlite3`
file and no `state/` directory, the other the reverse) so the comparison
isn't accidentally testing the same backend against itself. `sqlite_store.py`
is 100% covered.

**Invariants held.** The runtime changed by exactly one optional
constructor parameter — no behavior change for any existing caller.
Reproducibility preserved (verified byte-for-byte via `SemanticState.__eq__`
across backends, not just version numbers). `spc-demo demo` unaffected —
confirmed with a real run that `DEMO.md` doesn't change; no new file
appears under the deterministic `runs/demo/` tree either, since nothing
opts into the SQLite backend by default.

---

## T7 — End-to-end test for the `analyze` pipeline · ✅ DONE

`src/spc_state/analyze.py` (`run_analysis`, `build_analysis_operators`) is the
five-stage operator list + runtime run, factored out of `cli.analyze` so the
CLI and the test share it — the CLI command is now a thin wrapper that builds
the provider, calls `run_analysis`, and renders the result. `AnalysisResult`
carries the run plus the projected `ReceiptArtifacts` and memo path, both
`None` when nothing committed (no state to project from).

Tests in `tests/test_analyze_pipeline.py` (injected `MockProvider`, no
network, no key): a five-stage run reaches state v5 with the operators
committing in the documented order; one canonical patch and validation report
per stage (plus one attempt file per LLM stage, per the audit-trail fix —
none for the deterministic retriever); receipt and memo are written and every
`[E#]` citation in the memo's findings resolves to real evidence in the final
state; `--extract-only` stops at v1; nothing committed skips both artifacts
rather than building them empty.

`cli.py` coverage was ~20% with the pipeline entirely untested; the pipeline
logic itself (`analyze.py`) is now 100% covered. `cli.py` remains low because
what is left there is typer plumbing and console output, not logic.

---

## T8 — Verify evidence quotes against the source document · ✅ DONE

`src/spc_state/provenance.py` (`locate_span`, `normalize`) — a pure,
deterministic, offline lookup that finds an evidence quote in the document it
claims to come from and returns `SpanMatch(start, end)` **against the original
document offsets**, or `None`. Comparison happens under a documented
normalization: whitespace runs collapse, typographic quotes/dashes/spaces fold
to ASCII (double quotes fold to the same canonical mark as single ones), and
the quote's trailing punctuation may differ from the document's. Letter case
and any added, dropped, or reordered word are deliberately **not** normalized —
those alter what the source says, which is the thing the check exists to catch.

Wired into `LLMExtractOperator._assemble` only, which already holds
`input_text`. A quote that cannot be located is collected rather than raised on
immediately, so one repair hint names *every* offender and a single retry can
fix them all; the hint then travels the operator's existing `ExtractionError`
-> `repair_hint` -> RETRY path (the same seam the T0 follow-on uses), so no
runtime or validator change was needed. `validation.validate()` and
`l2.validate_patch()` were left alone as the task required — they are shared by
every operator and most have no source text.

The stretch landed too: a located quote now records `{"start", "end"}` in
`Evidence.location`, a field that was always `{}` before, so a committed
citation is machine-checkable after the fact.

**Verified against live model output, not just fixtures.** Re-running the
4-page press release that motivated the task (`deepseek/deepseek-chat`): all
five stages COMMIT, all 10 evidence spans located on the **first attempt** —
no retry, no false rejection — and every recorded offset resolves to the real
span. Only 1 of the 10 was byte-exact; the normalization is doing real work
(two spans contain PDF line breaks, one contains typographic quotes). That
false-rejection risk was the main hazard in this task, since a check that is
too strict silently destroys good extractions.

19 tests in `tests/test_provenance.py`, 100% coverage of `provenance.py`.
Unit: verbatim quotes locate at their real offsets; line-broken, typographic,
added-terminal-period, and comma-truncated quotes locate; fabricated,
paraphrased, word-dropped, case-changed, and empty quotes do not; a fabricated
quote ending in punctuation is not rescued by the trailing-punctuation
tolerance. Operator: a fabrication on every attempt commits nothing (state
stays v0, no citations); a fabrication repaired on attempt 2 commits, with both
attempts on the record (a retry is a real billed call under T5); the repair
hint names both offending spans; a located quote records resolvable offsets.

One documented boundary: `locate_span` answers presence only. A lone `"."` is
genuinely a span of the document and therefore locates. Judging whether a
quote is *substantive* is a separate concern, and inventing a minimum length
here would be an undocumented policy of its own.

`tests/test_extract_llm.py::test_extract_dedupes_shared_assumptions` used
quotes absent from its document; it is about assumption de-duplication, so it
now brings its own document rather than weakening the new invariant.

**Invariants held.** No direct `SemanticState` mutation — the extractor still
emits a `SemanticPatch`. `provenance.py` never calls a model. The check is not
applied to the deterministic `ExtractOperator`, whose `ev_001` is a legitimate
truncated span; `spc-demo demo` re-run and `DEMO.md` byte-identical.

---

## T9 — Live-run regression harness (record/replay cassettes) · ✅ DONE

**Why it existed.** Every LLM-path test drove the pipeline with hand-written
payloads that are, by construction, already well-formed. Real model output is
not, and T8 was found by running one real document by hand — nothing in the
suite could have found it. This closes that gap without putting a key or a
network in CI.

`src/spc_state/providers/cassette.py`: `RecordingProvider` wraps a live
provider and captures each completion **verbatim**; `ReplayProvider` feeds them
back in order, offline. `Cassette` is the on-disk format (versioned; provider,
model, `document_sha256`, and per-exchange `request_sha256` + response +
fingerprint + `TokenUsage`, so T5 accounting stays exercised on replay).

Three deliberate behaviours:

- **Exhaustion raises**, unlike `MockProvider`'s repeat-the-last. A pipeline
  that makes an extra call is a real change; handing it a stale completion
  would hide it.
- **Document identity is checked.** `ReplayProvider.from_path(..., document=)`
  refuses a cassette recorded against different text, so editing the fixture
  without re-recording fails clearly instead of as a confusing quote mismatch.
- **Prompt drift is reported, never fatal.** Each exchange stores a hash of the
  request it answered; `drifted_calls` names the ones that no longer match.
  Hard-failing would break the suite for any contributor without an API key,
  who cannot re-record. The staleness signal is asserted *in this repo*
  (`test_committed_cassette_matches_the_current_prompts`), where re-recording
  is cheap, and inspectable offline via `tools/record_cassette.py check`.

`tools/record_cassette.py` records (needs `OPENROUTER_API_KEY`, ~$0.002) or
inspects drift offline. Deliberately a script, not a `spc-demo` subcommand:
re-recording is a maintainer action, not a user-facing feature (same reasoning
as T6's no-CLI-flag decision).

**Two cassettes**, because a harness that only records success proves only that
the happy path works. Both are real `deepseek/deepseek-chat` runs over authored
fixture documents (not third-party text), each document carrying formatting a
model demonstrably mishandles:

- `analyze_five_stage.json` over `live_document.txt` — the clean path. 4
  exchanges, every stage committing first time; typographic quotes, an em dash,
  bullets with no terminal period, sentences broken mid-line.
- `analyze_retry_path.json` over `live_document_hyphenated.txt` — the **failure
  path**, hyphenated at line ends the way PDF extraction of justified text is.
  The model de-hyphenates when it quotes ("impair-\nment" -> "impairment"), T8
  refuses the unlocatable spans, and the extractor really retries twice: 10
  claims proposed with 6 unsourceable, then 6 with 4 unsourceable, then 5 that
  all locate — COMMIT. 6 exchanges. Coverage traded for provenance, which is the
  trade this engine exists to make.

Getting a genuine failure took two attempts. An all-uppercase filing was tried
first, on the theory that a model would re-case its quotes and trip T8's
deliberate case-sensitivity. It did not — the model quoted the caps faithfully,
so that fixture was discarded rather than committed. Useful evidence in its own
right: case-sensitivity is not costing false rejections in practice.

`--allow-uncommitted` was added to the recorder for failure paths, where a run
that commits nothing is the point rather than a mistake.

20 tests in `tests/test_live_replay.py`, 100% coverage of `cassette.py`. The
pipeline half replays genuine output through all five stages and asserts every
committed quote locates in the document (the T8 regression guard), that memo
citations resolve, that the cost ledger counts recorded usage, and that replay
is deterministic. The failure half asserts the extract step really took three
attempts, that both rejected proposals stay on the record, that the repair hints
named real unlocatable spans, that no span rejected on attempt 1 survives into
committed state, and that all three attempts are billed (T5) — checked against
the token usage summed straight from the cassette. One guard is worth naming:
`test_normalization_is_load_bearing_on_real_output` fails if *every* real quote
is byte-exact — otherwise T8's normalization would be untested dead weight and
this fixture would be proving nothing. That assertion cannot be written with
mocks, because a mock author simply writes quotes that match.

**Verified the harness actually fails, and found what only it catches.**
Mutating `locate_span` to exact matching turns 7 tests red; disabling T8's
rejection turns 6 red. For both, the mock-driven suite fires too. The clean
separation is **prompt drift**: changing one line of the extractor's schema hint
is caught only here (both staleness guards), and is completely invisible to the
other 252 tests — fixed mock payloads cannot notice that the question changed.
Cutting the extractor's retry budget from 3 to 2 turns 6 tests red here against
1 in the mock suite.

**Invariants held.** No operator or runtime change; the providers sit behind
the existing `LLMProvider` seam. Replay is offline and deterministic.
`spc-demo demo` re-run, `DEMO.md` byte-identical.

---

## T10 — Soft-hyphen handling in `locate_span` · ✅ DONE

**Why.** The T9 failure-path cassette put a number on a boundary T8 had left
open: a document hyphenated at line ends — what PDF extraction of justified
text produces — cost **half its claims** (10 proposed, 5 committed) because the
model de-hyphenates when it quotes and `locate_span` refused every such span.

**Tried both ways rather than guessed.** A hyphen before a break is genuinely
ambiguous: a soft one splitting a word (`impair-\nment` -> `impairment`) or a
real one in a compound that happened to wrap (`pre-\ntax` -> `pre-tax`).
Nothing short of a dictionary separates them, so `locate_span` now seeks a
quote under each reading in turn — `keep` (as written), `join` (hyphen and
break dropped), `rejoin` (hyphen kept, break closed) — applied symmetrically to
document and quote, `keep` first so an unambiguous quote pays nothing for the
ambiguity. Any reading that resolves is a faithful rendering of the same text;
none drops, adds, or reorders a word. U+00AD is folded away outright, being a
discretionary break rather than part of a word.

**Two boundaries, both found empirically and both tested.**

- *A hyphen must be attached to the preceding word.* An adversarial sweep over
  the three fixture documents (102 altered spans: dropped, swapped, added
  words, changed digits) found 4 wrongly accepted — all a standalone em dash
  between spaces, erased by the join reading, so a quote could drop or move it.
  Requiring a word character against the hyphen closed all 4; the sweep is now
  clean, and the case is pinned by a test.
- *A hyphen inside a word on one line is not forgiven.* Quoting
  `ausserplanmaessige` for `ausserplan-maessige` drops a character the source
  contains. A real model did exactly this, and it is now the T9 failure-path
  cassette.

**Cassette fallout, which is the harness working.** The change made the old
retry cassette misaligned — the extract step no longer needs its two rejected
attempts, so replay handed later stages the wrong recordings, and the staleness
guard caught it. `analyze_hyphenated.json` was re-recorded and now proves the
recovery on fresh live output (9 claims, first attempt, no retry, every span
resolving). A new German-language cassette restores the failure-path coverage
the change removed, and pins the in-word-hyphen boundary above.

7 new tests (4 unit, 3 replay), 100% coverage of `provenance.py` retained. A
now-unreachable empty-needle branch was removed rather than left uncovered.
Verified by mutation: collapsing the readings back to `keep` alone turns 5
tests red across both layers.

**Invariants held.** Pure, offline, deterministic; no operator or runtime
change. `spc-demo demo` re-run, `DEMO.md` byte-identical.

---

## T11 — Close the full-patch passthrough around the provenance check · ✅ DONE

**Why.** `_assemble` has a branch for output that is already a complete
`SemanticPatch`: it hands the patch to the validator rather than building one.
T8 put its check inside the assembly loop, so that branch never reached it —
and the validator is never given the source document. A model returning a
full patch could therefore commit a citation nobody had checked. Latent, not
observed: every live run so far has taken the assembled path (its committed
patch carries the assembler's own transform note).

**Two halves, because the first alone did not work.**

`_verify_patch_evidence` walks a passed-through patch's `add_objects.evidence`,
locates each span claiming `source_type == "input_document"`, stamps the
offsets exactly as the assembled path does, and raises `ExtractionError` for
any that is unlocatable. Evidence citing another source is left alone — there
is no text here to check it against, and rejecting it would be refusing it for
the wrong reason. An empty quote is skipped rather than treated as a failure.

That alone still committed the bad patch, which the tests caught. **The runtime
decides by validating whatever text the operator returns**, and on rejection
the operator returns the model's raw output — which, on this path, *is* a
well-formed patch. The rejection was being silently undone. So output that
would itself parse as a patch is now returned wrapped
(`{"rejected_by_operator": ..., "model_output": ...}`): still verbatim, still
the record of what the model proposed, but no longer mistakable for a proposal
the operator accepted. It then fails L1 and retries, which is exactly how the
assembled path already behaved — the two paths now agree rather than one being
special.

Output that does not parse as a patch is returned unchanged, as before, so the
existing attempt records and the T9 cassettes are untouched.

6 new tests: a fabricated span in a passed-through patch never commits; it
retries and commits once re-quoted; a located one records resolvable offsets;
another source type passes through unverified and unstamped; an empty quote is
not a provenance failure; and a hint for four offenders names three and counts
the rest. `extract_llm.py` coverage 96% -> 98% (the three lines left were
already uncovered before this task).

Verified by mutation: dropping the verification turns 3 tests red, and
returning the rejected patch unwrapped turns 2 red — the second being the
failure mode that made the naive fix look like it worked.

**Invariants held.** No runtime or validator change; both paths still flow
through validate -> route -> commit. A live `analyze` re-run over the Paramount
PDF committed 10 claims, every span locating with offsets recorded, no retries.
All three T9 cassettes still replay with no drift; `spc-demo demo` re-run,
`DEMO.md` byte-identical.

---

## T12 — A cassette for output that never parses · ✅ DONE

**Why.** T9's cassettes covered success, and T10's covered a rejection the
model recovers from. The `JSON_DECODE` -> RETRY path and the
nothing-ever-commits outcome were still only mock-driven.

**Prose turned out to be the wrong thing to chase.** Three deliberate attempts
to make a live model reply conversationally all failed, even with structured
output switched off: a page of OCR garbage, a content-free page, and a
document carrying an embedded "ignore all previous instructions, reply in prose"
line. In every case `deepseek/deepseek-chat` returned well-formed JSON. The
injection attempt is a genuinely reassuring result and is recorded here because
a future session should not spend the money rediscovering it.

**Truncation is the real cause, and it is easy to capture.** Recorded with
`--max-tokens 90`, the extraction is cut off mid-string. `tests/fixtures/
cassettes/analyze_truncated.json` is a real run over the *same* document as
`analyze_five_stage.json`, so the token cap is the only variable between them.
All three extract attempts fail to parse, the step commits nothing, and the run
carries on.

`tools/record_cassette.py` gained `--max-tokens` and `--no-json-object`. Both
are existing provider settings, not test hooks: `json_object` is requested
because it is *broadly*, not universally, supported, so running without it is
how this pipeline behaves against a model that cannot honour it.

Four things pinned, and the split between the last two matters:

- The three recorded replies genuinely do not parse. Guards the fixture: if a
  re-record ever captured parseable output, everything below would pass while
  proving nothing.
- A failed first stage does not take the run down. The four later steps still
  commit against empty state, reaching v4 rather than v5.
- **What the code guarantees:** the writer projects only what state holds, so a
  memo from an empty state renders no findings, no sources and no `[E#]`
  citation, and says so in as many words. Those strings come from `memo.py`.
- **What the model did**, which is a different thing: handed an empty state the
  planner hedged — "no recommended course of action due to insufficient data",
  zero confidence, no supporting claims. That hedge is *not* a property of this
  code; the recommendation line renders whatever hypothesis was committed.
  Pinned separately so a re-record that starts asserting something confident
  out of nothing is visible rather than silently shipped inside a memo.

**A T5 boundary, now shown with real money rather than described.** The three
billed extract attempts appear nowhere in the cost ledger, because it holds one
row per `TransformRecord` and a step that never commits produces none. The test
asserts their absence, so closing that gap becomes a deliberate change with a
test to update.

Verified by mutation: suppressing the memo's empty-state notices turns 1 test
red, and stopping the pipeline after a failed extraction turns 8 red.

**Invariants held.** No `src/` change at all — this task is a fixture, tests and
two recorder flags. `spc-demo demo` re-run, `DEMO.md` byte-identical.

---

## T13 — Attempt-level cost accounting · ✅ DONE

**Why, with the number.** T5 keyed the ledger to `TransformRecord`, so a step
whose every attempt failed produced no record and its spend appeared nowhere.
T12 pinned that as a boundary; this closes it. Replaying
`analyze_truncated.json`, where the extraction loses three attempts to
truncated replies:

| | tokens |
|---|---|
| Reported before | 1,001 |
| Actually spent | 3,651 |

The failed extraction was the *most expensive step in the run* — three attempts,
each carrying the whole document — and the ledger called the other four steps
the total. It understated by 3.6x, and always in the same direction: the worse
a run goes, the more it under-reports.

**Where the numbers now come from.** `StepOutcome` carries `usage`,
`fingerprint` and `operator`, set on every LLM step whether or not anything
committed. That is the fix: the cost was always computed in the loop (summed
across attempts since T5) and then thrown away when there was no patch to hang
it on. `build_cost_ledger` reads the step rather than the record, falling back
to the record for a patch that arrived carrying its own usage. A deterministic
step still has no fingerprint and still contributes nothing.

**Attribution and reconciliation stay separable**, which is the part worth
getting right. Each row gains `attempts` (billed calls covered), and
`committed`; `transform_id` is `None` when nothing committed, because inventing
a synthetic id would imply a transform that does not exist. The ledger gains
`uncommitted_tokens` and `uncommitted_estimated_cost_usd`. Filter to committed
rows to ask what the state cost; sum every row to ask what the provider will
bill.

Two tests that pinned the old gap were rewritten rather than deleted — that was
their purpose, and the T12 entry said so.

New/updated tests in `test_cost_ledger.py` and `test_live_replay.py`: a step
that commits nothing gets a row, marked uncommitted, unnamed, covering both
its billed calls; a committed step is still named and marked; and on the real
cassette the row matches the recorded usage **to the token**, with committed
and uncommitted spend separable from the same ledger. 100% coverage of
`cost_ledger.py`.

Verified by mutation: reverting to `TransformRecord`-only rows turns 3 tests
red, and hard-coding `committed` true turns the same 3 red.

**Invariants held.** No operator or validator change; the runtime change is
three fields on a dataclass, no control flow. `cost_ledger.json` gains fields
and no run commits it (`runs/` is gitignored); the deterministic demo writes no
ledger at all, and `DEMO.md` is byte-identical.

---

## T14 — Evidence reliability comes from the source, not from the model · ✅ DONE

**The defect.** `Evidence.reliability` decides how sceptical the rest of a run
is: the Retriever opens an evidence-gap question for any under-confident claim
not resting on a `HIGH` span, and the memo flags a finding supported only by
`LOW` ones. It arrived from the model, as an `evidence_reliability` field in the
extraction schema — which asks a model to grade a document's trustworthiness
from inside that document, the one place the answer is not, and lets the
extraction that most wants scrutiny exempt itself from it.

It is not a theoretical worry. The model's own self-grades, read back off the
cassettes recorded before this change — every one of these documents an
announcement written by an interested party:

| recording | spans graded `high` by the model |
|---|---|
| `analyze_five_stage` (merger press release) | 6 of 11 |
| `analyze_hyphenated` | 8 of 9 |
| `analyze_retry_path` | 7 of 8 |

On the live Paramount/WBD press release earlier in this project it was 10 of 10,
and the run recommended proceeding at 90%.

**The fix.** Reliability is a property of *where the text came from*, so the
caller declares that once and the operator derives the rest. `source_types.py`
holds a coarse taxonomy and the mapping: `HIGH` only where someone is
accountable for the statement being true (a legal duty of accuracy, or an
independent check) — regulatory filing, audited financials, court record,
official statistics, peer review; `LOW` where the author has a stake in the
conclusion and nobody checked it — press release, marketing material, opinion,
social media; `MEDIUM` for the disinterested-but-unverified middle. The
`evidence_reliability` field is gone from the prompt, and
`LLMExtractOperator(source_type=...)` stamps the derived value on both routes
in — the assembled one and the full-patch passthrough, where a model-authored
patch asserting `high` for itself would otherwise have kept it. `spc-demo
analyze --source-type` exposes it.

**An undeclared source is `MEDIUM`, deliberately.** `LOW` would assert something
about the source nobody established, and flag every finding of every
unclassified run as weakly supported. `HIGH` is the free promotion this task
removes. `MEDIUM` is the honest answer and still denies the `HIGH` that silences
the Retriever — nothing reaches `HIGH` without someone saying where the text
came from.

**What it changes, measured.** Same recording, same claims, same confidences —
only the declaration differs:

| declared as | evidence-gap questions | findings flagged weakly supported |
|---|---|---|
| `regulatory_filing` | 0 | 0 |
| *(undeclared)* | 4 | 0 |
| `press_release` | 4 | 8 |

Declared for what it is, the Northwind merger release stops passing its own
enterprise-value figure off as settled: eight findings gain a **Weakly
supported** marker, including three at 100% confidence.

**Stated honestly:** replaying the *old* recordings under the old and new rules
gives the same gap count on all three. The model's self-graded `HIGH` spans
happened to support claims it was already confident about, and the Retriever
does not question those whatever their evidence. The gate is real — the table
above is the same pipeline over the same recording — but on those three
documents it was not yet the thing costing questions. What it was costing was
the memo's weak-support flag, and the ability to tell a filing from a press
release at all.

New `tests/test_source_types.py` (the taxonomy: every member has a decided
weighting, the `HIGH` set is exactly the accountable one and not a superset,
unknown strings are weighed cautiously rather than raising) and
`tests/test_evidence_reliability.py` (the wiring: the declaration sets every
span on both routes in, a payload asserting `high` is ignored, and the
Retriever's questions follow from the declaration — press release 2, filing 0,
undeclared 2 on the same claims).

Verified by mutation: restoring the model's self-grade turns 6 tests red;
dropping the passthrough overwrite, 1; promoting the undeclared default to
`HIGH`, 5; weighing a press release `MEDIUM`, 5.

**Cassettes re-recorded.** Removing the field changed the extract prompt, which
is exactly what `test_committed_cassettes_match_the_current_prompts` exists to
catch. All four were re-recorded against `deepseek/deepseek-chat` and each
still shows the property it was made for: the five-stage run commits every
stage first time, the hyphenated one loses no claims, the German one is refused
once and repaired, and the truncated one fails all three attempts. One
assertion was loosened in the process — the new recording hedges with
"insufficient information" where the old said "insufficient data", and pinning
the synonym was pinning the model's prose style rather than its refusal to
invent.

**Invariants held.** No validator, runtime or state-model change; the
deterministic `ExtractOperator` is untouched, so `DEMO.md` is byte-identical.
`Evidence.source_type` stays a free-form string, and `input_document` — what
every earlier run and the demo write — is still read as "the document under
analysis".

---

## T15 — Hold a recommendation to what it rests on · ✅ DONE

**The defect, with the numbers.** T14 made the pipeline honest about its
*sources*. Run `paramount_006` — the Paramount/WBD merger release, declared
`--source-type press_release` — committed all ten spans as low-reliability,
opened three evidence-gap questions, and flagged every one of its ten findings
**Weakly supported**. It still opened at *Confidence: 90%*, unchanged from the
run before T14.

Two structural causes, both confirmed in that run's own record:

1. **Nothing re-derived a hypothesis after its support moved.** The planner
   writes it at step 2; the critic adjusts claims at step 3. In that run the
   critic lowered `claim_006` from 0.80 to 0.65 — "a high estimate" — and the
   recommendation citing it did not move. Stale by construction precisely when
   the critic did its job.
2. **Nothing related it to its support at all.** The `CRITIC` slice carries no
   hypotheses; the critique transform's `read_set` was four claim ids. The
   recommendation was the one object in committed state no operator read.

**The fix.** `operators/calibration.py` — `CalibrationOperator`, deterministic,
model-free, free to run and identical on replay, in the mould of
`RetrieverOperator`. It runs **last**, so the critic has already moved the
claims beneath it, and proposes a patch capping any hypothesis above what its
support can carry:

```
ceiling(h) = min over c in h.supporting_claims of
                 c.confidence * reliability_factor(c)
```

Weakest link across claims, because four confident restatements of a press
release must not outvote the one claim that was actually questioned — an
average would have read 0.79 where the weakest link reads 0.39. **Best span
within** a claim, because one solid source is enough to ground it. Factors
`HIGH` 1.0, `MEDIUM` 0.8, `LOW` 0.6; a claim citing no evidence is treated as
the lowest tier rather than as zero (three buckets cannot express a finer
distinction, and the Retriever already opens a *high* priority gap for exactly
those). A hypothesis citing no claims gets 0.0. Results are floored to two
places, so the rounding never resolves in the recommendation's favour.

Two rules hold whatever the constants become: **it only ever lowers** — raising
a confidence because the support looks strong would be inventing certainty,
which is the failure mode — and **every change is recorded** as an
`UpdateObject` plus a matching `ConfidenceChange` naming the binding claim, the
same mechanism the critic uses.

**The projection gap is closed** by adding hypotheses to the `VERIFIER` slice,
whose stated job (§14.2) is already "claim/evidence alignment, provenance,
**confidence sanity**" and which already carries every claim and every span the
ceiling needs. No new perspective invented; the contradiction operator's
`read_set` is `sorted(view.claims)` and is unaffected.

**Measured.** Same recorded run, same claims, only the declaration differing:

| declared as | planner proposed | committed |
|---|---|---|
| `regulatory_filing` | 0.85 | **0.85** — uncapped |
| `press_release` | 0.85 | **0.60** |

And live, `paramount_007` over the same PDF as `paramount_006`: the planner
proposed **0.95**, the memo now opens at **60%**, and the receipt carries
`changed hypothesis hyp_001: confidence 0.85 → 0.6` beside the reason
naming `claim_001`.

`tests/test_calibration.py` (17 tests): the ceiling is the weakest link and not
an average; reliability damps it, pinned per tier; the best span within a claim
carries it; an unsourced claim is the lowest tier; a recommendation citing
nothing is 0.0, and one citing a claim outside committed state is too;
confidence is never raised; a hypothesis already within its ceiling is
untouched and writes nothing; every cap names the claim that bound it and not
the ones that did not; the operator declares only ids its projection holds; it
records no usage or fingerprint and replays byte-identically. Against the
recorded cassette: the press-release run commits below what was proposed and
the memo opens with the capped number, the same run read as a filing is left
alone, and the move is visible in the receipt.

Verified by mutation: an average instead of the weakest link turns 3 tests red;
letting it raise as well as lower, 2; ignoring reliability, 7; an unsupported
hypothesis reading 1.0, 1; taking the weakest span within a claim, 1; a generic
reason that does not name the binding claim, 3; dropping hypotheses back out of
the `VERIFIER` slice, 13.

**Explicitly still open.** The extractor's own claim confidences — `claim_001`
above is the binding limb at **1.00** off a press release, and the cap is only
as good as that number. That is the same disease one layer down and wants its
own task.

**Invariants held.** No direct `SemanticState` mutation; no validator or
runtime change. The operator is not in `spc-demo demo` (same reason T1 kept the
Retriever out), so `DEMO.md` is byte-identical. `analyze` is now six stages, so
committed state reaches v6 — the cassettes needed no re-recording, since the
new stage makes no provider call.

---

## T16 — A claim is not certain because the document says so · ✅ DONE

**The defect, with the numbers.** T14 stopped the model grading its own
sources; T15 stopped it grading its own recommendation. The extractor still set
`Claim.confidence` itself, and across five real runs **32 of 48 claims (67%)
committed at exactly 1.00** — not a heavy tail, a spike at certainty. The
mechanism was one confusion, visible in the data: in every cassette the claims
marked `observed` and the claims at 1.00 were the **same set** (6 of 6, 6 of 6,
7 of 7). The model read "I can quote this" as "this is certain", but a verbatim
span establishes that the *document* says so.

What that produced on `paramount_007`, all at 1.00 and `observed`: "Paramount
**will acquire** Warner Bros. Discovery" (a future event contingent on
approvals), "the combined company **will own** a film library of more than
15,000 titles" (a company that does not exist yet), and "one of the industry's
**most compelling** portfolios of sports rights" (the seller's own evaluative
language). The source says the deal needs "regulatory clearances and approval
by WBD shareholders"; that sentence was never extracted, so state asserted the
acquisition **will** happen, at certainty, and held nothing about what it
depends on.

**The fix.** `CalibrationOperator` (T15) gained a first pass: a claim is damped
by the best source it cites, using the factors it already applied one layer up.

```
ceiling(c) = c.confidence * reliability_factor(c)
ceiling(h) = min over c in h.supporting_claims of ceiling(c)
```

**The damping happens once**, which is the decision T16 forced and settles. The
hypothesis rule no longer multiplies by the factor itself — it reads the claims
*after* their own discount and takes the minimum. Applying it at both layers
would discount a press-release recommendation twice (0.6 x 0.6 = 0.36), which
is not a position anyone took. Composed this way the committed recommendation
is **arithmetically identical** to what T15 alone produced; what is new is that
the claims' own numbers are corrected, and recorded, too. That identity is
pinned as a test, since it is exactly what a careless future edit would break.

**It is a discount, not a ceiling**, and that was a real choice. The factor
scales rather than clips, so a claim stated at 0.40 on a press release carries
0.24 and not 0.40-because-it-was-already-low. The two numbers measure
independent things — the model's confidence is about the *content*, the factor
is about the *source* — so they compose: a company's own estimate of an
uncertain outcome is worth less than a disinterested party's identical
estimate. The cost, stated plainly, is that **every** claim from a non-`HIGH`
source moves, not only the overconfident ones. The alternative (`min(conf,
factor)`) is a coherent position; it is not this one, and swapping it turns 7
tests red rather than passing quietly.

**Measured, live.** `paramount_008`, the same PDF as `paramount_007`, declared
`press_release`:

| | proposed by the extractor | committed |
|---|---|---|
| claims at 1.00 | 5 of 10 | **0 of 10** |
| highest claim confidence | 1.00 | **0.60** |
| recommendation | 0.90 | **0.45** |

with `claim_001: 1.00 -> 0.60 — "low-reliability evidence carries 60% of a
claim's stated confidence"` and `hyp_001: 0.90 -> 0.45 — "it rests on claim_004
(confidence 0.45 once calibrated…)"` on the record. Read as a
`regulatory_filing` instead, the same recorded run keeps six claims at 1.00 and
the operator writes nothing at all: a source-sensitive discount, not a blanket
haircut.

New `tests/test_claim_calibration.py` (14 tests): certainty survives only where
the source can carry it, pinned per tier; an accountable source leaves a claim
untouched; an already-modest claim is still discounted (the design decision,
argued in the test); confidence is never raised; an unsourced claim is damped
like the weakest source; the best span a claim cites decides its factor; claims
are discounted independently of one another; every change records the source
and the factor that moved it; the factor is applied exactly once; the
recommendation reads the *capped* claim, not the proposed one; and against the
recorded cassette — no press-release claim commits at certainty, the same
recording read as a filing keeps its 1.00s, and the committed recommendation is
unchanged from T15 at both declarations.

Verified by mutation: not capping claims at all turns 18 tests red; applying
the factor twice, 15; reading pre-cap claim values for the hypothesis, 10;
making the claim rule `min()` instead of a product, 7; sending an unsourced
claim to zero, 2.

**Still open, and unchanged.** No reliability factor makes `will acquire` stop
being typed as an *observation*, or marketing language stop being a *claim*.
The honest fix is splitting the model so `observed` means "observed in the
source" and warranted belief lives on its own field — a state-model change that
wants its own ⚠ task with sign-off.

**Invariants held.** No direct `SemanticState` mutation; no validator, runtime
or state-model change. The deterministic `ExtractOperator` is untouched and the
operator is not in `spc-demo demo`, so `DEMO.md` is byte-identical. No prompt
change, so the cassettes needed no re-recording.

---

## T17 ⚠ — Reading a document is not observing the world · ✅ DONE

**Sign-off given 2026-09-12**, per the ⚠ convention: this relaxes a v0.1
constraint by adding a member to `EpistemicStatus`.

**The defect.** `OBSERVED` was doing two jobs. Reading a press release
establishes **that the press release says so**; it establishes nothing about
the merger. The extractor only ever has the first and was committing the
second. Across five real runs the claims marked `observed` and the claims at
confidence 1.00 were the *same set*, and among them:

> "Paramount **will acquire** Warner Bros. Discovery" — `observed`, 1.00

A future event, contingent on regulatory clearances the same document names,
recorded as something someone saw. T14 and T16 priced that claim down; neither
could stop the memo telling a reader it had been **observed**, which is not a
hedge they can discount but a false statement about where the claim came from.

**The fix.** `EpistemicStatus.REPORTED` — "a source states this; nobody here
verified it". It is **derived, not asked for**, the same move as T14/T15/T16:
the prompt no longer offers `observed`, and a model that says it anyway is
corrected rather than believed, on **both** routes in (assembled and full-patch
passthrough — the second way in that T8, T11 and T14 each had to close).
`VERIFIED` is mapped down for the same reason: nothing in the run corroborated
anything.

`OBSERVED` keeps its place in the vocabulary for an operator that genuinely
sees the thing itself, and `VERIFIED` for a future corroboration step that
promotes a reported claim once a second accountable source carries it. Neither
is emitted today, and the enum now says so.

**`REPORTED` is grounded, deliberately, and that non-change is pinned.**
Groundedness (`projection/builder.py`, `_UNGROUNDED`) is about provenance, and
a reported claim has some: a named source says it, the span is on record. What
it lacks is *first-hand* observation, which the label now states out loud
rather than a projection filter re-litigating it — how much the source is worth
is already priced by T14 and T16. Putting `REPORTED` in `_UNGROUNDED` would
reclassify every extracted claim as weak overnight; that turns 5 tests red
rather than passing quietly.

**Measured, live.** `paramount_010`, the Paramount/WBD release declared
`press_release`: **10 of 10 claims commit as `reported`, none as `observed`**,
and every line of the memo now reads `_(confidence 60%, reported)_`. The same
run also extracted, for the first time across ten runs, the conditionality the
source states: *"The transaction is expected to close in Q3 2026, subject to
regulatory clearances and WBD shareholder approval."*

New `tests/test_epistemic_grounding.py` (15 tests): only the two statuses a
reader cannot reach are rewritten and every other passes through; the prompt no
longer offers `observed`; a model claiming observation is corrected on both
routes in; an omitted status defaults to `reported` rather than `inferred`;
inference still reads as inference; a reported claim is grounded and not weak;
and against the recorded cassette — no committed claim is `observed`, and the
memo says `reported` where it used to say `observed`.

Verified by mutation: believing the model's `observed` again turns 5 tests red;
dropping the passthrough correction, 1; defaulting an omitted status to
`inferred`, 1; flattening `inferred` into `reported`, 2; treating `REPORTED` as
ungrounded, 5.

**Not fixed, and it is worth being plain.** The relabelling does not make
"one of the industry's **most compelling** portfolios" stop being extracted as
a claim — but it does stop the state asserting it. As a `reported` claim at 60%
it says "the seller says this", which is true and is what a reader needs.
Whether the extractor should decline evaluative language altogether is a
separate question about what counts as a claim.

**Invariants held.** Adding an enum member is additive, so stored state and the
deterministic `ExtractOperator` are unaffected and `DEMO.md` is byte-identical
— the demo's claims are hand-written against a fixture and its artifacts are a
release gate, so the rule is scoped to the path where a model is the author
(pinned as a test). No validator or runtime change; `L2.CLAIM_MISSING_PROVENANCE`
still requires evidence for a `reported` claim, correctly. The prompt changed,
so all four cassettes were re-recorded and each still shows the property it was
made for.

**Test hygiene, while re-recording.** Four replay assertions that pinned exact
numbers (0.85, 0.60, "six claims at 1.00") had now broken on three successive
re-records and proved nothing about the rules when they passed. They were
rewritten to derive their expectations from the run — the recommendation equals
the weakest claim it cites, a filing discounts no claim where a press release
discounts all of them — which is what those tests were always trying to say.

---

## T18 — Several sources, one semantic state · ✅ DONE

**Why.** A run could hold only one document, and that quietly capped the whole
pipeline. The verifier looked for contradictions inside a single press release,
where a company does not contradict itself. T14's reliability tiers never
arbitrated anything, because every span in a run shared one source type. And
nothing could emit `VERIFIED`, since corroboration needs a second source to
corroborate with.

The blocker was mechanical: the extractor mints `claim_001`, `ev_001`,
`assumption_001` per run, and L2 refuses a second extraction into the same state
with `L2.DUPLICATE_OBJECT_ID` — correctly. Each extraction now mints in its own
namespace (`d2_claim_001`), declares its own `source_type`, and records its own
`source_id`. **Nothing downstream changed at all**: the planner, critic,
retriever, verifier and calibrator read committed state, so they compare across
sources for free.

`SourceType.REGULATORY_DETERMINATION` (HIGH) was added for the case this
exposed: a regulator's *own* finding is not a `regulatory_filing`, where the
interested party is still the author.

`spc-demo analyze --also-input PATH --also-source-type TYPE`, repeatable and
positionally paired; a mismatched count is refused rather than guessed at.

**What the first real run showed.** `paramount_dual_001` — the Paramount/WBD
press release (`press_release`) plus the DOJ Antitrust Division's statement
closing its investigation (`regulatory_determination`), 19 claims, 20,399
tokens, $0.0035:

| | claims | committed confidence |
|---|---|---|
| press release | 13 | all ≤ **0.60** |
| DOJ determination | 6 | **0.85–0.95**, untouched |

T14 and T16 arbitrating between two sources, which a single-document run could
never do.

**And the defect it exposed, which is the point of having run it.** The
recommendation rests on `claim_001, 003, 004, 009, 010` — **every one of them a
press-release claim at ≤0.60**. The six DOJ claims contributed nothing. The
state now holds better evidence than it did and still builds its conclusion out
of the weakest material in it.

Sharpest form: the Retriever committed
> *"What stronger source would confirm 'The deal may face risks from regulatory
> clearances and stockholder approval'?" (claim_013 rests only on
> lower-reliability evidence.)*

while `d2_claim_001`, at 0.95 on the regulator's own determination, sits in the
same state answering it. The question and its answer are both committed and
nothing connects them. The verifier found **0** contradictions — fairly, since
the DOJ cleared the merger — but it also missed that the DOJ statement reveals
Netflix had agreed to acquire WBD in December 2025 and Paramount outbid it, a
material fact the press release omits entirely.

**That is the corroboration operator's specification, written by a real run
rather than guessed at**, and it is deliberately left for its own task.

New `tests/test_multi_document.py` (7 tests): a second document commits into the
same state; each source mints ids in its own namespace; each keeps its own
weight and is separately attributable; provenance is checked against the *right*
document; the later stages are unchanged and see every source; and a
single-document run is byte-for-byte unchanged. Verified by mutation: removing
the id namespacing turns 5 tests red.

**Invariants held.** No validator, runtime or state-model change; the single
document path is untouched (same ids, same stage count), so every committed
cassette still replays and `DEMO.md` is byte-identical. No prompt change, so no
re-record.

---

## T19 — Corroboration: what two sources independently say · ✅ DONE

**Specified by T18's run, not guessed at.** With the Paramount/WBD press
release and the DOJ determination in one state, the Retriever asked *"what
stronger source would confirm this?"* about a claim the regulator's finding
answered at 0.95 in the same state, and nothing connected them.

`operators/corroboration_llm.py` — `LLMCorroborationOperator`. Whether two
differently-worded sentences assert the same thing is a semantic judgement, so
the model supplies the pairings and the operator owns every consequence. Two
passes, the precision gate `LLMContradictionOperator` established: propose,
then a skeptic whose default is "these are different claims". A false
corroboration is worse than a missed one here, because it does not merely add a
note — it lets a claim inherit warrant it never earned.

**It never touches confidence, and that is the design.** T15 and T16 hold that
calibration only ever lowers. Corroboration needs no exception: it changes what
a claim *rests on*, and the calibrator's existing rule reprices it. A claim
ceilinged at `confidence x reliability_factor(best evidence)` and cited only to
a press release carries 0.54; once a regulator's span genuinely supports it,
the best evidence it cites is `HIGH` and the **same untouched rule** lets it
carry 0.90. No new arithmetic and no exception to a stated invariant — the
composition is pinned as a test.

`REPORTED` is promoted to `VERIFIED` only when the corroborating source is
**accountable**. Two press releases agreeing is two interested parties telling
the same story, which is what T17 reserved `VERIFIED` *against*. Only across
sources, and one direction: the better-sourced claim corroborates the weaker.

Runs between extraction and the planner, so the planner reasons from what the
sources jointly establish. **Not added at all for a single-source run** — there
is nothing to corroborate across, and a stage that always answers "none" costs
a real call and would make every committed cassette stale for nothing.

**A defect this found in `commit`, not in the operator.** A patch arrives as
JSON, so an `UpdateObject.to_value` for a typed field is whatever JSON can
carry. `model_copy(update=...)` assigns without validating, so setting
`epistemic_status` to `"verified"` left the raw **string** sitting where an
`EpistemicStatus` belongs — comparing unequal to the enum, with only a pydantic
serializer warning much later to hint at it. No operator had ever updated an
enum field, so nothing had caught it. `_apply_update` now round-trips the
object through validation, which coerces the value and refuses one the model
cannot hold.

**Measured live, and the honest result is mixed.**

`paramount_corrob_001` (press release + DOJ determination): **0
corroborations**. A true negative, not a failure — the two documents assert
different things about the same transaction. The press release is deal terms
($31/share, $6bn synergies, 15,000 titles, funding); the determination is
competition analysis (SVOD, linear, theatrical, labour). Nothing in one asserts
what the other asserts.

That corrects an assumption in T18's write-up: **corroboration is not the
payoff from a second source of a different kind — coverage is.** The DOJ
statement contributed eight claims at `HIGH` that the press release never made,
including the Netflix bidding war it omits entirely, and the recommendation now
cites them.

`paramount_corrob_002` (both companies' press releases + the DOJ determination,
35 claims, $0.0049) is the case corroboration is actually for, and it fired:

> `claim_005` *"expected to close in Q3 2026, subject to regulatory approvals
> and WBD shareholder approval"*
> **corroborates** `d2_claim_005` *"expected to close in Q3 2026, subject to
> customary closing conditions"*

and **did not promote it** — both sources are press releases. The accountable
-source rule holding on real data, not only on a mock. The overlap was smaller
than it looks: the two extractions picked largely different facts, and the one
genuine duplicate was the one found.

**Still unproven on real data:** promotion to `VERIFIED` needs two sources
asserting the *same* fact where one is accountable. Neither live pairing
produced that, so it is covered by tests and not yet by a run.

New `tests/test_corroboration.py` (10 tests). Verified by mutation: allowing
same-source pairs turns 1 test red; promoting regardless of source, 1; skipping
the skeptic pass, 1; choosing direction by id instead of strength, 4; and
reverting `commit` to the unvalidated assignment, 2.

**Invariants held.** No state-model change. Single-source runs are untouched —
the stage is not added, so every cassette still replays and no prompt changed.
`DEMO.md` byte-identical.

---

## T20 ⚠ — One status cannot hold three facts · ✅ DONE

**Sign-off given 2026-09-13**, per the ⚠ convention.

**What landed.** `EpistemicStatus` is five members and one question. `VERIFIED`
and `CONTRADICTED` are gone from it; a `Claim` carrying either on disk migrates
to `reported` at load, on a `field_validator` rather than in a store, so every
route in gets it — both backends, a patch carrying a legacy value, and a model
that answers `verified` anyway.

Support and conflict are derived in the new `src/spc_state/epistemics.py`:

- `corroboration_of(claim, evidence)` → `UNCORROBORATED` / `CORROBORATED` /
  `VERIFIED`, read from the spans a claim cites and the sources behind them;
- `is_contested(claim_id, contradictions)` → whether an **unresolved**
  `Contradiction` names it.

**T19's promotion write is deleted**, as predicted: `LLMCorroborationOperator`
already attached the corroborating span and wrote the `Relation`, so the label
was redundant bookkeeping over the same fact. The operator now writes exactly one
field, `supporting_evidence`, and a test pins that the `epistemic_status` update
is *gone* rather than merely agreeing with the derived answer.

**The higher bar, as specified.** `Evidence.derives_from` names the `source_id` a
document was written off; `sources_are_independent` walks the chain (transitively,
cycle-safe) and `_candidates` drops any pair that is not independent, replacing
the old `source_a == source_b`. Two documents off a *common* origin stay
independent of each other — the rule is ancestry, not shared ancestry — and that
choice is pinned by a test so it stays a decision. Undeclared lineage counts as
independent; `--also-derives-from` on `spc-demo analyze` declares it, validated
against the run's real source ids because a typo'd parent silently buys back the
independence the flag was passed to deny.

**Five sites became two properties.** `_UNGROUNDED` and `_PROVENANCE_FREE`
(`projection/builder.py`), `_PROVENANCE_FREE_STATUSES` (`validation/l2.py`) and
the `SPECULATIVE` comparison in `evaluation/metrics.py` are now
`EpistemicStatus.is_grounded` and `.needs_provenance`. The metrics one was
carrying a real bug: §20.2 counted a `speculative` claim as having declared its
provenance but not an `assumed` one, although L2 has always exempted both for the
same reason. `metrics.py:106` is left alone deliberately — it asks whether the
demo quantified uncertainty, a genuine one-member question, not axis recovery.

**Measured.** 429 tests (was 425 at the start, 388 before T20's spec was
written). `DEMO.md` byte-identical: the deterministic `ExtractOperator` emits
only `OBSERVED` and `INFERRED`, the demo has no corroboration stage, so every
demo claim derives `UNCORROBORATED` and renders exactly as before — including
after the `metrics.py` correction, which was checked against the demo rather than
assumed safe.

**Verified by mutation.** Ignoring lineage turns 3 red; removing the migration 4;
re-introducing the promotion write 3; conflict ignoring contradiction status 2;
`VERIFIED` dropping its accountability requirement 2; `needs_provenance`
forgetting `ASSUMED` 2; `is_grounded` admitting `INFERRED` 2; the extractor
failing to stamp declared lineage 1 on the assembled route and 2 on the
passthrough.

That last pair was a **real gap found by mutation, not by review**: the first
draft wired `derives_from` end to end and nothing tested it, so an extractor that
quietly stopped stamping it would have gone unnoticed — and the consequence is
exactly the failure T20 exists to prevent. Three tests now cover it, including a
patch that asserts its own independence and is overwritten.

**A regression guard was relocated, not dropped.**
`test_a_typed_field_update_commits_as_its_real_type` pinned a defect in
`runtime/commit.py` — a typed field updated from JSON committed as a raw string —
found through T19's promotion, which was the only operator updating an enum
field. Retiring the promotion would have silently retired the test with it, so it
moved to `tests/test_commit.py` and pins the commit rule directly. The defect is
in `commit`, and the next operator to update a typed field would meet it again.

**Schemas regenerated.** `python -m spc_state.models.schema_export schemas`. The
diff also picks up a `TokenUsage` block missing since T5 — the committed schemas
had drifted before this task and nothing checks them, which is worth a test one
day.

**Still true, and still out of scope.** The model still judges whether two claims
assert the same thing. Independence and accountability are structural now; the
match is not, and it is the last self-judgement in the T14–T20 arc. The
corroboration docstring says so rather than letting a derived `VERIFIED` read as
more than it is.


---

### The spec this was built from

**Required sign-off.** This changes the membership of `EpistemicStatus` and adds
a field to `Claim` and `Evidence`. T16 deferred exactly this — "splitting the
model so `observed` means 'observed in the source' and warranted belief lives on
its own field ... is a state-model change: raise it as its own ⚠ task with
sign-off, do not smuggle it in here." This is that task.

**Why, with what is in the tree.** `EpistemicStatus` has seven members and they
do not answer one question. They answer three:

| axis | the question it answers | members today |
|---|---|---|
| **acquisition** | how did this enter state? | `OBSERVED` `REPORTED` `INFERRED` `ASSUMED` `SPECULATIVE` |
| **corroboration** | how well is it supported? | `VERIFIED` |
| **conflict** | does anything contradict it? | `CONTRADICTED` |

A claim has a value on all three **at once**. One field holds one, so every
write on a second axis destroys the first. Both failure modes are already in the
tree:

- **`CONTRADICTED` is dead.** It appears in `models/enums.py:47` and in one
  parametrised test case. Nothing emits it — because T3 gave conflict a
  first-class `Contradiction` object carrying both claim ids, a type and a
  status. The object is the right shape; the enum member is the sketch it
  superseded, never removed.
- **`VERIFIED` overwrites `REPORTED`** (`operators/corroboration_llm.py:411`). A
  corroborated claim is *still reported* — it was read out of a document, and
  that does not stop being true because a second source agreed. T19 trades a
  fact about acquisition for a fact about support, and the receipt loses the
  first.

The consumers already work around the shape. **Five sites hand-maintain a subset
of the enum to recover an axis the type does not expose**: `_UNGROUNDED`
(`projection/builder.py:49`), `_PROVENANCE_FREE` (`:54`),
`_PROVENANCE_FREE_STATUSES` (`validation/l2.py:54`), `_UNAVAILABLE_TO_A_READER`
(`operators/extract_llm.py:115`), and two inline comparisons in
`evaluation/metrics.py:106,178`. Every member added to the flat list is an audit
of all five, and a missed one fails silently.

That is the case against simply adding members. The list is not too short; it is
the wrong shape, and lengthening it multiplies a defect that already costs five
maintained subsets and one dead value.

**The fix — store one axis, derive two.**

Store **acquisition** only. It is a fact about what an operator did at commit
time, and nothing downstream can recover it:

```
OBSERVED     an operator saw the thing itself
REPORTED     a source states it
INFERRED     derived from other claims in state
ASSUMED      taken as a premise
SPECULATIVE  proposed without warrant
```

Derive the other two, because **state already holds everything they need**:

- **corroboration** is a function of the claim's `supporting_evidence` and the
  sources those spans came from;
- **conflict** is a function of the `Contradiction` objects naming the claim.

This is T14/T15/T16 one level up. The rule those three established is *derive it
from structure, do not let anyone assert it*, and the enum is the last place it
has not been applied. It is also the pilot's own thesis turned on its own
schema: a stored status that summarises the warrant graph is a summary sitting
in the middle of the state.

The pleasant consequence: **T19's promotion write disappears.**
`corroboration_llm` already adds the corroborating span to `supporting_evidence`
and already writes a `Relation` recording why. Once corroboration is derived
from those, the third write (`:405-421`) is redundant and comes out. A good part
of this task is a deletion.

**The higher bar: independence, and the caller declares it.**

`VERIFIED` today needs a second source at `HIGH` reliability. The hole is that it
has **no notion of independence**. Reuters reporting a merger *because it read
the press release* is not a second source, it is the same source relayed; ten
outlets carrying one wire story are one source wearing ten hats. `Evidence`
separates sources only by `source_id` (`models/objects.py:110`), so two spans
tracing to a common origin corroborate each other today. If `VERIFIED` ever
fired on real news data it would most likely be wrong — which is the honest
reason its bar is too low, ahead of any question of how many members the enum
has.

A model cannot close this. Whether an article was written off a press release is
a fact about the world *outside* both documents — precisely the class T14 ruled
on: *an operator does not take a model's word for a fact about the world outside
the document.* So the caller declares it, exactly as they now declare
`--source-type`:

- `Evidence.derives_from: str | None` — the `source_id` this document is
  downstream of;
- a CLI option paired with `--also-input`, following the positional convention
  `--also-source-type` already set;
- two spans are **independent** iff neither's source is an ancestor of the
  other's.

The derived ladder then reads:

| derived level | requires |
|---|---|
| `UNCORROBORATED` | one source, or several that are not independent |
| `CORROBORATED` | ≥ 2 **independent** sources assert it |
| `VERIFIED` | ≥ 2 **independent** sources, ≥ 1 of them `HIGH` |

Undeclared lineage counts as independent, for T14's reason in reverse: "we do
not know" is not "we know it is derivative". Note that unlike the `MEDIUM`
default for reliability this default is **generous**, so it must be stated at
the field and surfaced in the memo rather than left implicit.

**The decision this forces.** Removing `VERIFIED` and `CONTRADICTED` from
`EpistemicStatus` is breaking: state already on disk carries those values and
`schemas/` exports them. Either

(a) remove them and write a load-time migration mapping `verified → reported`
and `contradicted → reported`, or
(b) keep them parseable but never emitted.

**Take (a).** (b) leaves the confusion inside the type where the next operator
can reach for it, and there is exactly one production emitter to migrate. Get
this confirmed before writing code — that is what the ⚠ is for.

**Out of scope, named so nobody smuggles it in.**

- **The three kinds of `REPORTED`.** A document that *asserts* a fact, one that
  *attributes* it to someone ("the CEO said"), and one that *evaluates* ("one of
  the industry's most compelling portfolios") are three different epistemic acts
  and all land on `REPORTED`. That belongs on the acquisition axis and is the
  T17 follow-on already named in `HANDOFF.md`. It wants this task's shape
  underneath it first: do it after, not inside.
- **Per-assertion accountability.** A 10-K is `HIGH`, but a forward-looking
  sentence inside it is explicitly not audited. Accountability attaches per
  assertion, not per document; catching that means reading claim text, which is
  a heuristic rather than a structural check.
- **"These two claims assert the same thing" is still model-judged.** The
  two-pass skeptic gate is a precision device, not a check, and it is the last
  self-judgement left in the T14–T19 arc. This task raises the bar on
  *independence* and *accountability* only. Say so in the write-up rather than
  letting a derived `VERIFIED` read as more than it is.

**Acceptance test** (`tests/test_epistemic_axes.py`, deterministic, no provider
call).

*Unit — acquisition.* The five members survive; under (a), a state file on disk
carrying `verified` or `contradicted` loads as `reported` and the migration is
pinned by a round-trip test.

*Unit — derived corroboration.* A claim on one source derives `UNCORROBORATED`;
on two independent `MEDIUM` sources, `CORROBORATED`; on two independent sources
one of which is `HIGH`, `VERIFIED`; and — **the case that does not pass today,
and the point of this task** — on two sources where one declares `derives_from`
the other, back to `UNCORROBORATED` however reliable either is.

*Unit — derived conflict.* A claim named by an `UNRESOLVED` `Contradiction`
reads as conflicted; a `RESOLVED` or `DISMISSED` one does not; and assert **no
field on the claim changed** to say so.

*Unit — the five subsets.* Each hand-maintained set is replaced by a property on
the axis, with today's behaviour pinned unchanged: a `reported` claim is
grounded and not weak, an `assumed` claim is provenance-free, and L2 still
raises `L2.CLAIM_MISSING_PROVENANCE` at `ERROR` for a 0.6+ claim citing nothing.

*Composition.* On the T19 corroboration fixture the corroborated claim reaches
the same derived level the promotion used to write — **and the patch contains no
`epistemic_status` update at all.** Pin that the write is gone, not just that the
answer matches.

*Replay.* Against the committed cassettes: no committed claim carries `verified`
or `contradicted`, and the memo line for a corroborated claim states its
acquisition and its derived support as **two** facts rather than one.

**Invariants.** No direct `SemanticState` mutation. Derivation is a pure read
over committed state — deterministic, model-free, and free to compute, so it
replays identically and adds no provider call.

`DEMO.md` stays byte-identical. The deterministic `ExtractOperator` emits only
`OBSERVED` and `INFERRED` (`operators/extract.py:69,79,88`) and the demo has no
corroboration stage, so every demo claim derives `UNCORROBORATED`; render
nothing at that level and the artifacts do not move. If a renderer change would
move them, scope it out of the demo path the way T1, T15 and T16 each did.

The extraction prompt should not need to change — `extract_llm.py:75` already
offers only `reported | inferred | assumed | speculative`. If it does change,
re-record all four cassettes.

Whatever replaces `_UNAVAILABLE_TO_A_READER` must hold on **both** routes in,
assembled and full-patch passthrough. T8, T11, T14 and T17 each had to close
that separately; assume this one does too until a test says otherwise.

---

## T21 — An accountable source is not a certain one · ✅ DONE

**What landed.** `GROUNDING_FACTOR` (`operators/calibration.py`) maps each
`EpistemicStatus` to how much of a claim's confidence survives *how it entered
state*. `REPORTED` is **0.9**, agreed before code moved; every other member is
1.0, each for a stated reason. The table is exhaustive rather than defaulting, so
adding a member to the axis forces a decision — T20's lesson applied forward.

`claim_factor()` resolves the one factor that damps a claim and says which rule
supplied it:

```
ceiling(c) = c.confidence * min(reliability_factor(c), grounding_factor(c))
```

**`min`, not a product**, which is the decision T16 settled and the one thing
T21 could most easily have broken. Under `min` a `LOW` press release still caps
at 0.60 — 0.6 is already below the 0.9 a reported claim allows — so nothing about
T14–T16 moves. Only the `HIGH` tier changes, which is the tier that was wrong.
Multiplying would have dropped that press-release claim to 0.54 for no considered
reason: two rules meeting by accident, exactly what T16 ruled out.

**Measured on the run that found the defect.** `verify_001`'s pre-calibration
state (v7) re-calibrated under the new rule, so the claims, evidence and model
output are identical and only the arithmetic differs:

| | before T21 | after T21 |
|---|---|---|
| claims at 1.00 | **17 of 17** | **0** |
| claim confidences | all 1.00 | all 0.90 |
| recommendation | **100%** | 90% |

18 confidence changes recorded, each naming what moved it:

> *"Discounted to 0.90 from 1.00: a reported claim carries 90% of its stated
> confidence however accountable its source. Reading a document establishes that
> the document says so, which is not the same as the thing being so — so no claim
> read out of one is certain."*

**Three existing assertions inverted, and each was rewritten to say what is still
true rather than deleted.** The spec predicted the first; the other two fell out
of the same rule.

- `test_a_filing_is_held_to_a_higher_ceiling_than_a_press_release` said *"an
  accountable source discounts no claim"*. It now asserts what the test was
  always about — a filing is worth **more** than a press release — plus the new
  half: it is not worth certainty.
- `test_the_same_recording_read_as_a_filing_keeps_its_certainty` is renamed
  `..._is_discounted_least` and pins that the discount applied is the *grounding*
  one and not the source one. A filing sliding to the `LOW` factor would be a
  worse bug than the one T21 fixed, and nothing else would have caught it.
- T19's headline test (`0.54` uncorroborated → corroborated) keeps its shape with
  the upper endpoint at **0.81**: the claim is still only *reported*, so
  grounding binds where the source no longer does. Both endpoints are now derived
  from the constants rather than typed, so the test says which rules produced
  them. Corroboration still pays; it just no longer pays in certainty.

**Verified by mutation.** Restoring the defect (`REPORTED` back to 1.0) turns 7
red; multiplying instead of `min`, 7; letting the *weaker* rule bind (`max`), 25;
applying grounding to `OBSERVED` too, 11; dropping the receipt's distinction
between the two rules, 2. No survivors.

**`DEMO.md` byte-identical**, and checked rather than assumed: the deterministic
`ExtractOperator` emits `OBSERVED` and `INFERRED` only — never `REPORTED` — so the
new factor does not bind anywhere on the demo path.

**What this does not do, and the number says so.** 90% on a merger facing a
hostile counter-bid is still too high, and T21 does not claim otherwise. It
removes *certainty*; it does not model the risk of the thing not happening, which
a pipeline reading two documents has no business forecasting. The remaining gap
is per-assertion accountability — the same 8-K carries Section 18 liability for
its historical statements and disclaims its forward-looking ones under the PSLRA
safe harbor — and that is named, unstarted, and wants its own task.


---

### The spec this was built from

**Why, with the numbers.** T20's first live proof run did what it was built to
do and, in passing, produced the highest confidence number in the project's
history. `verify_001` — Netflix's Form 8-K Item 1.01 and WBD's Form 8-K Item
1.01, both declared `regulatory_filing` — committed **17 of 17 claims at exactly
1.00**, and a recommendation of *"Proceed with the merger"* at **100%**.

Measured against the arc that produced it, on the same pipeline:

| run | source | claims at 1.00 | recommendation |
|---|---|---|---|
| `005` (before T14) | press release | 7 of 10 | 90% |
| `009` (T16) | press release | 0 of 10 | 42% |
| `010` (T17) | press release | 0 of 10 | 48% |
| **`verify_001` (T20)** | **two filings** | **17 of 17** | **100%** |

T14 stopped a press release buying certainty. Nothing stops a *filing* buying
it — and a filing buys more of it than the press release ever did.

**The mechanism, in three facts already in the tree.**

1. `RELIABILITY_FACTOR[Reliability.HIGH] = 1.0`
   (`operators/calibration.py:104`). A claim citing an accountable source is
   discounted by **nothing**: `ceiling = confidence × 1.0`.
2. T15's recommendation cap is `min(capped claim confidence)`
   (`calibration.py:170`), so with every limb at 1.00 the recommendation is 1.00.
   The cap did its job; there was nothing left to bind it.
3. The model set every `claim_type` to `factual_claim` — **17 of 17**, including
   ten whose text is plainly about the future (*"WBD's stockholders **will**
   become stockholders of NewCo"*, *"Each share of WBD Common Stock **will** be
   converted into cash"*). `predictive_claim` is offered in the prompt
   (`extract_llm.py:74`) and was used **zero** times. `calibration.py` never
   reads `claim_type` at all.

That is T14's disease at the top of the ladder: a classification the model makes
about its own output, answered uniformly and favourably, that nothing downstream
re-derives.

**And the substance was genuinely unsettled.** At the time of these filings the
merger was subject to a competing hostile tender offer and a proxy contest from
Paramount Skydance (EDGAR: `SC TO-T`, `DFAN14A`, `DEFC14A`, Dec 2025 – Feb 2026),
plus regulatory clearance and a shareholder vote. The run's own Retriever opened
the question *"Are there any regulatory hurdles that could delay or prevent the
merger?"* — and the memo still recommended Proceed at 100%.

**The documents themselves disagree with the number.** The same 8-K that carries
Section 18 liability for its factual statements explicitly disclaims its
forward-looking ones under the PSLRA safe harbor, and WBD's 8-K says of its own
exhibits that they *"shall not be deemed 'filed' for purposes of Section 18 ...
or otherwise subject to the liability of such section."* A filing is not one
uniform block of accountability, and it says so in its own text. The pipeline
applies `HIGH` to all of it.

**The fix — the ceiling reads the epistemic axis too.** T17 established that
reading a document establishes *that the document says so*, never that the thing
is so, and made every extracted claim `REPORTED`. That rule never reached the
number. It should:

```
ceiling(c) = c.confidence × min( reliability_factor(best evidence),
                                 grounding_factor(c.epistemic_status) )
```

with `grounding_factor(OBSERVED) = 1.0` and `grounding_factor(REPORTED) < 1.0`.
**`min`, deliberately not a product** — T16 settled that a claim is damped
*once*, and multiplying two factors that never agreed to meet is the double
discount it ruled out. Under `min`, a `LOW` press release still caps at 0.60 and
nothing about T14–T16 moves; only the `HIGH` tier changes, which is the tier that
is wrong.

The consequence worth stating plainly: **no claim read out of a document can
commit at 1.00, ever.** That is not a new rule — it is T17's rule, finally
applied to the number instead of only to the label. It needs no text heuristic,
no new model call and no new field: it reads the axis T20 just narrowed to one
clean question.

**The decision this forces.** What is `grounding_factor(REPORTED)`? It is a
constant with no principled derivation, the way `RELIABILITY_FACTOR`'s values are
— pin it, document the reasoning at the constant, and make changing it a
deliberate edit. **0.9 is the recommendation**: it removes certainty without
pretending to model deal risk, and leaves a filing meaningfully stronger than the
`MEDIUM` 0.8 it would otherwise collapse toward. Get the value agreed before
writing code; the mechanism is not in question, the number is.

**Expect one existing assertion to invert, and that is the point.**
`tests/test_calibration.py:421` reads `assert claim_caps(filing) == [], "an
accountable source discounts no claim"`. After T21 an accountable source *does*
discount — a little — because the claim is still only reported. Rewrite it to say
the thing that is still true: a filing discounts **less** than a press release,
and the gap between them is unchanged.

**Out of scope, named so nobody smuggles it in.**

- **Per-assertion accountability.** T20 named this and deferred it; this run is
  the evidence it is not academic. The honest version reads document structure —
  the PSLRA safe harbor, `furnished` under Item 7.01 versus `filed` — and prices
  a forward-looking span below a historical one *within the same document*. That
  is a second discount on a different axis (modality, not grounding) and it wants
  its own task. T21 deliberately does the layer that needs no text analysis.
- **Deal risk.** Nothing here models whether the merger completes. A ceiling is
  not a forecast, and a pipeline that reads two documents has no business
  producing one.
- **The model's `claim_type`.** T21 does not start trusting it, and does not try
  to fix it. It is currently inert — nothing reads it — and the measurement above
  (17 of 17 `factual`) is the reason to leave it that way until something derives
  it rather than asks for it.

**Acceptance test** (`tests/test_claim_calibration.py`, deterministic, no
provider call).

*Unit.* A `REPORTED` claim citing `HIGH` evidence cannot commit at 1.00 whatever
confidence was proposed, and commits at exactly `grounding_factor(REPORTED)`; an
`OBSERVED` claim citing the same evidence is untouched; a `REPORTED` claim citing
`LOW` evidence is capped at the `LOW` factor and **not** below it — pin that the
two rules compose by `min` and not by product, which is the decision above; every
cap records a reason naming which of the two bound it.

*Composition.* On the `analyze_five_stage` cassette declared `regulatory_filing`,
the recommendation is below 1.00, and the gap between the same run declared
`press_release` and declared `regulatory_filing` is unchanged from today's — the
filing is still worth more, it is just no longer worth certainty.

*Replay.* Against the committed cassettes: **no committed claim in any run
commits at 1.00**, and no hypothesis does either. That single assertion is the
whole task, and it is the one that would have caught `verify_001`.

**Invariants.** No direct `SemanticState` mutation. Deterministic and model-free
— the ceiling is arithmetic over committed state, so it replays identically and
adds no provider call. Confidence still moves **only downward**, and every change
still records what moved it (T15/T16).

`DEMO.md` must stay byte-identical: the deterministic `ExtractOperator`'s
hand-written confidences are 0.74/0.85/0.83/0.58 with no 1.00 anywhere, and its
claims are `OBSERVED`/`INFERRED` rather than `REPORTED`, so the new factor does
not bind. **Verify that rather than assume it** — and if a renderer or metric
moves, scope the change out of the demo path the way T1, T15, T16 and T20 each
did.

---

## T22 — A document is not one block of accountability · ✅ DONE

**What landed.** `src/spc_state/regions.py` — a region is a marker plus a source
type, declared by the caller; a span takes the source type of the last region
beginning at or before its offset, and the document's own declaration before
that. Option **(a)** as agreed:

```
spc-demo analyze --input 8k.txt --source-type regulatory_filing \
                 --region "Item 7.01:press_release"
```

Nothing new is derived. T8 made every citation locatable and T10 hardened it, so
`Evidence.location` already carried the offsets this needs; markers are located
with the same `locate_span`, so `"Item   7.01"` finds `"Item 7.01"` the way a
citation survives a real document's whitespace.

**Measured, live.** The same complete 8-K submission, declared `regulatory_filing`
both times:

| | `region_001` (no region) | `region_002` (region declared) |
|---|---|---|
| filed spans (Item 1.01) | `high` | `high` |
| furnished spans (7.01 / Ex 99.1) | **`high`** | **`low`** |
| claim confidence, furnished | 0.90 | **0.60** |
| recommendation | 0.90 | **0.60** |
| memo flags furnished claims weak | no | **yes** |

The whole chain moves: region → reliability → T16's claim discount → T15's
recommendation cap → the memo's risk section. Nothing downstream needed changing,
because each of those already read what was underneath it.

*(The two runs extracted different claim sets — a live model is not
deterministic, and `region_002` happened not to extract the marketing-copy line at
all. The deterministic proof is the unit test, which feeds both spans from one
document and asserts each one's weight; the live pair is corroboration.)*

**Both routes in, closed together this time.** T8, T11, T14, T17 and T20 each had
to close the full-patch passthrough separately, after the assembled path. Here the
passthrough was written in the same change and is pinned by its own test: a patch
asserting the furnished exhibit is a `regulatory_filing` at `high` is overruled,
because the region is the caller's fact and believing the patch restores exactly
the defect. Moving the reliability stamp after `locate_span` — the offset is not
known until the span is located — is the only structural change that needed.

**`_is_this_document` was widened, and it would have been a silent bug.** It
accepted evidence naming the document's declared source type or the legacy
vocabulary. With regions, a span inside a furnished exhibit legitimately reads
`press_release` while the document is a `regulatory_filing`, so a model-authored
patch carrying the honest region type would have been treated as naming a
document we were not handed, and skipped.

**Verified by mutation.** Ignoring regions entirely turns 5 red; excluding the
marker index from its own region, 1; first-region-wins instead of last, 1;
silently skipping a marker that does not occur, 1; the assembled route ignoring
the region, 1; the passthrough route ignoring it, 1. No survivors.

**`DEMO.md` byte-identical**, and 459 tests pass (was 441) — with no region
declared every span is weighed exactly as before, which is the no-op guarantee
this task owes everyone not using it, pinned by its own test.

**Scope, stated plainly.** `--region` applies to `--input` only. `--also-input`
documents take no regions from the CLI; `SourceDocument.regions` carries them for
a programmatic caller, but pairing a repeatable-per-document list positionally on
the command line would be worse than not having it. Add it when a run needs it.

**What this does not fix, and it is the one that matters.** `verify_001`'s 17 of
17 claims at 1.00 and its 100% recommendation are untouched, exactly as the spec
said: every one of those spans sits in Item 1.01, the accountable region, so no
region rule reaches them. That is **modality** — settled fact versus expected
event — and it remains unstarted, needing a decision between a linguistic check
on the cited span (locatable and auditable, but the heuristic T16 declined) and
asking the model, which answered `factual_claim` 17 times out of 17 including ten
claims plainly about the future.


---

### The spec this was built from

**A correction first, because it splits this task in two.** `HANDOFF.md` records
"per-assertion accountability" as one item, and says its two markers — the PSLRA
safe harbor and the furnished-versus-filed distinction — are "explicit, locatable
document structure rather than the claim-text heuristic T16 rejected." Read
against the actual filings, **only one of those two is true**:

- **Furnished-versus-filed is a genuine region boundary**, and the document
  declares it itself. Netflix's 8-K: *"The information contained in **this Item
  7.01, including Exhibit 99.1**, shall not be deemed 'filed' for purposes of
  Section 18 ... or otherwise subject to the liabilities of that section."* That
  names a span of the document and states its legal status. Locatable, structural,
  no judgement required.
- **The safe harbor is not a per-sentence marker.** It says *"This document
  contains 'forward-looking statements'"* and describes their subject matter
  (the expected closing date, the anticipated benefits). It does **not** say which
  sentences they are. Applying it to a given span still means deciding whether
  that span is forward-looking — which is exactly the judgement T16 declined to
  make from claim text.

So the two halves want different tasks, and only the first is structural. **T22 is
the first.** The second is named at the end and left unstarted, because it
reopens a question T16 settled and needs its own sign-off.

**Why, with the numbers.** EDGAR serves every filing as a complete submission
file — 1.2 MB for this one — that concatenates the 8-K body with all of its
exhibits. So "the Netflix 8-K", as a user actually downloads it, is one document
containing an accountable region *and* a region the document itself disclaims.
Declared `regulatory_filing`, as any reasonable user would:

| claim | region | reliability |
|---|---|---|
| entered into a merger agreement with WBD | filed (1.01) | `high` ✅ |
| the boards unanimously approved | filed (1.01) | `high` ✅ |
| the merger results in WBD becoming a subsidiary | filed (1.01) | `high` ✅ |
| issued a joint press release announcing… | **furnished (7.01)** | `high` ❌ |
| Netflix will host an investor conference call | **furnished (7.01)** | `high` ❌ |
| *"The merger **unites** Warner Bros.' **iconic** franchises and **storied** libraries…"* | **furnished (Ex 99.1)** | `high` ❌ |

Run `region_001`: **three of six claims** are drawn from the disclaimed region and
every one of them carries `HIGH`. The last is the press release's marketing copy
— the seller's own promotional language — weighed exactly as heavily as the deal
terms, inside a document that says in its own text that nobody is liable for it.

This is T14's rule applied at the wrong granularity. T14 established that
reliability is a fact about *where the text came from*, which the caller knows and
the model cannot see — and then stamped one value on every span in the file. A
filing is not one block of accountability, and the SEC's own machinery says so.

**The fix — reliability is a property of the span, not the document.** The
machinery already exists and nothing new needs deriving: T8 made every citation
locatable and T10 hardened it, so `Evidence.location` already carries `start` and
`end` offsets into the source. A document becomes an ordered list of **regions**,
each with its own source type; a span's source type is the last region beginning
at or before its offset.

Declared by the caller, for T14's reason — whether Item 7.01 is furnished is a
fact about securities law, not something visible from inside the sentence:

```
spc-demo analyze --input 8k.txt --source-type regulatory_filing \
                 --region "Item 7.01:press_release"
```

meaning *"from the first occurrence of this marker onward, weigh spans as a press
release."* Markers are located with the same `locate_span` the extractor already
uses, so a marker that does not appear is an error rather than a silent no-op —
the failure mode being a document that looks region-aware and is not.

With no `--region`, the whole document is one region at the declared
`source_type` and **nothing changes** — every existing run, cassette and test
included.

**The decision this forces.** How a region is declared is the open question, and
it is ergonomics rather than mechanism:

(a) `--region "<marker>:<source_type>"`, repeatable — hand-usable, format-agnostic,
    and it reuses `locate_span`;
(b) byte offsets — precise, unusable by a human;
(c) a sidecar JSON file per document — scales to many regions, heavy for two;
(d) auto-detect SEC item headers — fixes the common case without the caller
    knowing anything, but embeds one filing format in a general engine.

**(a) is the recommendation**, with (d) explicitly rejected: a pipeline that
silently knows what an "Item 7.01" is has taken a fact about the world into
itself, which is the mistake T14 exists to prevent — the caller should say it.
Agree the shape before code moves.

**Out of scope, named so nobody smuggles it in.**

- **Modality — whether a claim is about something settled or something expected.**
  This is what produced `verify_001`'s 17-of-17 at 1.00 and its 100%
  recommendation, and **T22 does not fix it**: those spans are all in Item 1.01,
  the accountable region, so no region rule touches them. The safe harbor tells
  you the document contains forward-looking statements and refuses to say which.
  Closing it means either a linguistic check on the cited span — locatable and
  auditable, but a heuristic, and T16 declined one — or asking the model, which
  answered `factual_claim` 17 times out of 17 including ten claims about the
  future. That is a real decision with no obviously right answer: its own task,
  its own sign-off.
- **Evaluative language.** *"iconic franchises and storied libraries"* is caught
  here only in the sense that it stops being `HIGH`. Whether a sentence with no
  truth value should become a `Claim` at all is still the T17 follow-on.

**Acceptance test** (`tests/test_regions.py`, deterministic, no provider call).

*Unit.* A span before the marker keeps the document's declared source type; a span
after it takes the region's; a span exactly at the marker offset takes the
region's (pin the boundary, it is the only ambiguous index). Several regions apply
in order, and the *last* one beginning at or before the span wins. A marker that
does not occur in the document raises rather than being ignored. No regions
declared leaves every span exactly as today.

*Composition.* On a fixture holding a filed section and a furnished one, the
claims drawn from the furnished region commit at the region's reliability and the
filed ones at the document's — and the `Retriever` opens a gap on the former,
which it does not do today.

*Replay.* Against the committed cassettes, with no `--region` declared: every
committed `Evidence.reliability` is byte-identical to today's. This task must be a
no-op for anyone who does not use it.

**Invariants.** No direct `SemanticState` mutation. The region resolution is
deterministic and model-free. Reliability is still derived from the caller's
declaration and never from the model — T22 narrows *what* the caller declares, it
does not move the authority. The rule must hold on **both** routes in, assembled
and full-patch passthrough, where `_verify_patch_evidence` already overwrites
`reliability` and `derives_from`: T8, T11, T14, T17 and T20 each had to close that
separately, so assume this one does too until a test says otherwise.

`DEMO.md` must stay byte-identical — the deterministic `ExtractOperator` declares
no regions — and that is to be verified, not assumed.

---

## T23 — An accountable source cannot settle a future event · ✅ DONE

**Sign-off given 2026-09-14** on the one question it was blocked on: read the
language, rather than ask the model.

**Why, with the numbers.** T21 stopped a filing buying certainty and left
`verify_001` at **0.90** on a merger then facing a hostile counter-bid. The reason
was visible in the spans all along — ten of its seventeen claims are about the
future (*"WBD **will** become a wholly owned subsidiary"*, *"each share **shall**
be converted"*) and seven are about completed acts (*"the boards **have
unanimously approved**"*). Nothing read the difference. The model was asked:
`claim_type` offers `predictive_claim`, and it answered `factual_claim` **17 times
out of 17**.

T22 established there is nothing structural left to read. Furnished-versus-filed
is a real region boundary and T22 took it; the PSLRA safe harbor is not, because
it says a filing *contains* forward-looking statements and describes their subject
matter without ever marking a sentence.

**So this reads language — the narrow, deliberate exception T16 declined.** Four
constraints make it auditable rather than magic, and each is pinned by a test:

1. **It reads the source's words, not the model's.** The check runs on the quoted
   span, which T8 verified is really in the document. The claim text is the
   model's paraphrase; the span is evidence.
2. **It only ever lowers.** A miss leaves the number where it was, so the failure
   mode is doing nothing — never inventing confidence.
3. **It names what it found.** Every discount records the marker, so a reader can
   check the span. That is what separates an auditable heuristic from a
   classifier nobody can question.
4. **It is biased against firing.** A claim is unsettled only when **every** span
   it cites is; one settled span settles it, mirroring `best_reliability`.

**The marker set is measured, not invented.** Against the sixteen distinct spans
committed in `verify_001`: **9 of the 11 forward-looking ones caught, 0 false
positives** on the 5 settled. `will` and `shall` did all the work on merger 8-Ks;
the rest (`may`, `might`, `could`, `expects`, `anticipates`, `intends`, `subject
to`, `contingent on`) cover the guidance and risk language a 10-K carries.

**`can` is excluded on principle.** It expresses *capability*, not contingency:
"the library can parse JSON" is a settled fact about the library. It also happens
to be the demo's one hedged span ("coding assistants **can** accelerate routine
tasks") — the two coincide, and the principle is what decides it. Stated plainly
because the coincidence is convenient and should not pass unexamined.

**The composition is the real design decision.** The two axes combine differently:

```
ceiling(c) = c.confidence x min(reliability, grounding) x modality
```

Reliability and grounding both answer *how much is this telling worth*, so the
harder binds and the other stands down — `min`, exactly as T16 settled, untouched.
Modality answers whether the **proposition** is settled, which no amount of source
quality changes: a merger agreement is a perfect source for *"we signed this"* and
tells you nothing about whether the merger completes. Folding it into the same
`min` would let a good source mask an unsettled claim — which is precisely how
`verify_001` reached 0.90. So it multiplies, and a test pins that
`min(a, b) * m != min(a, b, m)`.

**Measured.** `verify_001`'s pre-calibration state re-calibrated, identical claims
and model output, only the arithmetic differing:

| | pre-T21 | T21 | **T21 + T23** |
|---|---|---|---|
| claims at 1.00 | 17 of 17 | 0 | 0 |
| claim confidences | all 1.00 | all 0.90 | **0.72 x10, 0.90 x7** |
| recommendation | 100% | 90% | **72%** |

**Exactly 10 of 17**, matching the hand count of forward-looking claims. The seven
completed acts keep 0.90 — the axis discriminates rather than sweeping. Each of
the ten records why:

> *"…and every span it cites is about something not yet settled ('will'), which
> carries a further 80% — an accountable source cannot make a future event
> certain."*

**Three existing tests moved, and one of them found a better answer than the test
had.** `test_the_calibrator_then_reprices_the_corroborated_claim` asserted T19's
0.54 → 0.81. Its fixture claim reads *"may face regulatory risk"*, so modality
fires uncorroborated — but once the regulator's span (*"cleared the acquisition"*,
a completed act) joins the claim, modality stops applying entirely. **Corroboration
now pays twice**: a better source, and a span about something that has happened.
That fell out of the every-span rule rather than being designed, and is now
asserted as two separate facts.

**Verified by mutation.** Modality never firing turns 4 red; joining the `min`
instead of multiplying, 4; *any* unsettled span sufficing instead of every, 2; an
empty span list counting as unsettled, 3; admitting `can`, 1; dropping word
boundaries so `will` fires inside `goodwill`, 1; the receipt no longer naming the
marker, 1. No survivors.

482 tests (was 459). `DEMO.md` byte-identical, verified rather than assumed.

**The limits, pinned as tests so they stay known rather than discovered.**

- **It misses modal-free future statements.** Two of `verify_001`'s spans are the
  same gerund — *"the stockholders … **becoming** the stockholders of Newco"* — a
  future event with no modal. The check does nothing and the number stands.
- **It is English-only.** `live_document_german.txt` contains none of these
  markers and never will, so a non-English run simply gets pre-T23 behaviour.
  The engine is not multilingual here and should not pretend otherwise.
- **It does not forecast.** 0.72 is not a probability that the merger closes.
  Whether a deal completes is not something a pipeline reading two documents can
  know, and T23 claims only that an expectation is worth less than a completed
  act.

---

## T24 — The committed schemas must match the models · ✅ DONE

**Why.** `schemas/` is a committed artifact generated from the models, and
nothing compared the two. T20 regenerated them and the diff picked up a
`TokenUsage` block **missing since T5** — ten tasks of schema changes had landed
without anyone noticing.

The three existing tests all passed throughout that drift, and it is worth being
precise about why: they wrote schemas to a `tmp_path` and checked the output was
well-formed JSON with the right required fields. Every one of them was a test of
`build_schemas`, and none of them was a test of `schemas/`. The artifact a reader
actually opens was the one thing unchecked.

**What landed.** Three tests in `tests/test_schema_export.py`:

- every exported model has a committed schema;
- no committed schema **outlives its model** — T20 removed two `EpistemicStatus`
  members and a whole model could go the same way, leaving a file that documents
  something gone;
- every committed schema matches what `write_schemas` produces **as exact text**.

Text and not parsed JSON, because the committed file *is* the artifact: a
hand-edit or a change to the writer's own indentation is drift too. The expected
bytes come from `write_schemas` itself, so this can never disagree with it about
formatting.

Each failure names the regeneration command. A contributor who adds a field sees:

> *schemas/ is out of date for ['semantic_patch', 'semantic_state'] — the models
> changed and the committed artifact did not. Run: `python -m
> spc_state.models.schema_export schemas`*

**Verified against real drift, not by mutating the test.** A passing test proves
nothing here — the old ones passed for fifteen tasks. So each scenario was staged
against the real tree and reverted: a model gaining a field turns 1 red; a
committed schema hand-edited, 1; a committed schema missing, 1; a schema left
behind after its model is gone, 1.

485 tests (was 482). `DEMO.md` byte-identical. The committed schemas were already
in sync — T20 regenerated them — so this adds a guard rather than a fix.

---

## T25 — The `VERIFIED` pairing, reproducible from a clean clone · ✅ DONE

**Why.** Everything T19–T23 claimed rested on `verify_001`, a live two-filing run
whose source documents lived in a scratchpad and whose output lived in a
gitignored `runs/`. The numbers were real and nobody else could check a single
one of them — an awkward position for a project whose whole subject is traceable
reasoning.

**What landed.**

- **The two filings, committed as fixtures.** `tests/fixtures/sec_8k_netflix.txt`
  and `sec_8k_wbd.txt` — Item 1.01 of each counterparty's Form 8-K on the same
  merger agreement. Kept as **pure document text**: the first attempt put a
  provenance header in each file, which was wrong, because the extractor reads
  the whole file and the header would have become extractable content. Provenance
  lives in `tests/fixtures/SEC_SOURCES.md` instead, with CIK, accession and the
  EDGAR path for each.
- **A recorded cassette**, `analyze_two_filings.json` — 7 exchanges, 8 committed
  stages. Replays with **no key and no network**, verified by running the suite
  with `OPENROUTER_API_KEY` and the proxy variables unset.
- **`tests/test_verify_replay.py`**, 10 tests.

**The recorder could not do this, and now can.** It was hardcoded to a
single-document run, so the pairing that motivates the whole thing was the one
shape it could not capture. `--also-input` / `--also-source-type` /
`--source-type` / `--question` now exist on both `record` and `check`, defined
once and shared, because a `check` that describes different sources than the
`record` replays against material the recording never saw.

**The cassette's document pin had the same gap.** `document_sha256` held one
digest, so a multi-source cassette could not prove what it was recorded from.
`documents_digest` pins every document in reading order, joined on a NUL — and
for a single document it is **exactly** `text_digest`, since joining a
one-element sequence returns it unchanged. Every cassette recorded before this
keeps validating against its own document, which is asserted rather than assumed.

**What this restores, and what it does not.** The original run's exact claim set
cannot come back — it came from a non-deterministic model and was never recorded.
What is reproducible is the *behaviour* those tasks claimed, and the whole arc
now shows up in one deterministic replay:

| | the replay shows |
|---|---|
| T19/T20 | **4 claims reach `VERIFIED`** across two independent accountable sources |
| T20 | every one still reads `reported` — corroboration does not overwrite acquisition |
| T21 | nothing commits at 1.00 |
| T23 | *"entered into"* and *"unanimously approved"* hold **0.90**; *"will be converted"* and *"will be determined"* take **0.72** |

The 0.90 and 0.72 are asserted as `GROUNDING_FACTOR` and
`GROUNDING_FACTOR x MODALITY_FACTOR`, derived from the constants rather than
typed, so the test says which rules produced them.

**A gap this would otherwise have created, closed with it.** Cassettes are
enumerated by hand in the replay tests, so a new one added without being
registered would be checked by nothing — the same shape as the `schemas/` drift
T24 fixed. `test_every_committed_cassette_is_exercised_by_a_test` asserts the
directory holds exactly the cassettes some test names. Verified by dropping a
stray cassette in: it fails and names the file.

**To re-record**, if a prompt changes:

```
python tools/record_cassette.py record \
    --input tests/fixtures/sec_8k_netflix.txt --source-type regulatory_filing \
    --also-input tests/fixtures/sec_8k_wbd.txt --also-source-type regulatory_filing \
    --question "What did Netflix and WBD agree, and on what terms?" \
    --out tests/fixtures/cassettes/analyze_two_filings.json
```

Needs `OPENROUTER_API_KEY`. Budget a retry: `deepseek/deepseek-chat` returns
upstream 429s intermittently.

**One existing assertion changed wording.** `from_path`'s refusal message says
"recorded against different source material" rather than "different document",
since it now covers both; `test_cassette_is_recorded_from_its_document` matches on
the durable part of the string.

495 tests (was 485). `DEMO.md` byte-identical.

**Still not reproducible, and named rather than left implicit.** The other four
live runs — `lineage_off`/`on` and `region_001`/`002` — remain scratchpad-only.
They demonstrate T20's lineage gate and T22's regions, each needs its own cassette
and fixtures, and the machinery to do it now exists. `verify_001` was the one
carrying the load, so it went first.

---

## T26 — The lineage gate, reproducible from a clean clone · ✅ DONE

**Why.** T25 committed the pairing that proves `VERIFIED` and named the four live
runs it left behind. `lineage_off` / `lineage_on` were the first two: the same
joint press release filed by both counterparties, three false corroborations that
one honest `--also-derives-from` removed. They demonstrated the bar T20 exists to
enforce, and they lived in a scratchpad — so the gate that stops one source
counting as two was the part of the arc nobody else could check.

**What landed.**

- **The one press release, committed twice.** `tests/fixtures/joint_pr_netflix.txt`
  and `joint_pr_wbd.txt` — Exhibit 99.1 of each counterparty's Form 8-K, which is
  the *same* joint release under two accession numbers. The retained text is
  word-for-word identical; the files differ only in where each filer's HTML wraps
  the headline, and the fixtures **keep that** rather than normalising it away,
  because two identical files would be a fabricated pair rather than a found one.
  Provenance is in `tests/fixtures/SEC_SOURCES.md`, as T25 established.
- **Two cassettes**, `analyze_joint_pr_undeclared.json` (7 exchanges) and
  `analyze_joint_pr_declared.json` (6). Both replay with no key and no network,
  verified with `OPENROUTER_API_KEY` and the proxy variables unset.
- **`tests/test_lineage_replay.py`**, 13 tests. 508 total (was 495).

**Two recordings, and the reason is the finding.** Lineage changes no prompt — it
is the caller's fact, invisible to the model — so both runs send an identical
extraction and an identical first corroboration request. It changes what
*commits*, and from there the runs diverge for real: the planner in the
undeclared run reads a state carrying ten corroboration links. One cassette
cannot cover both without replaying one run's model output against the other's
state, so the recorder grew `--also-derives-from` and each setting was recorded
separately.

| | undeclared | declared |
|---|---|---|
| corroboration links | **10** | **0** |
| claims reading `corroborated` | **10** | **0** |
| claims reaching `verified` | 0 | 0 |
| the memo a stakeholder opens | says *corroborated* | does not |
| model calls | 7 | **6** |

**Who refuses, and where.** The model proposed the pairs in **both** runs — it
cannot do otherwise, because whether one document was written off another is a
fact about the world outside both of them (T14). The declared run's cassette
holds those proposals and its committed state holds none of them, and the test
asserts exactly that, out of the recording: the refusal is `_candidates` reading
the caller's declaration, not the model changing its mind. The gate also sits
**before** the skeptic pass, so refusing is the cheaper path — one model call
fewer over identical documents, which is the 7-vs-6 above.

**What the false corroboration could not buy, which is worth as much as what it
could.** Not one claim reached `VERIFIED` even with ten bad links committed:
`VERIFIED` needs an accountable source among the two, and a press release is a
party with a stake in the conclusion (T14/T20). The lineage gate is the second of
two locks, and this run shows the first one holding while the second is open.
Nor did the links move a number here — both copies are `LOW`, so the best evidence
a corroborated claim cited was no better than what it already had. **The whole
damage was the word `corroborated` reaching a reader**, which is precisely why
the memo is asserted and not only the state.

**The two runs' claim sets are not compared, deliberately.** They come from two
recordings of a non-deterministic model (24 claims and 17), and a test that
diffed them would be measuring the model, not the rule. Every assertion is about
one run's own outcome, or about a fact the recording itself pins.

**To re-record**, if a prompt changes — both, and the pair must stay in step:

```
python tools/record_cassette.py record \
    --input tests/fixtures/joint_pr_netflix.txt --source-type press_release \
    --also-input tests/fixtures/joint_pr_wbd.txt --also-source-type press_release \
    --question "What did Netflix and WBD announce, and on what terms?" \
    --out tests/fixtures/cassettes/analyze_joint_pr_undeclared.json

python tools/record_cassette.py record \
    --input tests/fixtures/joint_pr_netflix.txt --source-type press_release \
    --also-input tests/fixtures/joint_pr_wbd.txt --also-source-type press_release \
    --also-derives-from doc_001 \
    --question "What did Netflix and WBD announce, and on what terms?" \
    --out tests/fixtures/cassettes/analyze_joint_pr_declared.json
```

**The recorder's new flag validates like the CLI's.** `--also-derives-from` takes
one value per `--also-input` (or `none`), and a parent that is not a source in
the run is **refused** rather than swallowed — a typo'd lineage silently buys
back the independence the flag was passed to deny, and the failure mode is a
corroboration nobody checked. Same rule as `cli._lineage_arg`, same message.

508 tests (was 495). `DEMO.md` byte-identical.

**Still not reproducible.** `region_001` / `region_002`, which demonstrate T22's
regions, remain scratchpad-only. The pattern is now established twice.

---

## Seeding issues

`TASKS.md` is the source of truth. To open GitHub issues from it (one per task)
on `danielwipert/cas.spc`, ask and they can be created with the `gh` CLI — this
is intentionally a manual, on-demand step, not automated.
