# Project Charter

## Mission

Build a backend-independent runtime that turns centrally specified video intent into measurable patch-local execution, preserves global consistency through bounded neighbor exchange, and saves real end-to-end computation by reusing stable temporal state.

## Product hypothesis

Video generation and editing can be made faster and more controllable when logical visual workers:

1. share one frozen base model rather than replicate it;
2. receive deterministic geometric and semantic work derived from a central scene contract;
3. exchange compact boundary and previous-step context;
4. skip stable interiors only when uncertainty and dependency rules permit;
5. expand repairs from strip → patch → object → frame when local correction is unsafe.

The initial product is a research runtime and command-line workflow. A creator-facing UI is M8, not an early milestone.

## Scope

### In scope

- deterministic baseline generation and complete run receipts;
- `SceneContract`, constraint compilation, dependency graph, affected closure, and write permissions;
- scheduler and denoising hooks for latent snapshots and patch experiments;
- patch parity, halo exchange, reconciliation, and central escalation;
- temporal cache, scene-cut invalidation, uncertainty, and periodic refresh;
- numeric geometry and identity compliance;
- closed-loop local repair;
- at least two video backends behind one control plane;
- license, dataset, experiment, and invention records.

### Deferred

- polished GUI;
- broad support for large model families;
- natural-language conversation among workers;
- feature-film-length generation;
- foundation-model pretraining;
- mobile deployment;
- full custom GPU-kernel rewrite.

## Non-goals and anti-patterns

HIVEFRAME does not count any of the following as success:

- adding workers while total GPU time rises;
- excluding VAE decode to inflate speedup;
- comparing a low-resolution result with a high-resolution baseline;
- cherry-picking easy static scenes;
- blurring seams at the cost of detail;
- copying the entire model into every worker;
- accepting errors only because an evaluator missed them.

## Principles

1. **Measure economics first.** The first five stages prove execution economics, not training scale.
2. **Receipts over anecdotes.** Every result must be attributable to exact code, model, configuration, seed, environment, and measured cost.
3. **Deterministic control.** The director expresses relationships; a compiler converts them into numeric constraints.
4. **Shared weights, logical workers.** Worker count is not model replication.
5. **Safe locality.** Local work is allowed only within write permissions and affected closure.
6. **Explicit failure.** Uncertain or conflicting work escalates or fails.
7. **License admission is a hard gate.** No checkpoint or dataset is used until its terms and provenance are recorded.
8. **Training follows diagnosis.** Adapters are used only after the missing behavior and target metric are known.

## Training gate

Training may begin only after all three conditions are met:

- a no-training structural experiment shows computation savings on at least some scenes;
- failures can be attributed to boundary, constraint, or cache modules;
- the adapter target and success metric are explicit.

Actual data requirements will be determined experimentally from adapter size and the selected base model.

## Primary stakeholders

- runtime and systems researchers;
- diffusion/backend integration engineers;
- evaluation and data-governance owners;
- future creator-product users.

## First priority

**M0 — Reproducible Baseline** is the only first implementation priority. It must reproduce a pinned backend under identical conditions and record every relevant cost and quality dimension before patch optimization begins.

## Decision record

The default strategy is:

> Use Wan as the primary commercial renderer, keep LTX as the control and audio research backend, and develop the central contract, patch workers, neighbor boundary protocol, and temporal cache as a model-independent runtime. Train only minimal adapters after structural bottlenecks have been measured.
