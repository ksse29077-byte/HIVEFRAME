# HIVEFRAME Compound-Eye Runtime Addendum

Status: architecture operating addendum; not performance evidence

## Purpose

This addendum clarifies how compound observation can support the selective
recompute product direction without deleting the original patch-centric
safety mechanisms. Compound observation is a means of gathering evidence,
not the product objective and not backend execution authority.

## Topology is adaptive

The valid topology set includes a non-split `1×1 Mono Eye`. Multiple eyes are
used only when their total expected cost is lower while satisfying safety
constraints.

Candidate observation-topology decisions include:

- eye count;
- receptive windows;
- spatial resolution;
- temporal stride and window;
- semantic role;
- overlap width;
- activation and sleep policy;
- backend and hardware capability.

The planner must consider:

```text
C_scout + C_change_detection + C_eyes + C_fusion + C_map_compile
+ C_scheduling + C_active_compute + C_frozen_reuse + C_transfer
+ C_synchronization + C_merge + C_boundary + C_audit
+ expected C_repair_and_fallback + C_output
```

## Global safety path

A low-cost global observation remains available to detect camera motion, scene
cuts, global lighting changes, object relationships, and local-eye blind spots.
It does not automatically justify a full-resolution global representation.

## Conservative state transitions

- `dirty` is only a candidate active region; it has no backend selector
  authority before capability admission.
- `stable` is only a candidate frozen region; it is not safe-skip truth and
  cannot authorize cache reuse by itself.
- `uncertain` blocks skip and promotes to more observation, closure expansion,
  or full computation.
- scene cut invalidates topology-dependent temporal state.

## Relationship to existing modules

| Existing asset | Compound-eye role |
|---|---|
| M0 baseline | 1×1 Single-Eye cost and output truth |
| SceneContract | intent, geometry, ownership, constraints |
| Patch Scheduler | one possible ComputePlan executor |
| Boundary Bus | overlap conflict and seam reconciliation |
| Temporal Cache | candidate reuse after stable evidence |
| Evaluator | output audit and repair routing |
| BackendCapabilityMatrix | capability truth before selector translation |
| ExecutionTopology | hardware-aware worker, queue, transfer, sync, and merge plan |
| Backend adapter | admitted selector translation only |
| RunReceipt | authoritative real-runtime measurement |

## Reversibility

Every topology decision must be promotable:

```text
reobserve
→ overlap/boundary refresh
→ larger regional closure
→ object closure
→ 1×1 full observation or full generation
```

Promotion and fallback costs belong in the final economic comparison.

## Evidence boundary

The current NumPy reference establishes deterministic contracts, coordinate
checks, motion detection on synthetic input, provenance-preserving fusion, and
candidate planning. It does not establish:

- real backend selector support;
- fewer CUDA kernels or tokens;
- quality parity;
- lower end-to-end wall time;
- commercial product value.

Those claims require later decision gates and same-condition receipts.

The normative current direction and claim boundary are defined in
[`HIVEFRAME_SELECTIVE_RECOMPUTE_RUNTIME_DIRECTION.md`](HIVEFRAME_SELECTIVE_RECOMPUTE_RUNTIME_DIRECTION.md).
