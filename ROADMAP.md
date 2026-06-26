# ROADMAP — cas.spc

Derived from `PILOT_SPEC.md` §22. Each phase has a single exit gate. Phases
should not be merged out of order — later phases assume earlier invariants
hold.

---

## Phase 0 — Pilot Spec ✅

Frozen as `PILOT_SPEC.md`. Defines purpose, scope, architecture, demo, and
acceptance criteria.

**Exit gate:** spec is the canonical reference for every contributor.

---

## Phase 1 — Repo scaffold _(in progress)_

- `pyproject.toml` with Python 3.11+, Pydantic v2, pytest, ruff.
- `README.md`, `AGENTS.md`, this `ROADMAP.md`, `PILOT_SPEC.md` mirrored in repo.
- `src/spc_state/` package skeleton.
- `examples/` with the AI-coding-assistant scenario (spec §8.1).
- `.gitignore` excluding `runs/`.
- Smoke test that imports the package and exercises `spc-demo --help`.

**Exit gate:** fresh clone runs `pip install -e ".[dev]"` and `pytest` green.

---

## Phase 2 — Schema lock

- Pydantic v2 models for every primitive in spec §10–11:
  `SemanticObject` base, `Claim`, `Evidence`, `Assumption`, `Inference`,
  `Hypothesis`, `Question`, `Contradiction`, `Relation`, `SemanticState`,
  `SemanticPatch`, `TransformRecord`, `ValidationReport`, `Projection`,
  `ReasoningReceipt`.
- `SemanticState` is frozen (immutable). A test asserts direct attribute
  writes raise.
- JSON Schema export via `model_json_schema()`.
- Round-trip tests against the YAML examples embedded in the spec.

**Exit gate:** `SemanticState` and `SemanticPatch` validate from disk and
round-trip to JSON without loss.

---

## Phase 3 — Deterministic patch loop

- File-based store: `runs/<id>/state/semantic_state_vNNN.json` etc.
- L1 schema validator (Pydantic-driven).
- L2 referential / provenance validator.
- Router: `COMMIT` / `REVIEW` / `REJECT` / `RETRY`.
- Runtime: load → project (stub) → operate → validate → route → commit → audit.
- Deterministic `Extract`, `Planner`, `Critic` operators that pattern-match
  the demo doc.
- `audit_log.jsonl` writer.
- CLI: `spc-demo run --input examples/ai_coding_assistant.txt --run-id demo_001`.
- Test asserts operators **cannot** mutate canonical state directly.

**Exit gate:** document → v1 → patch → v2 → patch → v3 runs deterministically
and is byte-for-byte reproducible across runs.

---

## Phase 4 — Diff and Reasoning Receipt ✅

- `diff` module comparing two state versions by object type
  (`spc_state.diff.diff_states` → `StateDiff`, added/removed/changed with
  field-level before/after, serialized to `runs/<id>/diffs/`).
- Markdown `ReasoningReceipt` generator projecting summary, claims,
  evidence, assumptions, contradictions, open questions, transform history,
  confidence map, and audit from state history
  (`spc_state.receipt.project_receipt` + `render_markdown`, written to
  `runs/<id>/receipts/`). The summary answer is read from the leading
  hypothesis, not re-prompted (§18.3).
- Snapshot test for the receipt (`tests/fixtures/reasoning_receipt_demo.md`).
- Programmatic answers to the spec §8.4 follow-ups via
  `spc_state.receipt.FollowUps`, surfaced by `spc-demo followups`:
  - "What did the critic add?" → reads `transform_log` write-sets + deltas.
  - "Which claims are weakest?" → sorts by confidence + evidence count.
  - "What changed between state v1 and v3?" → diff.
  - …plus assumptions-affecting-conclusion, source-supports-claim,
    unresolved-questions, recommendation-dependency, and
    inferred-vs-observed.

**Exit gate:** system answers §8.4 follow-ups from state, not by re-prompting.
✅ Met — every answer is a read over committed state; no operator is re-run.

> 🎯 **Milestone 1 — End-to-end deterministic demo complete.** ✅

---

## Phase 5 — Projection builder

Replace the projection stub from Phase 3.

- Perspective-specific projections per spec §14.2: planner, critic,
  retriever, verifier, writer.
- Projection invariant tests: an operator that tries to mutate its
  projection raises; operators only see their slice.

**Exit gate:** every operator runs against a perspective-specific projection.

---

## Phase 6 — Mock LLM operator

- `LLMProvider` interface (provider-agnostic).
- `MockProvider` that returns canned patches — valid, invalid, and prose
  ("repair me").
- Mock-backed critic operator exercising the validation-feedback retry path.

**Exit gate:** mock LLM operator produces both valid and invalid patches;
runtime commits one, rejects/retries the others.

---

## Phase 7 — Live LLM critic (Anthropic + OpenAI)

- `AnthropicProvider` (Claude tool-use / structured output).
- `OpenAIProvider` (JSON Schema mode).
- Live critic operator returning a `SemanticPatch`.
- Structured-output enforcement at the API layer.
- Validation-feedback retry loop with a hard cap.
- Provider, model name, and version recorded in
  `TransformRecord.model_fingerprint`.

**Exit gate:** a live LLM critic proposes a patch that the runtime
validates and routes — without direct state mutation.

> 🎯 **Milestone 2 — Live LLM critic in the loop.**

---

## Phase 8 — Baseline comparison + pilot report

- Competent JSON-handoff baseline: summary → critique → final memo.
- Same input document, same model budget.
- Evaluation report across spec §20 metrics:
  semantic continuity, provenance completeness, drift rate, reprocessing
  burden, contradiction detection, assumption sensitivity, state-reuse
  efficiency, audit clarity.
- The §8.5 demo moment captured in writing.

**Exit gate:** pilot report compares SPC engine against the baseline with
quantitative evidence for the hypotheses in spec §4.

> 🎯 **Milestone 3 — Pilot report shipped.**

---

## Phase 9 — Codex handoff _(optional)_

If the pilot succeeds and a second pair of hands joins:

- `CODEX_TASKS.md` with narrow, test-backed PR specs.
- `AGENTS.md` revisited to reflect anything learned.
- Issue list seeded.

**Exit gate:** an outside contributor (human or Codex) can take a task
without violating the architectural invariants.

---

## Deferred (out of scope for v0.1, but kept on the horizon)

- SQLite / Postgres backing store.
- pgvector / FAISS semantic index.
- NetworkX or graph DB for dependency traversal.
- POA-compatible hash-chained packaging.
- Multiple live model providers beyond Anthropic + OpenAI.
- Web UI, state-graph visualizer.
- Multi-user collaboration, auth, permissions.
