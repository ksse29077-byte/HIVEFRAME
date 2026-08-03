# HIVEFRAME Selective Recompute Runtime Direction

Status: protocol predeclaration; no backend result

## Product objective

HIVEFRAME's primary product objective is to make pretrained video generation
and editing inference lighter and faster than the same accepted-result full
compute path. It is not a project to train a new foundation model from
scratch. It seeks to freeze or reuse valid spatial, latent, feature, token,
block, or cache state; selectively recompute only the active dependency
closure; execute that plan with hardware-aware parallelism; and retain global
audit, repair, promotion, and full-compute fallback.

Compound observation is one possible way to acquire evidence. It is not the
product objective and does not itself prove that backend work can be skipped.

The economic claim is admissible only when:

```text
C_selective_accepted
= C_scout
+ C_change_detection
+ C_eye_observation
+ C_map_compile
+ C_scheduling
+ C_active_compute
+ C_frozen_reuse
+ C_transfer
+ C_synchronization
+ C_merge
+ C_boundary
+ C_audit
+ E[C_repair_and_fallback]
+ C_output

C_selective_accepted < C_full_compute_accepted
```

The comparison must keep quality, temporal coherence, safety, rights, license,
and accepted-result criteria fixed. Active-area fraction alone is not a
speedup measurement.

## Observation is not execution authority

Pixel change, a human movement box, optical flow, or an EyeObservation can
suggest where dependency analysis should start. None identifies the actual
backend execution unit by itself. A backend may only admit selectors whose
patch, latent, feature, token, block, timestep, resolution, or cache behavior
has been demonstrated.

```text
observed change evidence
  -> candidate FreezeMap / ActiveMap
  -> dependency and boundary closure
  -> BackendCapabilityMatrix admission
  -> ExecutionTopology
  -> backend selector adapter
  -> measured SelectiveComputeReceipt
```

Until admission, the reference ComputePlan has no selective execution
authority. `dirty` becomes an active candidate, `stable` becomes a frozen
candidate requiring safe-reuse evidence, and `uncertain` promotes to full
compute. A scene cut or other global invalidation clears prior freeze/cache
eligibility.

## State contract

- **FROZEN:** candidate state whose reuse is only legal after backend-specific
  dependency, invalidation, boundary, and quality checks.
- **ACTIVE:** candidate dependency closure to recompute; it is not necessarily
  a pixel patch and does not select a backend unit by itself.
- **UNCERTAIN:** evidence is insufficient or conflicting; skip is forbidden
  and the policy promotes to observation, closure expansion, or full compute.
- **GLOBAL_INVALIDATION:** scene cut or comparable whole-state change; prior
  freeze/cache state is invalid and full re-observation/full compute is the
  safe default.

Frozen, active, and uncertain regions must form a complete, non-overlapping
partition of their declared spatial and temporal scope.

## EyeTopology and ExecutionTopology

`EyeTopology` explains how evidence was observed: receptive fields,
resolution, temporal windows, overlap, and semantic role. `ExecutionTopology`
explains how admitted work is executed: physical/logical CPU, workers,
affinity, RAM, GPU, VRAM, worker assignment, granularity, spatial/temporal
parallelism, batch, streams, queues, synchronization, merge, and
oversubscription. They are separate contracts. Multiple Eyes do not imply
multiple model workers, GPU partitions, or less backend work.

## Editing-first validation

The first backend validation track is controlled local editing because it can
compare an intended edit mask, non-target preservation, dependency closure,
accepted result, and full-compute fallback under a bounded intervention.

The generation track follows only after a backend proves a selector and safe
reuse contract. It must measure actual work reduction, output quality,
temporal coherence, repair/fallback, and complete accepted-result cost. Neither
track is authorized by M1-A2.

## M1-A2 evidence boundary

The C01-C12 Guided Oracle export is classified as:

- `auxiliary_observed_change_evidence`;
- `human_reviewed_or_partially_reviewed`;
- `not_compute_relevance_truth`;
- `not_safe_skip_truth`;
- `not_eligible_for_backend_skip_claim`.

It may inform a future protocol design, but it is not a verified Oracle for
backend compute relevance. Blind re-review, adjudication, and final verified
Oracle promotion under the superseded pixel-change protocol are stopped.

## Protocol-only contracts

- `selective_state_map.schema.json`: combined FreezeMap and ActiveMap contract;
- `backend_capability_matrix.schema.json`: selector support and authority;
- `execution_topology.schema.json`: hardware and scheduling topology;
- `selective_compute_receipt.schema.json`: complete cost/resource/claim record;
- `selective-recompute-protocol.json`: predeclared, result-free example.

Every protocol config records `results_present=false`,
`protocol_status=predeclared`, `model_runs=0`, and `cuda_runs=0`. Unavailable
measurements use exactly a null value, explicit unavailable status and reason,
and method `not measured`; a zero is never invented.

## Evidence needed before a selective-compute claim

1. rights-cleared input and accepted-result evaluator;
2. a backend capability matrix with immutable version evidence;
3. full-compute parity and invalidation/fallback tests;
4. actual backend work reduction, not an inferred active fraction;
5. complete wall, transfer, synchronization, merge, boundary, audit,
   repair/fallback, memory, and byte accounting;
6. quality and temporal deltas under the same conditions;
7. repeatable accepted-result cost below full compute.

No such backend result is present in this change.
