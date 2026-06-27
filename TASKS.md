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

## T0 — Generalize Planner & Critic to arbitrary input (LLM-backed) · M

**Why.** `LLMExtractOperator` (`operators/extract_llm.py`) already turns *any*
document into a committed initial state — `spc-demo analyze` runs it live. But
the Planner and Critic are still the Phase 3 deterministic ones, keyed to the
demo's `claim_001`/`assumption_001`. Generalizing them unlocks the **full**
pipeline (extract → plan → critique → receipt) on real documents — the path to
"decision memos with receipts."

**Scope.** `operators/planner_llm.py`, `operators/critic_llm.py` modelled on
`LLMExtractOperator` (the operator owns id/transform bookkeeping; the model
contributes content; everything flows through `Runtime.step_llm`). Extend
`spc-demo analyze` to run all three live operators.

**Acceptance test** (injected provider, no network). Over an LLM-extracted
state, the LLM planner commits a hypothesis + open question linked to real
claim ids, and the LLM critic lowers an unsupported claim's confidence via a
versioned `update_objects` entry with `from`/`to`/`reason`. Both assert the
no-direct-mutation invariant.

**Invariants.** Mirror `extract_llm.py`: value-based per-task model, injected
client in tests, model only supplies content — never timestamps or ids.

---

## T1 — RetrieverOperator (complete the §8.3 SPC flow) · S

**Why.** Spec §8.3 has the SPC flow continue past the critic: *"Retriever
proposes Patch p4 identifying evidence gaps."* The demo currently stops at the
critic (state v3). The `RETRIEVER` projection already exists (evidence gaps +
open questions, `projection/builder.py`); only the operator is missing.

**Scope.** `src/spc_state/operators/retriever.py`, export it from
`operators/__init__.py`, optionally add it to the `spc-demo run`/`demo`
pipeline as a fourth step.

**Acceptance test** (`tests/test_retriever.py`). Running the retriever over the
post-critic demo state proposes a patch that adds an evidence-gap `Question`
for at least one weakly-supported claim, the patch validates and commits to
`v4`, and a test asserts the operator does **not** mutate state directly (mirror
`tests/test_operator_cannot_mutate_state.py`).

**Invariants.** Read through the projection (`resolve_view`); emit a patch with
`read_set`/`write_set`; new questions link to the claims whose evidence is thin.

---

## T2 — WriterOperator: project the final memo from state · S

**Why.** Spec §8.3 ends with *"Writer projects final memo from State v4."* The
writer is a **terminal projector**, not a state mutator — it consumes the
`WRITER` projection (high-confidence claims, no raw evidence) and renders a memo
artifact, the SPC counterpart to the baseline's memo. This makes the
head-to-head in `DEMO.md` a true memo-vs-memo at the end.

**Scope.** `src/spc_state/writer/` (or `receipt/`-adjacent), writing
`runs/<id>/memo.md`. It reads state; it returns **no** `SemanticPatch` (note the
distinction in `AGENTS.md §II` — a projector is read-only, not an operator).

**Acceptance test** (`tests/test_writer.py`). The memo cites only committed
high-confidence claims and the leading hypothesis, never raw evidence spans, is
deterministic (snapshot fixture), and contains no claim absent from the final
state.

**Invariants.** Read-only. No mutation, no patch. Pure projection → text.

---

## T3 — Formal Contradiction objects · M

**Why.** The `Contradiction` model exists but the demo produces **zero** formal
contradiction objects — tensions are captured as `Question`s instead (see
`evaluation` §20.5). Spec §20.5 asks whether the system preserves conflicts *as
objects*. A scenario with two directly conflicting claims should yield a
committed `Contradiction` linking them, routed for `REVIEW`.

**Scope.** A new scenario fixture under `examples/`, contradiction-detection
logic in a critic-style operator, and updates to `evaluation/metrics.py §20.5`
to count formal contradictions when present.

**Acceptance test** (`tests/test_contradiction.py`). Given the conflicting-claims
fixture, the pipeline commits (or routes to REVIEW) a `Contradiction` object
whose `claim_a`/`claim_b` reference the conflicting claims, and the §20.5 metric
reports `formal_contradiction_objects ≥ 1`.

**Invariants.** Contradiction enters via a patch like any other object; do not
special-case it around the validator.

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
