# M1-B0 Model-free Locality Opportunity Protocol

Status: measured on the experiment branch; Draft PR review pending

Protocol revision: `m1-b0-v1`

Decision vocabulary: `M1_B0_LOCALITY_SURFACE_MEASURED`,
`M1_B0_REFINEMENT_REQUIRED`, or `M1_B0_BLOCKED`

## Question and claim boundary

M1-B0 asks whether adjacent frames in the twelve approved M1-A2 analysis
derivatives contain enough spatial and temporal locality to justify a later
backend-capability experiment. It measures pixels, tiles, temporal runs, a
bounded global-translation correction, detector cost, and CPU scaling.

It does **not** create safe-skip truth. Guided Oracle coordinates are excluded
from measurement truth. It does not execute a model, CUDA, a GPU, a backend,
selective compute, or a VRAM benchmark. Therefore the implication remains:

```text
observed pixel locality
  != safe skip
  != backend work reduction
  != VRAM reduction
  != product speedup
```

M1-B0 is input evidence for the separately approved M1-B1 Backend Capability
Admission. It cannot automatically admit a selector or start M1-B1.

## Fixed inputs

The inputs are the twelve immutable, rights-reviewed M1-A2 FFV1 analysis
derivatives, C01 through C12. Each is 832x480 at 16 FPS. The runner verifies
the declared byte length, SHA-256, codec, dimensions, frame rate, and decoded
frame count before generating analysis buffers. Original videos and Guided
Oracle exports are not measurement inputs.

The analysis buffers and full per-implementation results remain in the
approved local artifact store. Public evidence uses `approved-asset:` IDs,
relative artifact names, hashes, and byte counts only.

## Predeclared detector surface

Gray8 is primary and RGB24 is the secondary disagreement check.

```text
gray changed      := abs(Y[t] - Y[t-1]) > threshold
RGB changed       := max(abs(RGB[t] - RGB[t-1])) > threshold
gray thresholds   := 0, 1, 2, 4, 8, 16
RGB thresholds    := 0, 2, 4, 8, 16
tile sizes        := 8, 16, 32, 64
activation rules  := any, 1%, 5%, 10%
halo radii        := 0, 1, 2 tiles
```

Threshold comparison is strict. Partial right/bottom tiles are retained
without crop or padding, and their actual pixel count is the activation
denominator. Every declared threshold, tile, activation, halo, raw, and
translation-compensated combination is reported. No best-looking combination
is promoted after seeing the results.

For every configuration the receipt reports active/frozen candidate ratios,
partial-edge counts, closure tiles, halo inflation, >=75%, >=90%, and full
pressure. Full pressure is a `global_invalidation_candidate`, not an Oracle
label or backend decision.

## Global translation v1

The deterministic correction samples each gray frame to 104x60, searches
integer `dx,dy` in `[-4,+4]`, and minimizes overlap mean absolute difference
using exact rational comparison. Ties use, in order: Manhattan distance,
`abs(dy)`, `abs(dx)`, ascending `dy`, then ascending `dx`. The chosen shift is
scaled by eight for the full-resolution comparison.

Newly exposed border pixels are always active/uncertain. Raw and compensated
surfaces are both retained. The correction does not claim to solve rotation,
zoom, perspective, or optical flow.

## Temporal persistence

Each tile configuration records active and frozen-candidate run counts,
nearest-rank p50/p95 run length, both transition directions, one-frame-only
activity, and persistent activity. These values are research inputs for a
future cache-lifetime hypothesis; they are not cache admission or skip
authority.

## Reference and native implementations

`numpy_vectorized_reference` is the correctness reference and contains no
per-pixel Python performance loop. `hive-retina-runtime` is the deterministic
Rust native implementation. Before costs are measured, all C01-C12 gray8 and
RGB24 pairs must agree on integer counts, tile/halo/run semantics, translation
records, and aggregate digest. Floating ratios use an absolute tolerance of
`1e-12`. A mismatch blocks the benchmark.

## Cost profiles

- `decode_only`: FFV1-to-gray8 decode, three measured repeats; no comparison.
- `resident_warm`: predecoded gray8 bytes are read once, then one warm-up and
  five in-process Rust analyses; input read and analysis are separate.
- `streaming`: one warm-up and three measured FFmpeg-pipe-to-Rust runs; the
  external span includes decode, pipe transfer, comparison, and aggregation.

No cold-disk result is claimed because OS file caches were not forcibly
evicted. Worker scaling uses CPU processes launched by a thread pool, not GPU
streams. Required workers are 1, 2, 3, 4, and 6; 8 and 12 are explicitly
oversubscription diagnostics.

Scheduling overhead, process-tree peak RSS, and CPU utilization are null with
an explanation because validated samplers were not active. Values not
measured are never replaced with zero.

## Evidence and Gate

Public aggregate evidence is in `reports/m1_b0/`; large decoded buffers and
full native/reference receipts are represented by a canonical local file
inventory digest. The public JSON Schema is
`schemas/m1_b0_locality_opportunity.schema.json`.

The measured Gate is `M1_B0_LOCALITY_SURFACE_MEASURED`: all twelve input
hashes passed, every fixed surface was measured, 24/24 NumPy/Rust comparisons
passed, cost profiles and worker sweep completed, and all forbidden execution
counters stayed zero. This Gate means only that the locality opportunity
surface is available for review.

## Next bounded step

M1-B1 must separately establish a BackendCapabilityMatrix: selectable compute
unit, selector granularity, dependency closure, temporal state ownership,
boundary invalidation, fallback, deterministic parity, and measurable backend
work. Until that admission exists, every locality candidate falls back to full
compute.
