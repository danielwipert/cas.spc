# cas.spc — SPC Shared Semantic State Engine

> **Working name:** SPC Reasoning Receipt Engine
> **Status:** Pilot v0.1 — pre-alpha, under construction.

This repository implements the **Shared Semantic State Pilot** for the Semantic
Processing Computer (SPC). It is a small, file-based engine that tests one
architectural claim:

> Compound AI systems should not communicate by passing summaries between LLM
> stages. They should operate over **persistent semantic state**, transformed
> through validated semantic patches.

For the full rationale, hypotheses, scope, and acceptance criteria, see
[`PILOT_SPEC.md`](./PILOT_SPEC.md).
For the architectural invariants that govern every contribution (human or
agent), see [`AGENTS.md`](./AGENTS.md).
For the build sequence, see [`ROADMAP.md`](./ROADMAP.md).

## What this engine does

```text
Input document
      ↓
Extract operator                  → SemanticState v1
      ↓
Planner operator → SemanticPatch  → Runtime validates → SemanticState v2
      ↓
Critic operator  → SemanticPatch  → Runtime validates → SemanticState v3
      ↓
ReasoningReceipt projected from state history
```

Each operator returns a **`SemanticPatch`**, never a mutated state. The
runtime validates the patch, routes it (commit / review / reject / retry),
writes the next state version, and appends an audit event. Follow-up
questions ("what did the critic add?", "which claims are weakest?", "what
changed between v1 and v3?") are answered by querying the state history,
not by re-prompting an LLM.

## Project layout

```text
cas.spc/
  PILOT_SPEC.md          # canonical v0.1 specification
  AGENTS.md              # architectural invariants for contributors / agents
  ROADMAP.md             # phased build plan
  pyproject.toml
  src/spc_state/         # the engine
    models/              # Pydantic models for state, patch, receipt, etc.
    store/               # file-based versioned state store
    validation/          # L1 schema + L2 referential/provenance validators
    router/              # COMMIT / REVIEW / REJECT / RETRY
    runtime/             # the load → project → operate → validate → route loop
    operators/           # extract, planner, critic, retriever, verifier, writer
    projection/          # perspective-specific views of state
    diff/                # state-version comparison
    receipt/             # ReasoningReceipt projection
    audit/               # jsonl audit log writer
    providers/           # LLM provider abstraction (added in Phase 6)
    baseline/            # JSON-handoff control pipeline (Phase 8)
    evaluation/          # §20 metrics + pilot report (Phase 8)
    tokens.py            # dependency-free token estimator
    cli.py               # `spc-demo` entrypoint
  examples/              # demo input documents
  runs/                  # generated; per-run output trees (gitignored)
  tests/
```

## Quickstart

```powershell
# from a fresh clone
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
spc-demo demo                            # narrated end-to-end §8 demo + DEMO.md
spc-demo run --input examples/ai_coding_assistant.txt --run-id demo_001
spc-demo followups --run-id demo_001     # answer §8.4 questions from state
spc-demo report --run-id demo_001        # SPC vs JSON-handoff baseline (§20)
```

`spc-demo demo` is the fastest way to see the whole story: it runs the SPC
engine and the baseline over the §8 scenario, answers the follow-ups live from
state, prints the §20 scorecard, and writes a shareable [`DEMO.md`](DEMO.md).
Add `--live-critic` to prove a real OpenRouter model on the same loop.

`run` writes a complete reproducible artifact tree under `runs/demo_001/`
(state snapshots, patches, validation reports, audit log, diffs, and a
markdown `reasoning_receipt.md`). `report` runs the JSON-handoff baseline over
the same document, scores both pipelines across the spec §20 metrics, captures
the §8.5 demo moment, and writes `report/pilot_report.md` + `report/metrics.json`.
Add `--live-critic [--model <slug>]` to `run` to swap the deterministic critic
for an OpenRouter LLM (needs `OPENROUTER_API_KEY`; the run becomes
non-deterministic).

## Use it on your own documents

The demo run is hardcoded to one scenario, but `analyze` runs the **full live
pipeline** (Extract → Planner → Critic) over *any* document: every claim is
committed with the exact span that supports it, the planner adds a
recommendation and open questions, the critic adjusts weak confidence with a
recorded reason, then a Reasoning Receipt is projected from that state:

```powershell
pip install -e ".[openrouter]"     # the live provider needs the openai SDK
# put OPENROUTER_API_KEY=sk-or-... in a .env file (gitignored), or export it
spc-demo analyze --input path\to\your_document.txt --run-id my_analysis
```

The CLI auto-loads a local `.env`, so a key dropped there is picked up without
exporting it. The output isn't just prose — it's a queryable object graph. Interrogate it
with `spc-demo followups --run-id my_analysis` (what did the critic change?
which claims are weakest? which assumptions drive the conclusion?), all
answered from committed state. Remaining operators (retriever, writer,
contradiction detection) are tracked in [`TASKS.md`](TASKS.md).

## Pilot scope

This engine intentionally does **not** include:
PDF parsing, vector databases, embeddings, autonomous agents, multi-user
collaboration, a UI, real-time orchestration, authentication, or any cloud
infrastructure. Those are deferred. The pilot tests the smallest useful
shared-state kernel.

## License

Copyright © 2026 Daniel Wipert. All rights reserved. See [`LICENSE`](./LICENSE).
