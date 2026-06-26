# SPC Shared Semantic State Pilot — v0.1 Specification

**Project:** Semantic Processing Computer (SPC)  
**Pilot name:** Shared Semantic State Pilot  
**Working product name:** SPC Reasoning Receipt Engine  
**Status:** Pilot specification draft v0.1  
**Date:** June 2026  
**Primary objective:** Prove that compound AI systems can coordinate through governed transformations of persistent semantic state rather than repeated text or JSON handoffs.

---

## 0. Source Lineage

This pilot sits at the intersection of five SPC artifacts:

1. **SPC v1.0 Planning Specification** — establishes the controlled LLM-centered architecture: substrate, memory hierarchy, instruction set, control plane, verification, router, commit, audit.
2. **SPC v2 Vision Specification** — frames semantic objects, semantic programs, semantic runtime, and verified semantic artifacts as the long-term computer architecture.
3. **SPC Brainstorm v0.2 — Shared Semantic Reality** — introduces the central shift from message-passing intelligence to state-transforming intelligence.
4. **SPC Persistent Semantic State Object v0.1 Schema** — defines the initial shared state object, semantic patches, projection model, transaction protocol, validation layers, and Reasoning Receipt schema.
5. **SPC State Engine v0.1 Prototype Repo** — implements a first deterministic, file-based proof of the state/patch/receipt loop.

This document does not replace those artifacts. It translates them into a concrete pilot: what we are trying to prove, what we are not trying to prove, what the system should do, what the demo should show, and what success means.

---

## 1. Executive Summary

The pilot tests a simple but important architectural claim:

> Compound AI systems should not communicate primarily by passing summaries between agents. They should operate over persistent semantic state.

Most LLM workflows today work like this:

```text
Input document
→ LLM summary
→ LLM critique
→ LLM rewrite
→ LLM final answer
```

Each stage receives text, reconstructs meaning, reasons internally, emits another textual or JSON artifact, and discards most of its internal representational state. Even when the handoff is structured JSON, the receiving stage must still reconstruct the broader semantic situation: which claims matter, which assumptions are fragile, which evidence supports which conclusion, what changed, what was rejected, what is uncertain, and what depends on what.

The SPC alternative is:

```text
Input document
→ Persistent Semantic State v1
→ Semantic Patch proposed by planner
→ Runtime validates and commits State v2
→ Semantic Patch proposed by critic
→ Runtime validates and commits State v3
→ Semantic Patch proposed by retriever/verifier/writer
→ Reasoning Receipt projected from state history
```

In this model, the output of one stage is not a message to be reread by another model. It is a governed state transition. A transform does not merely respond. It proposes a patch against a shared semantic state. The runtime validates the patch, routes it, commits or rejects it, increments the state version, and records the action in audit.

The pilot’s purpose is to determine whether this architecture produces measurable advantages in continuity, auditability, provenance, follow-up reasoning, and state reuse.

The pilot is intentionally narrow. It does not attempt to build the full Semantic Processing Computer. It does not attempt autonomous agents, long-term memory at scale, PDF-native parsing, vector geometry, UI polish, distributed orchestration, or enterprise integration. It tests the smallest useful shared-state kernel.

The desired pilot outcome is a compelling demo in which a user can ask:

```text
What did the critic add?
Which claims are weakest?
Which assumptions most affect the conclusion?
Which source supports this claim?
What changed between state v2 and state v5?
Which open questions remain unresolved?
```

The SPC system should answer from its semantic state. A baseline prompt-chain system must reconstruct the answer from prior text.

That is the pilot’s central demo moment.

---

## 2. Core Thesis

### 2.1 Pilot Thesis

A compound AI system becomes more reliable, inspectable, and reusable when its stages operate through semantic state transitions rather than serialized message handoffs.

### 2.2 More Precise Form

The pilot tests whether a persistent semantic state object, governed by semantic patches and a commit protocol, can reduce the failure modes caused by repeated language-based reconstruction in multi-stage LLM workflows.

### 2.3 Short Form

> SPC computes by transforming persistent meaning-bearing state.

### 2.4 What This Means Practically

The pilot does not claim that we can preserve the hidden latent state of an LLM. With current API-based models, we cannot directly extract or transfer a model’s internal activation state across stages.

The claim is more practical and more governable:

> Externalize the important reasoning state into typed, persistent, auditable semantic objects so later operators do not need to reconstruct the entire problem from prose.

The pilot therefore starts with explicit symbolic-semantic state: claims, evidence, assumptions, relations, inferences, contradictions, questions, confidence, provenance, and transform history.

---

## 3. Why This Pilot Exists

### 3.1 The Failure Mode in Current Compound AI Systems

Modern compound AI systems often combine several LLM calls:

```text
Planner
→ Researcher
→ Critic
→ Verifier
→ Writer
```

The usual interface between these stages is language: prose, markdown, JSON, YAML, tool output, or some mixture. JSON is better than prose because it provides explicit fields, structural constraints, and validation opportunities. But JSON handoff still usually behaves as a message rather than a computational state.

A typical handoff might say:

```json
{
  "summary": "The paper introduces a method that improves benchmark performance.",
  "limitations": ["Small sample", "Narrow evaluation"],
  "next_steps": ["Check benchmark validity", "Compare to prior methods"]
}
```

That is useful. But it does not fully preserve the reasoning landscape:

