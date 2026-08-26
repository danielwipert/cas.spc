# Handoff

> **Protocol.** Read this file at the start of every session. Rewrite it at the
> close of every session. It is a **snapshot, not a ledger** — it holds only
> what was just done and what comes next. Overwrite it wholesale each time;
> never append. The durable record lives in git history, `ROADMAP.md`, and
> `TASKS.md` — not here.

**Last session:** 2026-06-27 · **Branch:** `claude/project-status-check-l7zkvl` (even with `main`)

---

## Where things stand

Roadmap complete through **Phase 9**. All three milestones shipped, including
the pilot report comparing SPC against a summary-passing baseline (H1–H4 and H6
supported; H5 holds by construction).

Health check: `pip install -e ".[dev]"` then `pytest` → **178 passed**, clean
tree, no divergence from `main`.

## What the last session did

Took the engine from "runs the frozen demo" to **"runs live on any document."**
`spc-demo analyze` is now five stages: extract → plan → critique → retrieve →
contradict → v5 → Decision Memo.

- **T0** — LLM-backed Extract / Planner / Critic. The unlock: full pipeline on
  arbitrary input. Model supplies content; the operator owns ids and transform
  bookkeeping.
- **T1** — `RetrieverOperator` (deterministic). Opens a `needs_evidence`
  question per evidence-gap claim.
- **T2** — Decision Memo (`memo.py`). Citation-backed stakeholder doc. Pure
  projection, no model call — asserts nothing absent from state.
- **T3** — First-class `Contradiction` objects, committed as `unresolved`.
- **Last commit** (`8ea167c`) — contradiction detection split into two passes
  after live op-eds showed invented conflicts: propose candidates behind a
  justification gate, then an adversarial skeptic pass whose default is "these
  can coexist." False positive → 0; the genuine "+15% vs −4%" conflict still
  caught.

The deterministic `spc-demo demo` was deliberately kept out of the `analyze`
pipeline so the frozen pilot artifacts stay byte-stable.

## Next up

Nothing is half-finished — pick any of these cold.

1. **Planner RETRY fix** (unlisted, cheapest win). The planner currently
   REJECTs when the model returns valid JSON in the wrong shape, because the
   runtime only RETRYs on `JSON_DECODE`. Route shape-invalid output to RETRY
   with targeted feedback ("include a hypothesis").
2. **T4 — State-graph visualizer** (M). Mermaid export embedded in the
   receipt; strengthens the §20.8 audit-clarity story.
3. **T5 — Per-operator model routing + cost ledger** (M).
4. **T6 — SQLite `StateStore`** (L) ⚠ relaxes a documented v0.1 constraint —
   needs sign-off before starting.

Full specs with acceptance tests are in [`TASKS.md`](./TASKS.md).

## Before touching code

Read [`AGENTS.md`](./AGENTS.md). The hard invariant: **no operator mutates
`SemanticState` directly** — all change flows through a validated
`SemanticPatch`. Definition of done for any task is in `TASKS.md`: acceptance
test passes, `pytest` green, `ruff check` + `mypy src` clean on touched files,
`spc-demo demo` still byte-for-byte reproducible, no run output committed.
