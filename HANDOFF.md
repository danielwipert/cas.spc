# Handoff

> **Protocol.** Read this file at the start of every session. Rewrite it at the
> close of every session. It is a **snapshot, not a ledger** — it holds only
> what was just done and what comes next. Overwrite it wholesale each time;
> never append. The durable record lives in git history, `ROADMAP.md`, and
> `TASKS.md` — not here.

**Last session:** 2026-08-26 · **Branch:** `claude/project-status-check-l7zkvl`
(4 commits ahead of `main`, pushed)

---

## Where things stand

Roadmap complete through **Phase 9**; all three milestones shipped. Tasks
T0–T3 are done, T4–T6 open. No code changed this session — the engine does
exactly what it did on 2026-06-27.

All four definition-of-done gates now pass on a fresh clone:

```
ruff check src tests   ->  All checks passed
python -m mypy         ->  Success: no issues found in 62 source files
pytest                 ->  178 passed
spc-demo demo          ->  artifacts byte-identical, DEMO.md unchanged
```

## What the last session did

Housekeeping only. No behavior change anywhere.

- **Established this handoff convention.** `HANDOFF.md` + a pointer at the top
  of `AGENTS.md`, so it is discoverable from the file `TASKS.md` already tells
  every contributor to read first.
- **Refreshed the `AGENTS.md` status block**, which still described the repo as
  of Phase 8. It now covers both entry points — the deterministic byte-stable
  pilot (`demo`/`run`) and the five-stage live pipeline (`analyze`).
- **Fixed stale `--help` text** on `analyze`: the docstring claimed three
  stages while the code ran five, and `--extract-only` said it skipped two.
- **Repaired the ruff and mypy gates**, which the docs claimed were clean and
  which failed 56 / 17 on a fresh clone. Details below — the UP042 note
  matters.

## Gate repair — what a future session needs to know

**Run `python -m mypy`, never bare `mypy`.** The `mypy` on PATH is a
uv-installed tool in an isolated environment that cannot see pydantic, typer or
rich; it reports ~17 phantom `import-not-found` errors. Invoked correctly there
was exactly **one** real error (now fixed: `_issue_from_pydantic_error` took
`dict[str, Any]`, but pydantic passes an `ErrorDetails` TypedDict).

**ruff had drifted** — `>=0.5` resolved to 0.15.8, enabling rules the code
predates. 16 genuine issues auto-fixed, B007 fixed by hand, the rest ignored
with written rationale in `pyproject.toml`. Both linters are now pinned.

> ⚠ **Do not "fix" UP042.** It wants `class X(str, Enum)` → `StrEnum` across
> `models/enums.py`. Verified in a REPL: that changes `str()` and f-string
> output from `ObjectType.CLAIM` to `claim`, which would silently alter every
> rendered receipt and memo and break the byte-stable demo artifacts. The
> ignore is deliberate and documented at the rule.

## Next up

Nothing is half-finished — pick any of these cold.

1. **Planner RETRY fix** (unlisted, cheapest win). The planner currently
   REJECTs when the model returns valid JSON in the wrong shape, because the
   runtime only RETRYs on `JSON_DECODE`. Route shape-invalid output to RETRY
   with targeted feedback ("include a hypothesis"). Noted as a follow-on under
   T0 in `TASKS.md`.
2. **T4 — State-graph visualizer** (M). Mermaid export embedded in the
   receipt; strengthens the §20.8 audit-clarity story.
3. **T5 — Per-operator model routing + cost ledger** (M).
4. **T6 — SQLite `StateStore`** (L) ⚠ relaxes a documented v0.1 constraint —
   needs sign-off before starting.

Full specs with acceptance tests are in [`TASKS.md`](./TASKS.md).

## Before touching code

Read [`AGENTS.md`](./AGENTS.md). The hard invariant: **no operator mutates
`SemanticState` directly** — all change flows through a validated
`SemanticPatch`. The full definition of done is in `TASKS.md`; note that
`spc-demo demo` rewrites `DEMO.md` in the repo root, so run it with the default
`--runs-dir` or the run path gets baked into the committed file.