- Which claims were extracted from which source spans?
- Which claims were inferred rather than observed?
- Which assumptions support the conclusion?
- Which assumptions would change the conclusion if false?
- Which hypotheses were considered but rejected?
- Which objections were added by the critic?
- Which evidence was weak but suggestive?
- Which claims changed confidence over time?
- Which contradictions remain unresolved?
- Which state existed before and after each operator?

Current systems often lose this information. The result is semantic drift, repeated reconstruction cost, weak auditability, and poor follow-up reasoning.

### 3.2 Why Locked JSON Was a Good Step but Not the End State

Locked JSON improved the situation by forcing structure between stages. It reduced ambiguity and made validation possible.

But locked JSON answers this question:

> What should the next component be told?

The pilot asks a deeper question:

> What computational state should the next component inherit?

Once JSON becomes rich enough to carry stable object IDs, evidence pointers, assumptions, relations, dependency graphs, contradictions, confidence history, and transform logs, it is no longer just a handoff format. It has become a serialization of semantic state.

That is the transition point.

The pilot keeps JSON as a storage and serialization layer. It stops treating JSON as the architecture.

### 3.3 The Pilot’s Architectural Move

The architectural move is:

```text
From: Agent → Message → Agent → Message → Agent
To:   State → Transform → Patch → Commit → State
```

The receiving operator does not inherit a summary. It inherits a projection of the current semantic state. It then proposes a patch. The runtime, not the LLM, decides whether that patch becomes durable state.

---

## 4. Pilot Hypotheses

The pilot should test several hypotheses.

### H1 — State Continuity

A persistent semantic state will preserve claims, caveats, dependencies, assumptions, contradictions, and evidence links more reliably than a prompt chain.

### H2 — Reduced Reprocessing

Later stages will require less re-reading and re-derivation because they can operate over existing structured state.

### H3 — Stronger Auditability

The system will be able to explain how a claim entered the state, which transform produced it, what evidence supports it, which assumptions it depends on, and what later conclusions used it.

### H4 — Better Follow-Up Reasoning

The system will answer follow-up questions by querying or traversing state rather than reconstructing the original reasoning from prose.

### H5 — More Governable LLM Use

By requiring LLM operators to emit semantic patches rather than final answers, the architecture will make LLM behavior easier to validate, route, reject, retry, and audit.

### H6 — Clearer Multi-Agent Coordination

Different operators — planner, critic, retriever, verifier, writer — can specialize by perspective without creating separate private realities.

---

## 5. Pilot Non-Hypotheses

The pilot should not overclaim.

It does not need to prove:

- That SPC can outperform every prompt chain on answer quality.
- That semantic state is cheaper for trivial tasks.
- That hidden model cognition can be transferred between LLMs.
- That the system solves hallucination completely.
- That LLM judgment is authoritative.
- That the schema is final.
- That the architecture is ready for enterprise deployment.
- That the state model is mathematically complete.
- That vector geometry is required in v0.1.
- That autonomous agents should be introduced immediately.

The pilot’s job is narrower:

> Prove that persistent semantic state plus semantic patches is a viable and valuable coordination substrate for compound AI workflows.

---

## 6. Pilot Scope

### 6.1 In Scope

The pilot includes:

1. A persistent semantic state object.
2. A semantic patch object.
3. A file-based state store.
4. Versioned state snapshots.
5. Deterministic patch validation.
6. Deterministic routing: commit, review, reject, retry.
7. An audit log.
8. State diffs.
9. Reasoning Receipt projection.
10. Deterministic demo operators.
11. Later: one live LLM operator forced to return a valid patch.
12. A baseline prompt-chain comparison.
13. Evaluation metrics for continuity, drift, provenance, and reuse.

### 6.2 Out of Scope for v0.1 Pilot

The pilot excludes:

- Full PDF parsing.
- Complex document ingestion.
- Enterprise storage.
- Multi-user collaboration.
- UI development.
- Real-time orchestration.
- Autonomous planning loops.
- Vector databases.
- Embedding geometry.
- Long-term archival memory.
- Authentication and permissions.
- Full POA cryptographic packaging.
- Human review workflow UI.
- Production deployment.

### 6.3 Deferred but Architecturally Relevant

The following are important but deferred:

- SQLite/Postgres storage.
- pgvector or FAISS semantic indexes.
- NetworkX or graph database dependency traversal.
- POA-compatible hash-chained packaging.
- Multiple live model providers.
- Formal benchmark suite.
- Web UI.
- Visual state graph.
- Locking and theorem-package support for DAG work.

---

## 7. Pilot Product Definition

### 7.1 Product Name

Working name:

> **SPC Reasoning Receipt Engine**

Technical name:

> **SPC Shared Semantic State Engine**

### 7.2 Product Description

The SPC Reasoning Receipt Engine ingests a document or problem statement, creates a persistent semantic state, applies multiple semantic transforms as validated patches, and projects the resulting state history into a human-readable Reasoning Receipt.

### 7.3 User-Facing Value Proposition

For any complex analysis, the system can show:

- what claims were made,
- what evidence supports them,
- what assumptions were used,
- what contradictions remain,
- what changed over time,
- which operator contributed what,
- which claims are weakest,
- and how the final answer was derived.

### 7.4 Developer-Facing Value Proposition

For developers building compound AI systems, the engine provides a disciplined alternative to brittle prompt chains:

```text
No direct state mutation.
No unvalidated generated outputs.
No opaque handoffs.
No silent overwrites.
No unsupported promotion of claims.
```

Operators propose patches. The runtime validates and commits.

---

## 8. North Star Demo

### 8.1 Demo Setup

Input:

