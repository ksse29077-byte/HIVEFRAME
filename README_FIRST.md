# Read This First — HIVEFRAME

## Current repository state

As of 2026-08-05:

- official Compound I/O architecture and roadmap are merged into `main`;
- architecture RFC commit before this worklog addition:
  `041311bf6c3aad144f1a64980a36fd399c6c17d8`;
- preserved pre-rebase tag: `pre-compound-eye-v1` at
  `2bc35ff4a0d442dc5fa43924d719de942960762b`;
- M0 Smoke, regression Smoke, cold/warm, same-seed reproducibility, and
  49-frame memory admission have succeeded on the recorded RTX 3060 host;
- compound-eye schemas and NumPy reference simulation passed 59 model-free
  Python tests and the Rust workspace check;
- repository visibility is `PUBLIC`;
- the RFC branch and annotated preservation tag are published with exact Git
  history;
- RFC Issue
  [`#32`](https://github.com/ksse29077-byte/HIVEFRAME/issues/32) is closed and
  PR [`#33`](https://github.com/ksse29077-byte/HIVEFRAME/pull/33) is merged;
- the model-free Rust I/O admission result is `CONDITIONAL_ADMIT`, not a model
  or product speedup claim;
- Rust I/O PR #36 is merged at `a71eea7...`;
- M1-P0 v1 and M1-P0-R1 returned `REFINE_COST_MODEL`; the R1 same-run Mono
  normalization result was
  `REFINE_COST_MODEL`: Case B T1/T2 paired errors were 61.83% and 56.60%
  against the unchanged 35% rule;
- M1-P0-R2 isolated the Python control-plane overhead and M1-P0-R3 admitted
  the bounded in-process Rust control plane; neither result is a model,
  quality, GPU, or product-speedup claim;
- M1-A2 preserves twelve rights/scene/privacy-reviewed clips and twelve
  deterministic derivatives, but the Guided Oracle remains auxiliary
  observed-change evidence; the current Gate is `ORACLE_PROTOCOL_REVISE`;
- MiniMax H3 is the primary product backend target, with API and future
  open-weight admission still gated separately; Wan remains the frozen M0
  comparator and LTX is inactive;
- M1-B0 is published through PR #52 with bounded Gate
  `M1_B0_LOCALITY_SURFACE_MEASURED`; it is evidence, not a launch prerequisite
  or backend speedup claim.

Always run `git status -sb` and `git rev-parse HEAD` before relying on this
snapshot.

## What HIVEFRAME is

HIVEFRAME is researching a selective-recompute runtime for pretrained video
generation and editing. Its product objective is to reduce complete
accepted-result inference cost through safe state reuse and backend-admitted
selective recomputation.

Compound observation can create purpose-specific evidence for that decision,
but it is a means rather than the product objective. A movement box, pixel
delta, or model-free ComputePlan has no backend skip authority by itself.

This is not yet evidence of sparse speedup. The product goal is to reduce
accepted-result wall time and GPU cost after including every new overhead.

## Product-First priority

The single normative `Product-First Execution Constitution` is in
[`AGENTS.md`](AGENTS.md). Ship the smallest safe user flow, reuse unchanged
evidence, and defer research that does not block that flow.

## What M0 means

M0 is preserved as **Single-Eye Cost Truth**. It is the pinned Wan baseline
against which future selective execution must be compared. Do not delete,
bypass, weaken, or silently rerun it.

## Start in this order

1. Read `AGENTS.md` for the normative Product-First Constitution.
2. Read `docs/HIVEFRAME_EXECUTION_CONTEXT.md` for the compact current-state
   retrieval index and known documentation drift.
3. Read `TASKS.md` for current work and blockers.
4. Read `docs/WORKLOG.md` for verified history.
5. Read `HIVEFRAME_MASTER_WORK_ORDER.md` for project boundaries.
6. Read `ARCHITECTURE.md` and
   `docs/HIVEFRAME_COMPOUND_EYE_RUNTIME_ADDENDUM.md`.
7. For M0 work, read `docs/M0_BASELINE.md`.
8. For compound-eye experiments, read:
   - `ROADMAP.md`
   - `docs/ROADMAP_EXECUTION_RULES.md`
   - `docs/COMPOUND_EYE_HYPOTHESIS.md`
   - `docs/COMPOUND_EYE_ARCHITECTURE.md`
   - `docs/EXPERIMENT_PROTOCOL_EYE_V0.md`
   - `docs/DECISION_GATES_COMPOUND_EYE.md`

## Immediate next action

No next implementation stage is automatically authorized. P0 Local H3 has
been published, and the latest Core evidence on `main` is C3-R2 decision
`C3_R2_RESIDUAL_SIMILARITY_TOO_LOW`. P1 one-click Local H3, M1-B1/B2, and
C3-R3 Compact Residual Correction / Prediction each require a separate
explicit approval. See `docs/HIVEFRAME_EXECUTION_CONTEXT.md` before selecting
work; do not lower C3-R2 thresholds or claim a product speedup from the current
evidence.
