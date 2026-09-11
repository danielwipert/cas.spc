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
   - `pytest` is green and `ruff check src tests` + `python -m mypy` are
     clean (**`python -m mypy`, not bare `mypy`** — a uv/pipx-installed mypy
     runs isolated from the project's dependencies and reports ~17 phantom
     import errors);
   - the deterministic demo stays byte-for-byte reproducible
     (`spc-demo demo` → identical `DEMO.md`) unless the task explicitly changes
     it;
   - no run output committed (`runs/` is gitignored).

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

## Seeding issues

`TASKS.md` is the source of truth. To open GitHub issues from it (one per task)
on `danielwipert/cas.spc`, ask and they can be created with the `gh` CLI — this
is intentionally a manual, on-demand step, not automated.
