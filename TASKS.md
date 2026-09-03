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

## T5 — Per-operator model routing + cost ledger · M

**Why.** Listed in the roadmap "Deferred" set. Today `--live-critic` uses one
model for the critic. Each operator should be able to name its own value-based
model (never a hardcoded frontier flagship), and the run should record token
usage + an estimated cost per step.

**Scope.** Extend `providers/openrouter.py` config + `LLMCriticOperator` to
accept a per-operator model; write a `runs/<id>/cost_ledger.json` summing
tokens/cost per `TransformRecord`.

**Acceptance test** (`tests/test_cost_ledger.py`, injected fake client — no
network). Two LLM operators run with different model slugs; their
`model_fingerprint`s differ; the ledger records a per-step token count and a
non-negative estimated cost.

**Invariants.** Model choice stays per-task and configurable (never a
hardcoded flagship). No network in tests — inject the client.

---

## T6 ⚠ — SQLite-backed StateStore · L

**Why.** Roadmap "Deferred." The file-based store is the v0.1 norm
(`AGENTS.md §V`). A SQLite backend behind the **same** `StateStore` interface
would prove the storage seam is real — but it relaxes a documented constraint,
so confirm before starting.

**Scope.** `src/spc_state/store/sqlite_store.py` implementing the existing store
protocol; a test fixture that parametrizes the store backend.

**Acceptance test** (`tests/test_store_backends.py`). The existing store tests
pass against both the file backend and the SQLite backend via parametrization;
a full demo run on SQLite yields the same committed state versions as the file
run.

**Invariants.** The runtime must not change — only the store implementation.
Reproducibility preserved. Requires sign-off to relax `AGENTS.md §V`.

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

## Seeding issues

`TASKS.md` is the source of truth. To open GitHub issues from it (one per task)
on `danielwipert/cas.spc`, ask and they can be created with the `gh` CLI — this
is intentionally a manual, on-demand step, not automated.
