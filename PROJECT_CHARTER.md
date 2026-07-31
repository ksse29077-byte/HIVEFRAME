# Project Charter

## Mission

Build a commercial visual runtime that reduces real end-to-end video
processing time and GPU cost by observing change with small, purpose-specific
logical eyes and selectively generating only the work that remains necessary.

All economics include observation, fusion, planning, backend execution,
boundary handling, evaluation, and repair. HIVEFRAME succeeds only when that
total is lower than a same-condition conventional video-generation path
without unacceptable quality or control loss.

## Research hypothesis

Different spatial, temporal, resolution, and semantic observations can be
captured without giving every observer a full-fidelity copy of the input.
`EyeObservation` values can be fused into a provenance-preserving
`SharedVisualState`, then compiled into a backend-neutral `ComputePlan`.

The plan may select patches, tokens, model blocks, timesteps, resolution, or
cache operations. These are research candidates, not assumed backend
capabilities or speedup claims.

The falsifiable hypothesis and counterexamples are defined in
[`docs/COMPOUND_EYE_HYPOTHESIS.md`](docs/COMPOUND_EYE_HYPOTHESIS.md).
The official milestone sequence is defined in [`ROADMAP.md`](ROADMAP.md), and
its evidence, cost, safety, and review gates are governed by
[`docs/ROADMAP_EXECUTION_RULES.md`](docs/ROADMAP_EXECUTION_RULES.md).

## Preserved foundation

The architecture rebase does not replace the repository or erase evidence.
It preserves:

- Git history and the `pre-compound-eye-v1` snapshot;
- the Wan 2.1 1.3B M0 execution environment;
- smoke, cold/warm, reproducibility, and memory-admission results;
- RunReceipt 0.1/0.2 compatibility and timing meanings;
- evaluators and backend adapters;
- model and license ledgers;
- the patch-centric architecture as a comparison design in
  [`docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md`](docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md).

## Scope

### In scope

- deterministic Single-Eye Cost Truth baselines and complete run receipts;
- versioned `EyeContract`, `EyeObservation`, `SharedVisualState`, and
  `ComputePlan` contracts;
- purpose-specific global, regional, boundary, motion, and future semantic
  eyes;
- deterministic Sensory Fusion with source, confidence, and uncertainty;
- backend capability negotiation for patch, token, block, timestep,
  resolution, and cache selectors;
- scene contracts, numeric constraints, ownership, and write permissions;
- boundary reconciliation, affected closure, temporal reuse, evaluation, and
  closed-loop repair;
- same-condition economic experiments that include every overhead;
- at least two video backends behind one control plane;
- license, data, experiment, and invention records.

### Deferred

- model or adapter training before a measured need;
- custom CUDA/Triton kernels before a measured bottleneck;
- multi-GPU selective execution;
- polished GUI;
- broad model-family support;
- worker conversation;
- feature-film-length generation;
- foundation-model pretraining;
- mobile deployment.

## Non-goals and anti-patterns

HIVEFRAME does not count any of the following as success:

- presenting the compound-eye structure as proven before backend experiments;
- reporting a compute plan as actual sparse execution;
- adding logical eyes while total observation and GPU work rise;
- excluding fusion, VAE, evaluation, repair, or orchestration from wall time;
- comparing different resolution, frames, steps, scheduler, precision, or
  checkpoint conditions;
- cherry-picking static scenes;
- hiding boundary defects with blur;
- copying the entire input or model for every eye;
- converting unsupported values to zero;
- accepting errors only because an evaluator missed them.

## Principles

1. **Observe before selecting.** Selection is compiled from explicit evidence.
2. **Measure total economics.** Saved backend work must exceed every new cost.
3. **Receipts over anecdotes.** Results identify exact code, model,
   configuration, seed, environment, scope, and method.
4. **Provenance survives fusion.** Every state and decision remains traceable
   to observations and confidence.
5. **Logical eyes are not replicas.** An eye owns a receptive purpose, not
   model weights or a full input copy.
6. **Safe locality.** Regional work cannot escape compiled write permissions.
7. **Uncertainty is actionable.** Conflict causes reconciliation, promotion,
   refresh, or failure.
8. **Capabilities are explicit.** A backend may reject or promote unsupported
   selectors; it cannot silently claim them.
9. **License admission is a hard gate.**
10. **Training follows diagnosis.**

## Training gate

Training may begin only after:

- no-training experiments show a measured structural opportunity;
- failures can be attributed to observation, fusion, planning, boundary,
  backend capability, evaluation, or cache behavior;
- an adapter target and success metric are explicit.

## Current priority

**M0 — Single-Eye Cost Truth** is the preserved Wan Reproducible Baseline.
Existing executions, receipts, smoke gates, and environment fingerprints remain
valid. M0 is not rerun or weakened merely because the architecture hypothesis
changed.

The next research milestone is **M1 — Eye Topology Ground Truth Lab**. It
compares the valid 1×1 Mono Eye and declared multi-eye topologies against oracle
change masks and complete observation costs before any Wan attention-hook or
selective generation change.

## Decision record

> Preserve Wan as the primary baseline renderer and LTX as a future control and
> audio research backend. Test compound-eye observation and selective planning
> as a backend-independent control layer. Retain patch, boundary, temporal
> cache, and repair mechanisms as possible execution tools rather than defining
> the product solely as a patch runtime.