A short research paper excerpt, AI paper abstract, business memo, or AI adoption scenario.

Example pilot document:

```text
A company is evaluating whether to adopt an AI coding assistant. The engineering team expects productivity gains, but finance is concerned about usage-based costs. Security has concerns about source code exposure. Prior benchmark studies suggest coding assistants can accelerate routine tasks, but evidence is weaker for complex architecture work.
```

### 8.2 Baseline Flow

```text
Document
→ LLM summary
→ LLM critique
→ LLM final memo
```

The baseline should produce a plausible final answer, but it should not preserve durable semantic state.

### 8.3 SPC Flow

```text
Document
→ Extract initial SemanticState v1
→ Planner proposes Patch p2
→ Runtime validates and commits State v2
→ Critic proposes Patch p3
→ Runtime validates and commits/reviews State v3
→ Retriever proposes Patch p4 identifying evidence gaps
→ Writer projects final memo from State v4
→ Reasoning Receipt explains state evolution
```

### 8.4 Demo Follow-Up Questions

After both systems produce final answers, ask:

```text
What did the critic add?
Which claims are weakest?
Which assumptions most affect the conclusion?
Which source supports this claim?
What changed between state v1 and state v3?
Which unresolved questions remain?
Which final recommendation depends on the security assumption?
Which claims were inferred rather than observed?
```

The SPC system should answer these directly from semantic state and transform history.

The baseline must reconstruct from conversation history or rerun analysis.

### 8.5 The Demo Moment

The most important moment is not a better paragraph of prose. It is the visible difference between:

```text
"Let me reason through that again."
```

and:

```text
"Here is the exact object, patch, dependency, and state version where that entered the analysis."
```

---

## 9. System Architecture

### 9.1 High-Level Architecture

```text
Input Document / Problem
        ↓
Ingestion Operator
        ↓
SemanticState v1
        ↓
Projection Builder
        ↓
Operator receives perspective-specific projection
        ↓
Operator proposes SemanticPatch
        ↓
Patch Validator
        ↓
Router: COMMIT / REVIEW / REJECT / RETRY
        ↓
State Store writes SemanticState vN+1
        ↓
Audit Log records transaction
        ↓
Receipt Projector generates ReasoningReceipt
```

### 9.2 Conceptual Architecture

The pilot has five conceptual layers.

#### Layer 1 — Semantic Objects

Objects include claims, evidence, assumptions, relations, inferences, contradictions, hypotheses, and questions.

#### Layer 2 — Semantic State

The canonical versioned store of objects and relations.

#### Layer 3 — Semantic Patch

The unit of proposed change to state.

#### Layer 4 — Runtime Control Plane

The validator, router, committer, versioner, and audit recorder.

#### Layer 5 — Projections and Receipts

Human-facing and operator-facing views of state.

### 9.3 Pilot Architecture Compared to SPC v1

SPC v1 focused on artifacts moving through a controlled LLM-centered architecture:

```text
LOAD → EXECUTE → VERIFY → ROUTE → COMMIT / REVIEW / REJECT → AUDIT
```

The pilot applies the same control philosophy to semantic state transitions:

```text
BUILD PROJECTION → EXECUTE OPERATOR → VALIDATE PATCH → ROUTE → COMMIT STATE VERSION → AUDIT
```

The core continuity is:

> Do not trust generation. Trust the commit protocol.

---

## 10. Core Primitives

### 10.1 SemanticState

The canonical shared state of a problem, document, decision, or argument.

It stores:

- entities,
- claims,
- evidence,
- assumptions,
- relations,
- inferences,
- hypotheses,
- questions,
- contradictions,
- transform records,
- committed patches,
- rejected patches,
- current state version,
- and state metadata.

### 10.2 SemanticObject

A typed meaning-bearing unit inside state.

Required properties:

```text
id
object_type
text
status
epistemic_status
confidence
provenance
dependencies
temporal metadata
governance metadata
```

### 10.3 SemanticPatch

A proposed mutation to state.

A patch may:

- add objects,
- update objects,
- add relations,
- archive objects,
- update confidence,
- add contradictions,
- add questions,
- record transform metadata.

A patch may not mutate state directly.

### 10.4 SemanticTransaction

The runtime process of evaluating a patch.

```text
base state
+ proposed patch
+ validation report
+ router decision
+ optional committed state version
+ audit event
```

### 10.5 Projection

A task-specific view of semantic state.

Operators should not receive the entire state by default. They receive the subset relevant to their role.

### 10.6 TransformRecord

A durable record of what an operator did.

It includes:

- operator name,
- operator version,
- model fingerprint if applicable,
- input state version,
- output state version,
- read set,
- write set,
- confidence changes,
- validation report,
- and status.

### 10.7 ReasoningReceipt

A human-readable and machine-readable projection of state history.

It is the pilot’s primary output artifact.

---

## 11. Semantic State Model

### 11.1 Minimum State Shape

```yaml
SemanticState:
  state_id: sr_001
  schema_version: 0.1.0
  project_id: spc_pilot_001
  name: "AI Coding Assistant Adoption Analysis"
  state_version: 3
  previous_state_version: 2
  status: active

  entities: {}
  claims: {}
  evidence: {}
  assumptions: {}
  inferences: {}
  hypotheses: {}
  questions: {}
  contradictions: {}
  relations: []

  transform_log: []
  pending_patches: []
  committed_patches: []
  rejected_patches: []
```

### 11.2 Claim Object

Claims are propositions. They may be observed, inferred, assumed, speculative, verified, or contradicted.

