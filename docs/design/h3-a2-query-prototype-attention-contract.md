# A2 GPU-Resident Regional Query Prototype Attention Contract

Status: predeclared experiment contract

## Product question

Can the existing Compound Eye observation and Rust region plan reduce actual
H3 attention-core query work by evaluating exact representative query rows in
stable interiors, while retaining global K/V, Full Compute safety, and Standard
quality?

The fixed mechanism is
`GPU_RESIDENT_REGIONAL_QUERY_PROTOTYPE_ATTENTION_V1`. This contract does not
alter the historical A1 candidate or reinterpret its evidence.

## Ownership boundary

HIVEFRAME Core and the existing A1 Rust ABI own semantic region decisions,
anchors, cooldown, invalidation, uncertainty, and Full Compute fallback. The H3
adapter alone translates those semantic regions to the installed packed token
layout. Rust receives metadata only; no tensor, token, row index, or H3 layout
crosses the boundary.

## Frozen execution mechanism

- A representative is an exact original query row after Q normalization and
  RoPE. Averaged, synthetic, learned, or clustered prototypes are forbidden.
- Stable-region interiors use a fixed spatial stride of `2 x 2`; there is no
  temporal compression and no parameter sweep.
- Active, uncertain, halo, non-video, anchor, refresh, invalid, and unavailable
  regions use Full Query.
- QKV projection, K/V rows, output projection, residual, MLP, VAE, and audio
  remain Full Compute.
- Only attention-core Q rows can be reduced. Omitted stable-interior outputs are
  reconstructed bilinearly within the same latent time and same semantic region
  before the original full-row output projection.
- All possible four-region semantic masks have immutable CPU mapping metadata;
  their index and weight tensors are materialized once per device/layout and
  reused across blocks. No per-block/per-token Rust call, CPU tensor creation,
  tensor host copy, or explicit hot-path CUDA synchronization is permitted.
- Any malformed mapping, stale plan, non-finite result, runtime error, or
  unsupported state fails open to the installed Full Compute block.

## CONTROL and SELECTIVE

CONTROL executes actual Full Attention. It also computes GPU-first
counterfactual reconstruction diagnostics from the already produced full
attention-core output; those diagnostics never alter the generated tensor.
SELECTIVE is allowed only after every frozen structural, overhead, opportunity,
and output-integrity gate passes. It evaluates exact representative Q plus every
required Full Query row against full/global K/V, reconstructs omitted rows, and
runs the original output projection over all rows.

## Frozen admission thresholds

Each block needs at least three valid block-region observations:

- mean cosine at least `0.980`;
- p05 cosine at least `0.950`;
- mean normalized residual L2 at most `0.120`;
- p95 normalized residual L2 at most `0.250`;
- mean energy ratio in `[0.85, 1.15]`;
- non-finite count `0`.

At most 20 blocks are selected by mean normalized L2 ascending, mean cosine
descending, p95 normalized L2 ascending, then block index. The opportunity gate
requires at least three admitted blocks, three affected non-anchor steps, three
stable plan events, positive compression, and at least 5% planned Q-row
reduction. CONTROL sampler time must remain within `+5%` of immutable C4-S0
`488.847320 s`. The combined Compound Eye and region-plan p95 must be at most
`3 ms`. A1 Rust boundary latency is recorded but is not an independent A2
rejection threshold.

## Quality and claims

Automatic paired-video gates remain mean/p05/min SSIM `0.95/0.90/0.85`, low
SSIM rate at most `0.02`, normalized MAE at most `0.03`, and motion, spatial
gradient, and temporal consistency ratios in `[0.90, 1.10]`. Human visual
review remains mandatory. Quality failure overrides any work or runtime gain.

The experiment may run one CONTROL and, conditionally, one SELECTIVE generation.
It makes no QKV-projection, K/V, output-projection, product speedup, Sage
composition, or 2x claim. Full Compute remains the product-safe fallback.
