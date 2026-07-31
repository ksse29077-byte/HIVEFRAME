# Compound-Eye Architecture v1

Status: executable architecture RFC

## Data flow

```text
Input frame sequence + scene/edit intent
                      |
             EyeContract compiler
                      |
       +--------------+--------------+
       |              |              |
 global low-res   regional eyes   motion eye
       |              |              |
       +------ overlap/boundary eye --+
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
       generation + evaluation + repair
                      |
              receipts and artifacts
```

No reference eye owns model weights. No eye is required to materialize the
whole source at full resolution. Logical eyes may execute sequentially in one
process; concurrency is not part of v0.

## Contracts

### EyeContract

Declares:

- stable eye ID and role;
- one or more spatial/temporal receptive windows;
- sampling scale and temporal stride;
- read-only or bounded write policy;
- local-to-global coordinate transform;
- expected observation outputs.

The contract is backend-neutral. A regional eye's write windows must be
contained by its receptive field. Global, boundary, and motion eyes are
read-only in v0.

### EyeObservation

Contains only derived evidence:

- eye and input identity;
- exact receptive field and write scope;
- small purpose-specific features;
- dirty, stable, or uncertain region reports;
- confidence;
- source algorithm and input digest;
- explicit unsupported metrics.

An observation is not a latent patch, full-frame feature copy, or permission
to mutate output.

### SharedVisualState

Sensory Fusion produces:

- one global context reference;
- normalized canvas identity;
- fused regions with state and confidence;
- every contributing observation and reported state;
- input and observation hashes;
- an explicit fusion policy.

The v0 policy is conservative: agreement can yield `stable` or `dirty`;
missing, conflicting, or ownership-boundary evidence yields `uncertain`.

### ComputePlan

Each unit references one fused region and proposes:

- `generate` for dirty regions;
- `reuse_cache` for stable regions;
- `reconcile` for uncertain regions;
- backend-neutral selectors for patch, token, block, timestep, resolution, and
  cache.

Selectors are candidates. The backend capability adapter must accept,
translate, promote, or reject them explicitly. `reuse_cache` is not proof that
compute was saved.

## Reference implementation

The model-free implementation is split by responsibility:

| Package | Responsibility |
|---|---|
| `hive_eyes` | global, 2×2 regional, boundary, and motion observations |
| `hive_fusion` | deterministic conservative Sensory Fusion |
| `hive_visual_state` | coordinates, validators, shared state, compute plan |
| `hive_probes` | synthetic sequence and artifact-producing reference probe |

It uses a `[frames, height, width, channels]` NumPy tensor and never imports
Torch, Wan, CUDA, or model weights.

## Coordinate system

All v0 interchange boxes are integer `pixel_xywh` in the source canvas.
Normalized boxes are derived and checked against pixel coordinates.
`local_to_global` uses identity scale and the receptive-window origin as its
offset. Later latent/token coordinate systems require explicit transforms;
implicit rounding is forbidden.

## Backend integration boundary

The existing `hive_backends` package is unchanged. A later M1 experiment will
add a capability query before any Wan hook changes:

```text
supports_patch_selector
supports_token_selector
supports_block_selector
supports_timestep_selector
supports_resolution_selector
supports_cache_selector
```

Unsupported selectors cause promotion or a capability error. They are not
silently treated as successful sparse execution.

## Relationship to the legacy architecture

The preserved patch-centric design remains at
[`legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md`](legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md).
Its boundary, affected-closure, temporal-cache, evaluation, repair, and receipt
requirements remain relevant. Compound-eye state moves detection and planning
earlier; it does not delete those safety layers.

## Failure semantics

- Invalid contracts fail before backend execution.
- An eye cannot report a writable region outside its policy.
- Missing global context blocks fusion.
- Cross-input observations cannot be fused.
- Conflicting evidence becomes `uncertain`.
- Unsupported metrics and selectors are explicit.
- A model-free plan cannot claim quality, speedup, GPU time, or backend
  feasibility.
- Real selective runs must preserve M0 receipt timing meanings.
