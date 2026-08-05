# HIVEFRAME Master Work Order

## Product-First execution priority

The normative constitution is maintained only in [`AGENTS.md`](AGENTS.md).
Ship the smallest safe user-visible path, reuse unchanged evidence, and run
only focused, smoke, core end-to-end, fallback, and release-blocking security
checks unless the constitution requires a full suite. The official launch
track is P0 Product Vertical Slice, P1 Live MiniMax H3 Integration, P2 Internal
Alpha, P3 Limited Commercial Beta, and P4 1.0 Release.

The M0–M5 selective-recompute program remains preserved evidence and an
Engine Beta Track. M1-B1/B2 may test at most one backend/selector-cache path
when separately approved; a missing benefit becomes `FALLBACK_ONLY` or `DROP`
and does not block the H3 launch track. A HIVEFRAME 2.0 RFC is not a launch
prerequisite.

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
`M1_B0_LOCALITY_SURFACE_MEASURED`; PR #52 published it at `4ddb6a5...`.
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

The current scope is P0: one local standard-profile product vertical slice
using deterministic Mock H3 fixtures plus a disabled-by-default MiniMax H3
contract. It includes request, job state, result save/download, consent-aware
feedback, bounded manual retry, and external local artifact storage.

It excludes live H3 calls and cost, model loading, CUDA, training, selective
compute, M1-B1/B2, HIVEFRAME 2.0, and product-speedup claims.

## Definition of done for each change

1. Scope and preserved assets are stated.
2. Contracts and failure semantics are explicit.
3. Product-First focused, smoke, core-flow, fallback, and required safety
   verification passes; repeated full suites are skipped unless required.
4. Unsupported and unverified claims remain marked.
5. `TASKS.md` and `docs/WORKLOG.md` reflect the resulting state.
6. One intentional commit contains only the task.
7. External links are recorded only after remote verification.
