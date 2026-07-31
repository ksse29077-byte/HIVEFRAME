# Architecture

## Current architecture hypothesis

HIVEFRAME is an input-observation and selective-generation runtime. It does not
first treat every frame as one equally rich input and only later split output
into patches.

```text
input sequence + intent
          |
     EyeContract[]
          |
 purpose-specific logical eyes
          |
    EyeObservation[]
          |
     Sensory Fusion
          |
  SharedVisualState
          |
 ComputePlan compiler
          |
 patch | token | block | timestep | resolution | cache selectors
          |
 backend capability adapter
          |
 generation + boundary + evaluation + repair
          |
 receipts + artifacts
```

The detailed RFC is
[`docs/COMPOUND_EYE_ARCHITECTURE.md`](docs/COMPOUND_EYE_ARCHITECTURE.md).
The prior output-side patch-centric design is preserved at
[`docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md`](docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md)
and tag `pre-compound-eye-v1`.

## Control plane and model plane

The deterministic control plane owns contracts, coordinate transforms,
Sensory Fusion policy, state provenance, selector compilation, dependency and
affected-closure rules, boundary and repair policy, ledgers, and receipts.
These structures remain backend-neutral and are candidates for Rust after the
reference contracts stabilize.

Python remains the initial observation and model-integration plane. The v0
reference simulation uses only NumPy. Existing Wan/PyTorch M0 code remains
unchanged and is not imported by the reference path.

## Core contracts

### SceneContract

Scene intent remains the canonical source for objects, identities, landmarks,
masks, boxes, depth, motion, camera, symmetry, count, distance, preserved
regions, edit targets, and evaluator expectations.

### EyeContract

Defines an eye's role, spatial/temporal receptive windows, sampling,
local-to-global transform, write policy, and expected outputs.

### EyeObservation

Carries small derived features, dirty/stable/uncertain reports, confidence,
provenance, and explicit unsupported metrics. It is not a full-frame feature
copy or generated output.

### SharedVisualState

Carries global context and fused regional state while retaining every source
observation and confidence. Conservative fusion converts missing or conflicting
evidence into uncertainty.

### ComputePlan

Maps state to candidate generation, reuse, or reconciliation work. It can
describe patch, token, block, timestep, resolution, and cache selectors without
claiming the backend supports or economically benefits from them.

### RunReceipt

Existing M0 RunReceipt behavior remains authoritative and unchanged:

- schema 0.2.0 uses metadata-bearing measurements;
- immutable 0.1.0 receipts remain accepted;
- CUDA event spans are not GPU kernel-duration sums;
- profiler kernel durations require a separate profiled path;
- generation allocator, process allocator, NVIDIA sampling, and process-tree
  RAM have distinct scopes;
- unsupported metrics are `null` with status, reason, and method;
- memory admission is not an official quality or speed baseline.

The model-free observation receipt is a different kind and cannot satisfy an
M0 backend gate.

## Reference data flow

1. Validate a `[frames, height, width, channels]` NumPy sequence.
2. Compile global, fixed 2×2 regional, overlap-boundary, and motion eye
   contracts.
3. Produce one observation per eye without Torch, CUDA, or model weights.
4. Validate receptive and write scopes.
5. Fuse observations while retaining source and confidence.
6. Compile dirty→generate, stable→reuse candidate, and
   uncertain→reconcile units.
7. Hash contracts, observations, state, and plan in an observation receipt.

## Future backend flow

1. Validate model/data admission and M0 comparator fingerprint.
2. Query backend selector capabilities.
3. Compile intent and observations.
4. Build `SharedVisualState` and affected closure.
5. Translate supported selectors; promote or reject unsupported selectors.
6. Execute shared model weights without per-eye model replication.
7. Exchange bounded context where required.
8. Evaluate change, constraints, seams, drift, and false skips.
9. Repair the smallest safe scope or fail explicitly.
10. Emit complete receipts including all observation and orchestration costs.

## Retained patch, boundary, and cache mechanisms

Patches remain one possible execution selector. Boundary packets, object-aware
ownership, halo exchange, temporal cache, scene-cut invalidation, periodic
refresh, and repair promotion remain available after a plan selects work. The
architecture does not assume patch independence or that patches are the best
unit for every backend.

## Backend contract

Existing deterministic construction, pinned metadata, hooks, VAE timing,
output hashing, and compatibility checks remain. A future extension will add
explicit capability reporting for:

- patch selection;
- token selection;
- block selection;
- timestep selection;
- resolution selection;
- cache reuse and refresh.

Backend updates cannot silently alter M0 behavior or selector semantics.

## Module ownership

| Module | Responsibility |
|---|---|
| `hive_eyes` | purpose-specific input observation |
| `hive_fusion` | deterministic Sensory Fusion |
| `hive_visual_state` | coordinates, validators, state, and plan |
| `hive_probes` | model-free and future backend feasibility probes |
| `hive_backends` | pinned Wan/LTX adapters |
| `hive_hooks` | existing scheduler, attention, and latent capture |
| `hive_benchmarks` | M0 baselines, measurements, and comparisons |
| `hive-contracts` | future stabilized Rust contract types |
| `hive-evaluator` | quality, constraint, boundary, and drift evaluation |

## Safety and failure semantics

- invalid contracts fail before backend work;
- bounded eyes cannot write outside their scopes;
- fusion requires global context and one input identity;
- uncertainty cannot be converted to stable without evidence;
- unsupported selectors produce promotion or capability errors;
- selective claims require same-condition M0 comparison;
- failures emit partial evidence rather than silently degrading output.
