# Patch-Centric Architecture v0 — Preserved Legacy Design

Status: preserved, not deleted

Snapshot tag: `pre-compound-eye-v1`

Snapshot commit: `2bc35ff4a0d442dc5fa43924d719de942960762b`

This document preserves the output-side patch-centric HIVEFRAME design that
preceded the compound-eye RFC. It remains a valid comparison architecture and
a source of boundary, repair, cache, scheduler, and receipt requirements. The
compound-eye RFC does not claim this design was wrong; it asks whether earlier
selective observation can produce a better compute plan.

## Legacy system view

```text
Prompt / edit request / references
                  |
               Director
                  |
             SceneContract
                  |
      Deterministic Constraint Compiler
                  |
 Dependency Graph + Affected Closure + Patch Scheduler
          |              |              |
   Logical worker  Logical worker  Logical worker
          \_____ shared model weights _____/
                         |
                    Boundary Bus
                         |
                  Temporal Cache
                         |
          Evaluator + Repair Controller
                         |
                 Receipt + artifacts
```

## Control plane

The Rust control plane owns deterministic, model-independent structures:

- `SceneContract`;
- constraint compilation;
- dependency graph and affected closure;
- patch scheduler;
- boundary and repair policy;
- temporal-cache index;
- receipts;
- model-license and data ledgers;
- CLI and product orchestration.

## Model data plane

The model worker remains Python/PyTorch because Wan, LTX, Diffusers, scheduler
hooks, attention hooks, and adapter training are PyTorch-centered. The initial
layout uses one Python process for backend execution, hooks, patch experiments,
and receipt adaptation. A later layout may use a Rust control plane over shared
memory or FFI with a Python CUDA worker.

## Legacy execution sequence

1. Validate model and data admission.
2. Compile intent into a `SceneContract`.
3. Build dependencies and numeric constraints.
4. Partition the output domain into object-aware adaptive patches.
5. Compute affected closure and write permissions.
6. Schedule logical workers against shared weights.
7. Exchange boundary context for a bounded number of rounds.
8. Evaluate uncertainty, constraints, seams, and drift.
9. Accept, refresh, or expand repair from strip to patch to object to frame.
10. Emit a receipt and artifacts even on failure.

## Patching

The initial proposal uses a 2×2 grid, growing adaptively to at most 8×8 with
object-aligned subdivision and a latent halo. Minimum work size and merging
protect against scheduler overhead. Complex regions subdivide and stable
regions may merge.

Patch execution was never assumed to be independent. Head- and layer-level
sparsity must be measured. If global attention dominates, experiments may use
previous-step context, mixed resolution, another backend, or semantic token
groups instead of spatial patches.

## BoundaryPacket v0

A bounded neighbor message carries:

- source and destination patch IDs;
- timestep and latent-space edge;
- halo strip or compact feature reference;
- position metadata;
- semantic ownership and conflict hints;
- uncertainty and checksum;
- reconciliation round.

Two neighbor rounds are the initial maximum. Unresolved disagreement escalates
centrally.

## Temporal cache

Freeze decisions combine warped previous state, latent delta, semantic delta,
motion and object dependencies, uncertainty, periodic refresh, object anchors,
and scene-cut invalidation. Boundary-only dirty states permit halo refresh
while interiors remain frozen. False skips and static-region drift remain
first-class metrics.

## Safety properties retained by the new RFC

- invalid contracts fail before GPU work;
- unsupported backend hooks are explicit;
- uncertain or conflicting work escalates;
- local repair cannot write outside compiled permissions;
- shared logical workers do not imply replicated model weights;
- partial failures still produce receipts;
- end-to-end economics include orchestration, communication, evaluation, and
  repair;
- the existing M0 baseline remains the cost truth against which any selective
  runtime is compared.

## Legacy module map

| Module | Responsibility |
|---|---|
| `hive-contracts` | scene, boundary, and receipt structures |
| `hive-director` | relationship-level scene planning |
| `hive-constraint-compiler` | numeric geometry and permissions |
| `hive-patch-scheduler` | graph, affected closure, patch queue |
| `hive-boundary-bus` | neighbor packets and escalation |
| `hive-temporal-cache` | cache index and invalidation |
| `hive-evaluator` | metric contracts and evaluators |
| `hive-cli` | stable command surface |
| `hive_backends` | Wan/LTX adapters |
| `hive_hooks` | scheduler, attention, and latent capture |
| `hive_benchmarks` | baselines, measurements, and comparisons |

The source-of-truth snapshot for all details not repeated here is the tagged
repository state `pre-compound-eye-v1`.
