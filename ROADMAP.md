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

## Phase 5 — Projection builder ✅

Replaced the projection stub from Phase 3.

- `spc_state.projection.build_projection` ships perspective-specific
  projections per spec §14.2 — planner, critic, retriever, verifier, writer,
  executive (plus extract as a passthrough over the initial state). Each
  perspective selects a different slice (critic → weak claims + weak
  evidence + assumptions; writer → high-confidence claims, no raw evidence;
  planner → decision skeleton, no evidence spans; retriever → evidence gaps +
  open questions; verifier → claims + evidence + provenance; executive →
  recommendation + high-impact risks). Relations are included only when both
  endpoints are in the slice, keeping the projection referentially closed.
- `spc_state.projection.resolve_view` materialises a projection into a frozen,
  deep-copied `ProjectionView` — the slice an operator actually reads. The
  Planner and Critic operators now read through their view, not raw state.
- The runtime builds a perspective-specific projection per step (was the
  passthrough stub); the stub is deleted.
- `Projection`, `IncludedObjects`, and `ProjectionPolicy` are frozen, so an
  operator that receives a projection cannot mutate it.
- Projection invariant tests (`tests/test_projection_invariant.py`): the
  projection is frozen (writes raise); the view is frozen; the view contains
  only its slice; editing a view object leaves canonical state untouched
  (deep copies share no references). Perspective-slice tests in
  `tests/test_projection_builder.py`.

**Exit gate:** every operator runs against a perspective-specific projection.
✅ Met — the runtime builds one per perspective; operators read their slice
through `resolve_view`; the demo stays byte-for-byte reproducible.

---

## Phase 6 — Mock LLM operator ✅

- `spc_state.providers` ships the provider-agnostic seam: `LLMProvider`
  (abstract `complete(ProviderRequest) -> ProviderResponse`), where a
  response carries the model's **raw** text plus a `ModelFingerprint`. The
  provider never parses or commits — the runtime does.
- `MockProvider` returns scripted completions (one per call, last repeats).
  Canned builders land on each outcome: `build_valid_critic_payload` →
  COMMIT, `build_invalid_critic_payload` (ghost update target) → REJECT,
  `PROSE_RESPONSE` (not JSON) → RETRY.
- `MockLLMCriticOperator` (`operators/llm.py`, an `LLMOperator`) turns its
  critic projection slice — plus any prior validation feedback — into a
  prompt and delegates to the provider. It never mutates state.
- The runtime gained a validation-feedback retry loop (`Runtime.step_llm`,
  spec §15.6): validate → route → on RETRY, pass the issue codes/messages
  back to the operator and ask again, up to `operator.max_attempts` (hard
  cap). State commits only on a clean COMMIT; the committed patch records
  the `model_fingerprint`. The validator now accepts a raw `str` payload
  (prose → `L1.JSON_DECODE`).
- Tests (`tests/test_mock_provider.py`, `tests/test_runtime_llm_retry.py`):
  COMMIT, REJECT, prose→RETRY→COMMIT, retry-cap exhaustion, and that the
  feedback actually reaches the second prompt.

**Exit gate:** mock LLM operator produces both valid and invalid patches;
runtime commits one, rejects/retries the others. ✅ Met — valid → COMMIT,
ghost-ref → REJECT, prose → RETRY (then repairs and commits on feedback);
the deterministic demo stays byte-for-byte reproducible.

---

## Phase 7 — Live LLM critic (OpenRouter) ✅

> Design change from the original plan: instead of separate `AnthropicProvider`
> and `OpenAIProvider`, the live seam is a single **`OpenRouterProvider`**.
> OpenRouter is OpenAI-compatible, so one provider reaches ~1000 models
> (Anthropic, OpenAI, Google, DeepSeek, Meta, Qwen, …) behind one `model`
> string. Model choice is per-run and biased toward **value, not frontier**.

- `spc_state.providers.OpenRouterProvider` — talks to OpenRouter's
  OpenAI-compatible Chat Completions API through the `openai` SDK
  (`base_url=https://openrouter.ai/api/v1`). Model resolves from
  constructor arg → `SPC_OPENROUTER_MODEL` → a value-based default
  (`deepseek/deepseek-chat`); key from `OPENROUTER_API_KEY`. A client can be
  injected for testing (no network/key needed). `VALUE_MODELS` curates a few
  cheap slugs; any OpenRouter slug works.
- `LLMCriticOperator` (generalised from Phase 6's mock-only operator;
  `MockLLMCriticOperator` kept as an alias) — provider-agnostic, drives the
  same critic prompt against mock or live providers.
- Structured-output enforcement at the API layer: `response_format=
  {"type": "json_object"}` (broad model support) plus the existing
  validation-feedback retry loop with a hard cap (`Runtime.step_llm`,
  spec §15.6). Strict `json_schema` was rejected — it would shrink the
  usable model set.
- Provider, model, and resolved model version recorded in
  `TransformRecord.model_fingerprint` (`provider="openrouter"`).
- CLI: `spc-demo run --live-critic [--model <slug>]` swaps the deterministic
  critic for the OpenRouter one (fails clearly without a key; run becomes
  non-deterministic). The default deterministic run is unchanged and
  byte-for-byte reproducible.
- Tests (`tests/test_openrouter_provider.py`): config/model resolution,
  request mapping + response parsing, json_object toggle, and full runtime
  runs (commit; prose→retry→commit with feedback reaching the model) using
  an injected fake client.

**Exit gate:** a live LLM critic proposes a patch that the runtime validates
and routes — without direct state mutation. ✅ Met — `OpenRouterProvider`
behind `LLMCriticOperator` runs through `Runtime.step_llm`; state commits
only via the validated patch, and the model fingerprint is recorded.

> 🎯 **Milestone 2 — Live LLM critic in the loop.** ✅
> _(Live network calls are key-gated; CI/tests use an injected client.)_

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
- Per-operator model routing / cost tracking across OpenRouter models.
- Web UI, state-graph visualizer.
- Multi-user collaboration, auth, permissions.
