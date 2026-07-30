# Architecture

## System view

```text
Prompt / edit request / references
                  │
                  ▼
              Director
                  │ relationships and intent
                  ▼
            SceneContract
                  │ schema validation
                  ▼
       Deterministic Constraint Compiler
                  │ geometry, masks, depth, permissions
                  ▼
 Dependency Graph + Affected Closure + Patch Scheduler
          │             │                │
          ├─────────────┼────────────────┤
          ▼             ▼                ▼
     Logical worker  Logical worker  Logical worker
          │        shared model weights       │
          └────────── Boundary Bus ────────────┘
                         │
                  Temporal Cache
                         │
         Evaluator + Repair Controller
                         │
               Receipt + artifacts
```

## Control plane and data plane

### Control plane

The Rust control plane owns structures that should remain deterministic, portable, and model-independent:

- `SceneContract`;
- constraint compiler;
- dependency graph and affected closure;
- patch scheduler;
- boundary and repair policy;
- temporal cache index;
- receipts;
- model-license and data ledgers;
- command-line interface and future product orchestration.

### Model data plane

The first model worker remains Python/PyTorch because the backend ecosystem, Diffusers integration, Wan/LTX reference code, attention/scheduler hooks, and adapter training are PyTorch-centered. Starting Rust-only would make integration a larger bottleneck than the research.

Initial process layout:

```text
One Python process
├─ backend
├─ scheduler/attention hooks
├─ patch experiment logic
└─ receipt adapter
```

Intermediate layout after structure is proven:

```text
Rust control plane
        │ shared memory / FFI
Python model worker
        │
CUDA device
```

Multi-GPU work must measure NCCL bytes. Replicated data parallelism is only a comparison baseline; the target is latent/token partitioning with boundary packets and previous-step features.

## Core data contracts

### SceneContract

The canonical scene state must be backend-neutral and schema-versioned. It includes:

- canvas, frame range, and coordinate system;
- objects, identities, landmarks, masks, boxes, and depth order;
- motion and camera instructions;
- symmetry, count, distance, and geometry constraints;
- patch ownership and write permissions;
- preserved regions and edit targets;
- shared seed and conditioning references;
- expected evaluator checks.

An initial schema is provided in [`schemas/scene_contract.schema.json`](schemas/scene_contract.schema.json).

### BoundaryPacket

Version 0 should carry only bounded information:

- source and destination patch IDs;
- timestep and latent-space edge;
- halo strip or a compact feature reference;
- position metadata;
- semantic ownership/conflict hints;
- uncertainty and checksum;
- round number.

Two neighbor reconciliation rounds are the initial maximum. Remaining disagreement escalates centrally.

### RunReceipt

Every baseline and experiment receipt must identify:

- source revision and dirty state;
- backend, checkpoint digest, license record, runtime versions;
- prompt/suite/config digests and random seed;
- width, height, frames, fps, steps, scheduler, precision;
- wall, GPU, denoising-step, VAE, communication, scheduler, and repair time;
- peak VRAM, host RAM, utilization, transferred bytes, cache memory;
- patch activity, skip, closure, cache, and false-skip measures;
- quality and constraint results;
- output hashes, environment fingerprint, warnings, escalation, and failure state.

## Execution sequence

1. Validate model and data admission.
2. Compile input intent into a `SceneContract`.
3. Build dependency graph and numeric constraints.
4. Partition into object-aware adaptive patches.
5. Compute affected closure and write permissions.
6. Schedule logical workers against shared weights.
7. Exchange boundary context for at most the configured rounds.
8. Evaluate uncertainty, constraints, seams, and drift.
9. Accept, refresh, or expand repair strip → patch → object → frame.
10. Emit receipt and artifacts even on failure.

## Patching

Initial settings use a 2×2 grid, growing adaptively to at most 8×8 with object-aligned subdivision and a latent halo of 16. Minimum work size and merging protect against scheduling overhead. Complex regions subdivide; stable regions may merge.

Patch execution is not assumed independent. Head- and layer-level sparsity must be measured. If global attention dominates, experiments may use previous-step context, mixed resolution, a different backend, or semantic token groups instead of spatial patches.

## Temporal cache

Freeze decisions combine:

- warped previous latent/state;
- latent delta;
- semantic delta;
- motion and object dependencies;
- uncertainty;
- periodic refresh;
- object-level anchors;
- scene-cut invalidation.

Boundary-only dirty states permit halo refresh while interiors stay frozen. False skips and static-region drift are first-class metrics.

## GPU optimization order

1. Existing PyTorch operations.
2. `torch.compile` and CUDA Graphs.
3. Triton kernels for measured hotspots.
4. CUDA C++ only when justified.
5. Mojo only after a clear bottleneck is measured.

## Backend contract

Each backend adapter must expose:

- deterministic pipeline construction;
- pinned model/checkpoint metadata;
- scheduler-step callbacks;
- latent snapshots;
- VAE encode/decode timing;
- attention or feature hooks when supported;
- common conditioning inputs;
- output hashing;
- a compatibility test matrix.

Backend updates must not silently change behavior. Pinned versions and adapter contract tests guard hooks.

## Module ownership

| Module | Initial language | Responsibility |
|---|---|---|
| `hive-contracts` | Rust | versioned scene, boundary, receipt structures |
| `hive-director` | Rust | relationship-level scene planning |
| `hive-constraint-compiler` | Rust | numeric geometry and permissions |
| `hive-patch-scheduler` | Rust | graph, closure, patch queue |
| `hive-boundary-bus` | Rust | neighbor packets and escalation |
| `hive-temporal-cache` | Rust | cache index and invalidation |
| `hive-evaluator` | Rust + Python | metric contracts and model-backed evaluators |
| `hive-cli` | Rust | stable command surface |
| `hive_backends` | Python | Wan/LTX adapters |
| `hive_hooks` | Python | scheduler, attention, latent capture |
| `hive_training` | Python | gated LoRA/IC-LoRA experiments |
| `hive_benchmarks` | Python | suites, measurements, comparisons |

## Safety and failure semantics

- Invalid contracts fail before GPU work.
- Unsupported backend hooks are explicit capability errors.
- Boundary conflicts exceeding the round budget escalate.
- Cache uncertainty triggers refresh.
- Local repair cannot write outside compiled permissions.
- Receipts record partial results, promotion scope, and failure causes.