Example:

```yaml
Claim:
  id: claim_001
  object_type: claim
  claim_type: analytical_claim
  text: "AI coding assistants may improve routine engineering task speed."
  epistemic_status: inferred
  confidence: 0.74
  supporting_evidence:
    - ev_001
  assumptions:
    - assumption_001
  contradicted_by: []
```

### 11.3 Evidence Object

Evidence is observed source material. It should not be collapsed into claims.

Example:

```yaml
Evidence:
  id: ev_001
  object_type: evidence
  source_type: input_document
  source_id: doc_001
  quote_or_span: "Prior benchmark studies suggest coding assistants can accelerate routine tasks."
  reliability: medium
  extracted_by: transform_extract_001
```

### 11.4 Assumption Object

Assumptions are premises not fully proven inside the current state.

Example:

```yaml
Assumption:
  id: assumption_001
  object_type: assumption
  text: "Benchmark improvements will partially transfer to this company's engineering workflow."
  confidence: 0.58
  impact: high
  if_false_effect: "The productivity justification weakens materially."
```

### 11.5 Contradiction Object

Contradictions are preserved rather than flattened.

Example:

```yaml
Contradiction:
  id: contradiction_001
  object_type: contradiction
  claim_a: claim_002
  claim_b: claim_003
  contradiction_type: tension
  severity: medium
  status: unresolved
  resolution_options:
    - retrieve_more_evidence
    - split_claim_by_task_type
    - route_to_human_review
```

### 11.6 Inference Object

Inferences record reasoning dependencies.

Example:

```yaml
Inference:
  id: inf_001
  object_type: inference
  inference_type: abductive
  premises:
    - claim_001
    - assumption_001
  conclusion: claim_004
  confidence_delta: 0.12
  generated_by: transform_planner_001
```

### 11.7 Question Object

Questions represent unresolved information needs.

Example:

```yaml
Question:
  id: q_001
  object_type: question
  text: "Does the productivity evidence transfer to complex architecture work?"
  status: open
  priority: high
  linked_objects:
    - claim_001
    - assumption_001
```

---

## 12. Semantic Patch Protocol

### 12.1 Core Rule

> Operators do not edit state. Operators propose patches.

This is the most important rule in the pilot.

### 12.2 Patch Shape

```yaml
SemanticPatch:
  patch_id: patch_003
  patch_version: 0.1.0
  base_state_id: sr_001
  base_state_version: 2
  proposed_by: critic_transform@0.1.0
  created_at: "2026-06-26T00:12:00Z"

  read_set:
    - claim_001
    - claim_002
    - assumption_001

  add_objects:
    contradictions:
      - contradiction_001
    questions:
      - q_001

  update_objects:
    - object_id: claim_001
      field: confidence
      from: 0.74
      to: 0.62
      reason: "Evidence supports routine task speed but not complex architecture work."

  add_relations:
    - rel_004

  archive_objects: []

  transform_record:
    id: transform_critic_001
    transform_type: critique
    operator: critic_transform
    operator_version: critic_transform@0.1.0
    input_state_version: 2
    output_state_version: null
    read_set:
      - claim_001
      - claim_002
    write_set:
      - contradiction_001
      - q_001

  status: proposed
```

### 12.3 Why Patches Matter

Patches make LLM output inspectable before state mutation.

They allow the runtime to ask:

- Is the patch valid?
- Does the base state version match?
- Do all references resolve?
- Does the patch preserve provenance?
- Does it introduce a contradiction?
- Does it update confidence without evidence?
- Should it commit, route to review, reject, or retry?

### 12.4 Patch Status Values

```text
proposed
validated
committed
rejected
pending_review
superseded
failed_validation
```

### 12.5 Patch Design Constraint

A patch should be small enough to inspect and large enough to represent meaningful work.

Too small:

```text
one patch per field update
```

Too large:

```text
entire final analysis as one giant patch
```

Pilot target:

```text
one patch per operator step
```

---

## 13. Operator Model

### 13.1 Operator Signature

```text
Operator(
  projection,
  goal,
  constraints,
  operator_config
) → SemanticPatch
```

The operator receives a projection of state, not the entire state by default.

### 13.2 Pilot Operators

The pilot should include these operators:

#### Extract Operator

Creates initial semantic state from input document.

Writes:

- claims,
- evidence,
- assumptions,
- relations.

#### Planner Operator

Adds possible implications, candidate paths, and decision options.

Writes:

- hypotheses,
- inferences,
- questions,
- relations.

#### Critic Operator

Identifies weak claims, missing assumptions, contradictions, and overreach.

Writes:

- contradictions,
- confidence updates,
- questions,
- assumptions,
- relations.

#### Retriever Operator

Identifies evidence gaps and source targets.

Writes:

- questions,
- evidence gap objects,
- source target notes,
- optional evidence objects if retrieval is implemented.

#### Verifier Operator

Checks claim/evidence alignment, provenance, and confidence sanity.

Writes:

- validation flags,
- confidence updates,
- review recommendations.

#### Writer Operator

Does not create canonical truth by default. It projects the current state into a human-readable memo.

Writes:

- projection artifacts,
- optionally final conclusion objects if routed through patch protocol.

### 13.3 Deterministic Operators First

The first pilot should keep operators deterministic. This tests state and patch architecture without model variability.

### 13.4 LLM Operators Second

After deterministic operators pass tests, replace one operator with a live LLM operator.

First candidate:

> Critic Operator

Reason:

