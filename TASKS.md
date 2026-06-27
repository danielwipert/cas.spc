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
   - `pytest` is green and `ruff check` + `mypy src` are clean on touched files;
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

Follow-on polish worth a task: the planner currently **REJECTs** (no retry)
when the model returns valid JSON in the wrong shape, because the runtime only
RETRYs on `JSON_DECODE`. A small improvement would route shape-invalid LLM
output to RETRY with targeted feedback ("include a hypothesis").

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

## T4 — State-graph visualizer (Mermaid export) · M

**Why.** The Reasoning Receipt is text. A graph view of objects + relations
(`claim --depends_on--> assumption`, `question --questions--> claim`) makes the
state legible at a glance and strengthens the §20.8 audit-clarity story.

**Scope.** `src/spc_state/receipt/graph.py` rendering a `SemanticState` to a
Mermaid diagram; embed it in the receipt markdown.

**Acceptance test** (`tests/test_graph.py`). Deterministic Mermaid output for the
final demo state (snapshot fixture) contains a node per active object and an
edge per relation, with stable ordering.

**Invariants.** Read-only projection of state; deterministic (sorted) output.

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

## Seeding issues

`TASKS.md` is the source of truth. To open GitHub issues from it (one per task)
on `danielwipert/cas.spc`, ask and they can be created with the `gh` CLI — this
is intentionally a manual, on-demand step, not automated.
