# HIVEFRAME Master Work Order

## Objective

Develop HIVEFRAME into a commercial selective-recompute runtime that makes
pretrained video generation and editing inference lighter and faster than the
same accepted-result full-compute path. The runtime may use compound visual
observation to identify candidate reuse and active closures, but multiple Eyes
are an evidence mechanism rather than the product objective.

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

No observation, pixel-delta mask, or human movement box may directly authorize
backend skip. Freeze/reuse requires a supported BackendCapabilityMatrix entry,
dependency and boundary closure, invalidation handling, full-compute fallback,
and a SelectiveComputeReceipt that includes every added cost. Editing is the
first backend validation track; generation follows only after selector
admission. The current protocol is documented in
`docs/HIVEFRAME_SELECTIVE_RECOMPUTE_RUNTIME_DIRECTION.md`.

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

### M1-A — Real-video observation corpus

Preserve a rights-cleared clip suite and auxiliary observation evidence without
promoting visible movement to compute relevance or safe-skip truth.

### M1-B0 — Model-free locality opportunity

Estimate locality opportunity and full-recompute pressure without a backend or
product-speed claim. The dedicated `m1-b0-v1` branch has measured the complete
predeclared C01-C12 surface with NumPy/Rust parity and decision
`M1_B0_LOCALITY_SURFACE_MEASURED`; Draft review and publication remain pending.
This result does not authorize skip or start M1-B1.

### M1-B1 — Backend capability admission

Prove which backend units and reuse operations can actually be selected. An
unsupported selector falls back to full compute.

### M1-B2 — Controlled selective-recompute probe

Validate editing first, then generation, while holding the accepted-result
contract fixed and preserving full-compute parity and fallback.

### M1-B3 — Parallel scaling surface

Measure worker assignment, scheduling, transfer, synchronization, merge, and
repair economics only after a selector is admitted.

### M2–M4 — Planning, freeze/reuse, and compiler integration

Select observation topology, validate reusable state, preserve provenance and
uncertainty, and compile only backend-admitted work.

### M5 — End-to-end net gain

Claim a gain only when same-condition complete accepted-result wall time and
actual GPU/backend work decrease after every added cost and repair is included.

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

The current scope is M1-B0 model-free locality opportunity measurement on the
approved C01-C12 FFV1 derivatives. It includes fixed detector surfaces,
NumPy/Rust parity, decode/resident/streaming cost separation, CPU worker
scaling, receipts, and a Draft PR.

It excludes model training or loading, LoRA, Wan attention changes,
CUDA/Triton kernels, GPU or VRAM benchmarks, backend integration, selective
compute, M1-B1, HIVEFRAME 2.0, and actual product-speedup claims.

## Definition of done for each change

1. Scope and preserved assets are stated.
2. Contracts and failure semantics are explicit.
3. Model-free or approved runtime verification passes.
4. Unsupported and unverified claims remain marked.
5. `TASKS.md` and `docs/WORKLOG.md` reflect the resulting state.
6. One intentional commit contains only the task.
7. External links are recorded only after remote verification.