- Critique is useful and visible.
- It can add contradictions and questions.
- It tests whether an LLM can propose valid patches.
- It does not require perfect source extraction.

### 13.5 Operator Contract

Every operator must obey:

```text
1. Receive projection.
2. Return SemanticPatch.
3. Never mutate SemanticState directly.
4. Include read_set and write_set.
5. Include TransformRecord.
6. Preserve provenance for new claims.
7. Do not silently drop uncertainty.
8. Do not overwrite objects without versioned update.
```

---

## 14. Projection Model

### 14.1 Why Projections Exist

Operators should not all see the same flat state.

A critic needs weak claims and assumptions. A writer needs high-confidence claims and caveats. A retriever needs evidence gaps. A planner needs goals and dependencies.

The underlying state remains shared. The projection changes.

### 14.2 Standard Perspectives

| Perspective | Primary focus |
|---|---|
| Planner | goals, options, dependencies, candidate paths |
| Critic | assumptions, contradictions, weak evidence, failure modes |
| Retriever | evidence gaps, source targets, open questions |
| Verifier | claim/evidence alignment, provenance, confidence sanity |
| Writer | high-confidence claims, narrative order, audience, caveats |
| Executive | recommendation, risks, tradeoffs, decision options |

### 14.3 Projection Shape

```yaml
Projection:
  projection_id: proj_critic_003
  base_state_id: sr_001
  base_state_version: 2
  perspective: critic
  goal: "Identify weak claims and unsupported assumptions."
  included_objects:
    claims:
      - claim_001
      - claim_002
    assumptions:
      - assumption_001
    evidence:
      - ev_001
    contradictions: []
  projection_policy:
    include_low_confidence_claims: true
    include_evidence_spans: true
    include_dependency_edges: true
    include_writer_notes: false
```

### 14.4 Projection Invariant

> A projection may hide or emphasize parts of state, but it must not mutate canonical state.

---

## 15. Runtime and Commit Protocol

### 15.1 Runtime Loop

```text
1. Load current SemanticState.
2. Build perspective-specific Projection.
3. Run operator.
4. Receive SemanticPatch.
5. Validate patch.
6. Route patch.
7. Commit, review, reject, or retry.
8. If committed, write new SemanticState version.
9. Append audit event.
10. Optionally regenerate ReasoningReceipt.
```

### 15.2 Router Outcomes

```text
COMMIT
REVIEW
REJECT
RETRY
FAIL
```

### 15.3 Commit Requirements

A patch may commit only if:

1. The patch schema is valid.
2. The base state version matches the current state version or can be safely rebased.
3. All referenced objects resolve.
4. New major claims include provenance.
5. Confidence values are valid.
6. Hard constraints are satisfied.
7. The router returns `COMMIT`.

### 15.4 Review Requirements

A patch should route to review if:

- it introduces a contradiction,
- it makes a large confidence update without strong evidence,
- it creates high-impact assumptions,
- it makes interpretive leaps,
- it triggers L3 model-judgmental concern,
- or it affects locked objects.

### 15.5 Reject Requirements

A patch should reject if:

- schema is invalid,
- base state version is wrong and cannot rebase,
- references do not resolve,
- confidence values are out of range,
- required provenance is missing,
- it attempts direct overwrite of committed state,
- or it violates hard constraints.

### 15.6 Retry Requirements

A patch should retry if:

- the operator output is malformed but likely recoverable,
- required fields are missing,
- patch shape is wrong,
- the LLM returned prose instead of patch,
- or the output can be repaired by passing validation errors back to the operator.

---

## 16. Validation Layers

The pilot should use a four-layer validation stack.

### 16.1 L1 — Deterministic Schema Validation

Checks:

```text
valid JSON
required fields present
correct object types
ID uniqueness
confidence in [0, 1]
base_state_version present
read_set and write_set present
transform_record present
patch status valid
```

L1 failures reject or retry.

### 16.2 L2 — Referential and Provenance Validation

Checks:

```text
referenced object IDs exist
add_relations source/target objects exist
update_objects specify from/to values
evidence references resolve
new claims include provenance or explicit speculative status
no direct mutation outside patch protocol
no silent overwrite of committed objects
```

L2 failures reject or retry.

### 16.3 L3 — Model-Judgmental Review

Checks:

```text
unsupported claim risk
overconfident inference risk
subtle contradiction risk
claim/evidence mismatch risk
interpretive overreach risk
```

L3 is a smoke alarm, not an enforcement oracle. It can flag for review. It should not be the only basis for final rejection unless paired with deterministic or provenance failure.

### 16.4 L4 — Heuristic Validation

Checks:

```text
large confidence jumps without new evidence
too many claims from small input
unusually broad conclusion from narrow evidence
missing assumptions for major recommendations
empty evidence set for high-confidence claims
```

L4 can flag for review.

---

## 17. Storage Model

### 17.1 File-Based First

The pilot should remain file-based until the model stabilizes.

Recommended structure:

```text
spc_state_engine/
  src/spc_state/
  examples/
  runs/
    demo_001/
      input/
        input.txt
      state/
        semantic_state_v000.json
        semantic_state_v001.json
        semantic_state_v002.json
        semantic_state_v003.json
      patches/
        patch_001.json
        patch_002.json
        patch_003.json
      validation/
        validation_001.json
        validation_002.json
        validation_003.json
      receipts/
        reasoning_receipt_v003.md
      audit/
        audit_log.jsonl
      diffs/
        diff_v001_v003.json
  schemas/
    semantic_state.schema.json
    semantic_patch.schema.json
    validation_report.schema.json
  tests/
```

