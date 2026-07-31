# HIVEFRAME Master Work Order

## Objective

Develop HIVEFRAME into a commercial compound visual runtime that reduces the
total cost of an accepted video generation or edit by observing and computing
only what is necessary.

The objective is:

```text
minimize(
  observation
  + fusion
  + planning
  + generation
  + boundary
  + audit
  + repair
  + fallback
  + output
)
```

subject to declared quality, identity, geometry, constraint, memory, license,
and silent-failure limits.

## Architecture program

```text
Input sequence + intent
        |
Eye topology including valid 1×1 Mono Eye
        |
EyeObservation[]
        |
Sensory Fusion
        |
SharedVisualState
        |
ComputePlan
        |
Backend capability adapter
        |
Selective or full generation
        |
Audit, repair, fallback, receipt
```

The runtime may choose a single eye when splitting costs more than it saves.
Eye count is a decision variable, not a success metric.

## Work phases

### R0 — Architecture RFC

- preserve the pre-rebase snapshot and legacy architecture;
- publish contracts and the model-free reference implementation;
- make unproven assumptions explicit;
- obtain review before backend integration.

### M0 — Single-Eye Cost Truth

Preserve and complete the pinned Wan same-condition baseline. M0 is the cost
truth and must not include compound-eye optimization.

### M1 — Eye Topology Ground Truth

Build a rights-cleared small clip suite and oracle dirty masks. Compare 1×1,
fixed regional, overlap, motion, and adaptive candidates without model
optimization. Measure detection safety and observation economics.

### M2 — Scout and topology planning

Use measured M1 cost surfaces to select topology. Begin with deterministic
rules; train a small predictor only after sufficient receipts exist.

### M3 — Fusion and dynamic observation

Calibrate confidence, preserve provenance, reconcile coordinates, invalidate on
scene cuts, and adapt observation frequency safely.

### M4 — Perception-to-compute integration

Query backend capabilities and translate only supported selectors. Preserve a
full-compute parity and fallback path.

### M5 — Net selective gain

Claim a gain only when same-condition wall time and actual GPU/backend work
decrease after every added cost and repair is included.

### M6–M8

Add closed-loop adaptation, a second backend, temporal eyes, SDK/API surfaces,
and a creator or B2B product only after earlier gates pass.

## Hard gates

- No unadmitted model, checkpoint, dataset, or evaluation clip.
- No training before structural diagnosis and a measurable target.
- No backend selector claim without capability evidence.
- No speed claim from a model-free simulation.
- No quality claim from a memory-admission probe.
- No skip when uncertainty exceeds the declared policy.
- No milestone completion without receipts, reports, tests, or review evidence.

## Current authorized scope

The current architecture RFC scope includes documents, schemas, deterministic
NumPy reference code, tests, worklog, and Git publication when explicitly
approved.

It excludes model training, LoRA, Wan attention changes, CUDA/Triton kernels,
multi-GPU, GUI, canonical benchmark execution, and actual sparse speedup claims.

## Definition of done for each change

1. Scope and preserved assets are stated.
2. Contracts and failure semantics are explicit.
3. Model-free or approved runtime verification passes.
4. Unsupported and unverified claims remain marked.
5. `TASKS.md` and `docs/WORKLOG.md` reflect the resulting state.
6. One intentional commit contains only the task.
7. External links are recorded only after remote verification.