### 17.2 Why File-Based Storage Is Correct for the Pilot

File-based storage gives:

- transparency,
- easy inspection,
- reproducible demos,
- version snapshots,
- simple git diffs,
- low setup cost,
- no database migration overhead.

A database should come later.

### 17.3 Later Database Model

Later versions can move to:

```text
Postgres
JSONB for semantic objects
pgvector for embeddings
NetworkX or graph database for dependency traversal
object storage for source artifacts
```

But v0.1 should avoid infrastructure complexity.

---

## 18. Reasoning Receipt

### 18.1 Purpose

A Reasoning Receipt is the human-readable proof of what happened inside semantic state.

It should show:

- summary,
- claims produced,
- evidence used,
- assumptions,
- contradictions,
- open questions,
- transform history,
- confidence changes,
- patch decisions,
- state diffs,
- unresolved issues.

### 18.2 Receipt Shape

```yaml
ReasoningReceipt:
  receipt_id: rr_001
  state_id: sr_001
  state_version: 3
  generated_at: "2026-06-26T00:30:00Z"

  summary:
    question: "Should the company adopt an AI coding assistant?"
    answer: "Proceed with a controlled pilot focused on routine engineering tasks, subject to security and cost controls."

  claims_produced:
    - claim_001
    - claim_002

  evidence_used:
    - ev_001
    - ev_002

  assumptions:
    - assumption_001

  contradictions:
    - contradiction_001

  open_questions:
    - q_001

  transform_history:
    - transform_extract_001
    - transform_planner_001
    - transform_critic_001

  confidence_map:
    strongest_claims:
      - claim_002
    weakest_claims:
      - claim_001
    assumption_sensitive_claims:
      - claim_004

  audit:
    committed_patches:
      - patch_001
      - patch_002
    reviewed_patches:
      - patch_003
    rejected_patches: []
```

### 18.3 Receipt Principle

The receipt is not an explanation generated after the fact. It is a projection from actual state history.

---

## 19. Baseline Comparison

### 19.1 Baseline System

The baseline should be a normal multi-stage LLM workflow:

```text
Input document
→ summarize
→ critique
→ final memo
```

It may use JSON handoffs. That is important. The pilot should not compare SPC against a weak strawman. The baseline should be a competent structured prompt chain.

### 19.2 Baseline Capabilities

The baseline can include:

- structured JSON summary,
- structured critique,
- final memo,
- simple list of assumptions,
- simple list of risks.

### 19.3 What the Baseline Lacks

The baseline usually lacks:

- stable object identity,
- durable state versions,
- patch-level audit,
- dependency traversal,
- evidence-to-claim graph,
- confidence history,
- contradiction objects,
- transform records,
- state diffs,
- follow-up query over state.

### 19.4 Fairness Rule

The baseline should receive the same input and approximately the same model budget as the SPC version once live LLM operators are introduced.

---

## 20. Evaluation Metrics

### 20.1 Semantic Continuity

Question:

> Did later stages preserve earlier distinctions, caveats, dependencies, and uncertainty?

Measurement:

- manually score preservation of key distinctions,
- count dropped caveats,
- count mutated claims without new evidence.

### 20.2 Provenance Completeness

Question:

> What percentage of major claims trace to evidence, assumptions, or explicit speculation?

Measurement:

```text
major_claims_with_provenance / total_major_claims
```

### 20.3 Drift Rate

Question:

> How much did claims mutate without new evidence?

Measurement:

- compare claim text across stages,
- flag changed claims without new evidence or explicit transform reason.

### 20.4 Reprocessing Burden

Question:

> How much source material had to be reread or regenerated at each stage?

Measurement:

- count tokens passed into each operator,
- count repeated source spans,
- count full-document re-ingestions.

### 20.5 Contradiction Detection

Question:

> Did the system preserve conflicts as objects?

Measurement:

- number of contradictions identified,
- number of contradictions linked to claims,
- number of contradictions resolved or routed for review.

### 20.6 Assumption Sensitivity

Question:

> Can the system identify which assumptions drive conclusions?

Measurement:

- dependency traversal from assumptions to claims/conclusions,
- ranking of high-impact assumptions.

### 20.7 State Reuse Efficiency

Question:

> Can follow-ups query state instead of rerunning the pipeline?

Measurement:

- number of follow-up questions answered from existing state,
- no new source reprocessing required,
- latency and token comparison.

### 20.8 Audit Clarity

Question:

> Can a human inspect how the answer emerged?

Measurement:

- receipt readability,
- transform history completeness,
- patch decision clarity,
- state diff clarity.

---

## 21. Acceptance Criteria

### 21.1 Minimum Technical Acceptance

The pilot is minimally successful when:

1. A document can be converted into `SemanticState v1`.
2. At least two operators propose valid `SemanticPatch` objects.
3. The runtime validates patches before mutation.
4. The runtime commits valid patches into new state versions.
5. Invalid patches are rejected or routed to review.
6. Every committed patch increments state version.
7. State diffs can show what changed between versions.
8. A Reasoning Receipt can be generated from state history.
9. The system can answer demo follow-up questions from state.
10. Tests prove operators cannot directly mutate canonical state.

### 21.2 Strong Technical Acceptance

The pilot is strongly successful when:

1. One live LLM operator can reliably return valid patches.
2. Invalid LLM outputs are caught by validation.
3. The system can retry malformed patches.
4. Follow-up questions are answered without re-running the entire analysis.
5. Baseline comparison shows better provenance, lower drift, or stronger audit clarity.
6. The receipt makes the semantic state evolution legible to a non-developer.

### 21.3 Narrative Acceptance

The pilot is narratively successful when the demo makes this obvious:

> The answer was not simply generated. It was projected from an auditable semantic state.

---

## 22. Implementation Phases

### Phase 0 — Pilot Spec

Deliverable:

- This document.

Exit gate:

```text
Pilot purpose, scope, architecture, demo, and acceptance criteria are clear.
```

### Phase 1 — Repo Hardening

Deliverables:

- clean README,
- pyproject polish,
- test command,
- example input,
- deterministic demo command,
- no generated cache files committed.

Exit gate:

```text
Fresh clone can run demo and tests.
```

### Phase 2 — Schema Lock

Deliverables:

- Pydantic models,
- JSON Schema export,
- model tests,
- documented invariants.

Exit gate:

```text
SemanticState and SemanticPatch validate from disk.
```

### Phase 3 — Deterministic Patch Loop

Deliverables:

- extract operator,
- planner operator,
- critic operator,
- patch validation,
- routing,
- commit,
- state snapshots,
- audit log.

Exit gate:

```text
Document → state v1 → patch → state v2 → patch → state v3 works deterministically.
```

### Phase 4 — Diff and Receipt

Deliverables:

- state diff,
- receipt generator,
- receipt snapshot tests,
- follow-up query examples.

Exit gate:

```text
System can answer what changed and generate a useful Reasoning Receipt.
```

### Phase 5 — Projection Builder

Deliverables:

- planner projection,
- critic projection,
- retriever projection,
- verifier projection,
- writer projection.

Exit gate:

```text
Operators receive perspective-specific projections that do not mutate state.
```

### Phase 6 — Mock LLM Operator

Deliverables:

- provider-agnostic LLM operator interface,
- mock provider,
- structured patch response path,
- validation tests.

Exit gate:

```text
Mock LLM operator can produce valid and invalid patches; runtime handles both.
```

### Phase 7 — Live LLM Critic Operator

Deliverables:

- OpenAI or other provider-backed critic operator,
- structured output enforcement,
- validation repair/retry path,
- model fingerprint recording.

Exit gate:

```text
Live LLM critic proposes a patch; runtime validates and routes it without direct state mutation.
```

### Phase 8 — Baseline Comparison

Deliverables:

- baseline prompt chain,
- same input document,
- evaluation report,
- metric comparison.

Exit gate:

```text
Pilot report compares SPC state engine against structured prompt-chain baseline.
```

### Phase 9 — Codex Handoff

Deliverables:

- AGENTS.md,
- ROADMAP.md,
- CODEX_TASKS.md,
- issue list,
- PR sequence.

Exit gate:

```text
Codex can safely continue implementation without violating architecture.
```

---

## 23. Codex Transition Plan

This section is not the immediate next action, but it defines how the project should transition once the pilot is ready.

### 23.1 Codex Should Not Receive a Vague Task

Do not tell Codex:

```text
Build SPC.
```

That is too broad.

Instead, Codex should receive narrow PRs with acceptance tests.

### 23.2 Codex Repository Files

Before Codex begins, add:

```text
AGENTS.md
ROADMAP.md
CODEX_TASKS.md
PILOT_SPEC.md
```

### 23.3 Most Important Codex Rule

```text
No operator may directly mutate SemanticState.
All changes must be proposed as SemanticPatch,
validated, routed, and committed into a new state version.
```

### 23.4 First Codex Tasks

Recommended sequence:

1. Harden repo and tests.
2. Add projection builder.
3. Add mock LLM provider.
4. Add live LLM critic operator.
5. Add structured output enforcement.
6. Add retry path for malformed patches.
7. Upgrade Reasoning Receipt.
8. Add baseline prompt-chain comparison.

---

## 24. POA Compatibility Path

The pilot should not implement full Proof of Analysis packaging yet, but it should avoid design decisions that make POA difficult later.

### 24.1 POA-Relevant Fields

The pilot should preserve:

- input document hash,
- state version hashes,
- patch hashes,
- transform records,
- model fingerprints,
- validation reports,
- router decisions,
- committed outputs,
- rejected patches,
- audit events.

### 24.2 Future POA Package

A future POA for this pilot would package:

```text
input commitment
state snapshots
semantic patches
validation reports
audit log
reasoning receipt
schema versions
operator versions
model fingerprints
root hash
```

### 24.3 Architectural Fit

POA proves the reasoning record.

Semantic state is the living substrate.

Semantic patches are the state transitions.

Reasoning Receipt is the human-facing projection.

---

## 25. Risks and Mitigations

### 25.1 Complexity Explosion

Risk:

The state object becomes too rich too early.

Mitigation:

Start with minimal objects. Add types only when needed by demo or validation.

### 25.2 False Precision

Risk:

Structured state makes weak inference look more rigorous than it is.

Mitigation:

Keep epistemic status, confidence, assumptions, and speculative labels explicit.

### 25.3 Schema Rigidity

Risk:

Rigid schemas suppress open-ended reasoning.

Mitigation:

Use typed core objects with flexible `payload` fields.

### 25.4 LLM Patch Failure

Risk:

Live LLM operators return invalid patches.

Mitigation:

Use structured output, validator feedback, retry, and review routing.

### 25.5 State Drift

Risk:

Persistent state accumulates errors.

Mitigation:

Use versioning, confidence decay, contradiction detection, review routing, and state audit.

### 25.6 Overhead

Risk:

State maintenance costs more than direct prompting.

Mitigation:

Use SPC only for workflows where continuity, provenance, multi-stage reasoning, or auditability matter.

### 25.7 Premature Consensus

Risk:

System collapses contradictions too early.

Mitigation:

Make contradictions first-class objects. Preserve conflict until resolved.

### 25.8 Hidden State Assumption

Risk:

Observers think the pilot transfers internal LLM cognition.

Mitigation:

State clearly: the pilot externalizes reasoning state; it does not transfer hidden activations.

---

## 26. Open Questions

### 26.1 Object Model

1. Should `Relation` become a first-class object or remain an edge table?
2. Should `Constraint` move into the v0.1 core?
3. Should `DecisionOption` be added for business-decision demos?
4. Should `Risk` be a separate object or a claim subtype?
5. Should `Source` be a separate object from `Evidence`?

### 26.2 Patch Semantics

1. How should patch rebasing work?
2. Should multiple patches be batch-committed?
3. Should contradictions force review by default?
4. Should high confidence changes require new evidence?
5. Should patch size limits exist?

### 26.3 Evaluation

1. How do we score semantic continuity objectively?
2. How do we measure drift rate without a gold standard?
3. What is the fairest baseline?
4. What is the minimum number of demo documents?
5. How much token overhead is acceptable?

### 26.4 Product Framing

1. Is the first product a Reasoning Receipt Engine?
2. Is the first buyer a research analyst, legal team, AI governance team, or content pipeline?
3. Should the demo use a research paper or business decision?
4. Is the visual demo a state graph, receipt, or diff viewer?
5. What is the simplest public explanation?

---

## 27. Recommended First Demo Domain

The best first demo domain is probably:

> **AI research paper review for business implications.**

Reason:

- The user already works this way.
- The workflow naturally has technical claims, evidence, assumptions, limitations, implications, and content projection.
- It maps to LinkedIn/content pipeline needs.
- It makes state reuse visible.
- It can later generate post copy, infographic brief, and reasoning receipt from the same state.

### 27.1 Demo Flow for Paper Review

```text
Upload / paste paper excerpt
→ extract entities, claims, evidence
→ technical transform clarifies method
→ skeptic transform identifies limitations
→ business transform maps implications
→ content transform projects LinkedIn post
→ receipt shows all claims, evidence, assumptions, caveats, and transform history
```

### 27.2 Demo Follow-Ups

```text
Which business implication is weakest?
Which claim is most directly supported by the paper?
Which limitation should be mentioned in the LinkedIn post?
What did the skeptic transform add?
What changed after the business transform?
What assumptions make this relevant to enterprise AI buyers?
```

### 27.3 Why This Demo Works

It shows that the final post is not generated from scratch. It is a projection from accumulated semantic state.

---

## 28. Recommended Build Now

The immediate build path should be:

```text
1. Freeze this pilot spec.
2. Add it to the repo as PILOT_SPEC.md.
3. Add ROADMAP.md derived from implementation phases.
4. Add AGENTS.md with architectural invariants.
5. Harden the existing deterministic demo.
6. Add ProjectionBuilder.
7. Add mock LLM operator.
8. Add live critic operator.
9. Run paper-review demo.
10. Generate pilot report comparing against baseline.
```

Do not jump straight to Codex until the pilot spec and invariants are in place.

---

## 29. Pilot Success Narrative

The pilot should end with a simple claim we can show, not just assert:

> In a prompt chain, each stage describes what it thinks the next stage needs. In SPC, each stage proposes a governed update to shared semantic state.

The proof is visible when the user asks:

```text
What changed?
Why did it change?
Who changed it?
What evidence supports it?
What assumptions does it depend on?
What remains unresolved?
```

A conventional LLM workflow has to reconstruct the answer.

The SPC pilot reads the answer from state.

---

## 30. Glossary

### Semantic State

A versioned, typed, auditable representation of the system’s current understanding of a problem.

### Shared Semantic Reality

The human-facing phrase for persistent semantic state shared by multiple operators.

### Semantic Object

A typed meaning-bearing unit inside semantic state: claim, evidence, assumption, contradiction, inference, question, etc.

### Semantic Patch

A proposed mutation to semantic state. Operators produce patches; the runtime validates and commits them.

### Transform

A semantic operation that reads a projection of state and proposes a patch.

### Projection

A perspective-specific view of semantic state given to an operator.

### TransformRecord

A durable record of what an operator read, wrote, changed, and proposed.

### Reasoning Receipt

A human-readable and machine-readable projection of state history.

### Commit Protocol

The validation and routing process that determines whether a patch becomes durable state.

### State Diff

A comparison between two semantic state versions.

### POA

Proof of Analysis: a future portable, hash-chained, verifiable package of the reasoning process.

---

## 31. Final Pilot Definition

The SPC Shared Semantic State Pilot is a controlled experiment in replacing message-passing between LLM stages with governed transformations over persistent semantic state. It uses typed semantic objects, semantic patches, validation layers, deterministic routing, state versioning, audit logs, state diffs, and Reasoning Receipts to test whether compound AI systems can preserve reasoning continuity better than prompt chains or locked JSON handoffs.

The pilot is successful if it demonstrates that final outputs can be projected from auditable semantic state, and that follow-up questions can be answered by inspecting that state rather than reconstructing the reasoning from text.

The shortest working definition remains:

> SPC computes by transforming persistent meaning-bearing state.

