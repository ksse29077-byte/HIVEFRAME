# A3-G1C - Preplan Direct Selective Reuse

Date: 2026-08-18
Source PR: [#91](https://github.com/ksse29077-byte/HIVEFRAME/pull/91)
Branch: `accel/a3-g1-h3-conditional-attention-reuse`
Base main: `f5d2bf8c2f80612909eef21c555d764a116f7062`
Starting branch HEAD: `43967b6992d6beb8c1c172bf4bbbeb4b8ca4c1c4`
Implementation commit: `934e2f0eea3b4484d8d894eb07866d381e3da621`
Decision: `A3_G1C_REUSE_NOT_ADMITTED`
Disposition: `FALLBACK_ONLY`

## Scope and start state

The approved existing A3-G1C branch was checked out without reset, rebase,
stash, force checkout, or cherry-pick. Local HEAD, remote branch HEAD, and the
expected PR #91 head all matched `43967b6992d6beb8c1c172bf4bbbeb4b8ca4c1c4`,
and the worktree was clean. PR #92 and PR #94 were not changed. No issue,
branch, or PR was created, and the W0, G0, G1B, C2, A1, A2, and A3 evidence was
not rerun.

This revision used the frozen W0 decision
`W0_PREPLAN_DIRECT_SELECTIVE_READY`. The product question was whether a Rust
metadata pre-plan could choose selective execution before real H3 Attention,
omit stable Q work, preserve quality, and reduce runtime on the RTX 3060 12GB.
Standard Full Compute remained the product default; this capability remained
experimental and disabled by default.

## Lean architecture implementation

The real H3 path now uses
`RUST_METADATA_PREPLAN_DIRECT_SELECTIVE_V1`, with only `FORCE_FULL` and
`SELECTIVE_CANDIDATE` directives. It retained the A1 subset-Q/global-KV
contract, A2 region mapping, Compound Eye semantic plan, A3 actual Full output
cache, `REGION_CHANNEL_MEAN_DELTA`, and all original downstream H3 work.

The following G1B execution-island elements were removed from this path:

- `GPUConditionalAttentionIsland` and all live CUDA Graph capture/replay;
- static Q, K, and V buffers and conditional output storage;
- the current same-block GPU representative guard and aggregation;
- graph pointer/signature compatibility checks and graph branch counters.

This removes 663,355,392 bytes of duplicate static QKV allocation. The normal
hot path is branch-exclusive: Full executes one exact Full Attention call and
no Partial call; Selective executes one Partial Attention call and no Full
call. Tensor transfer to Rust is zero. Cache lineage accepts only actual Full
Attention-core output of exact age one and prohibits selective/corrected cache
sources and consecutive approximation.

Full cache refresh is gathered and copied region by region into pinned host
storage. GPU region staging is bounded to 48,269,312 bytes, and full-size GPU
cache staging is zero. Correction uses 64-row chunks and enforces a temporary
upper bound of 32 MiB. The reconstructed core replaces the normal Full output
storage before the original output projection.

## Focused verification and implementation freeze

Eighteen focused tests passed with the owned ComfyUI Python environment. They
covered both directives, anchor and unsafe fallback, cache age and lineage,
consecutive-reuse rejection, region staging, branch-exclusive work accounting,
representative reuse, removal of the GPU guard/conditional graph/static QKV/
runtime capture, output shape and dtype, and the disabled product default.
Targeted diff validation also passed. The full suite and the G0 synthetic test
were intentionally not repeated.

Commit 1 was created with the required message and pushed before any model
generation. The runtime algorithm was not changed afterward.

## Runtime preflight

One environment-only preflight invocation stopped before model load because
the installed H3 source environment variables were absent. Its Generation
count was zero. The approved source paths were then restored; this was not a
Generation retry.

The actual CONTROL preflight admitted the immutable model and Attention
sources, exact backend, 12 fixed cache candidates, host-cache capacity, GPU
memory, and standard workflow. Source and workflow digests remained unchanged.
The fixed profile was 864x480, 124 frames, 24 FPS, 20 steps, canonical prompt,
seed 101, the existing scheduler and guidance, denoise 1.0, native audio, and
Sage disabled.

## CONTROL

Exactly one CONTROL Generation ran in
`CONTROL_A3_G1C_PREPLAN_DIRECT_REUSE`; retry count was zero. It completed with
the original exact Full Attention output for every block.

| Metric | CONTROL result |
|---|---:|
| Model forwards / block calls | 20 / 1,000 |
| Full / Partial Attention calls | 1,000 / 0 |
| Normal Partial+Full / exception Partial-then-Full | 0 / 0 |
| Theoretical / actual Attention Q rows | 15,424,000 / 15,424,000 |
| Reused omitted rows / actual Q reduction | 0 / 0.0% |
| Stable plan events / admitted blocks | 0 / 0 |
| Pre-plan false-safe | 0 |
| Host cache / D2H / H2D | 2,068,684,800 / 41,373,696,000 / 0 bytes |
| Full refresh / hit / miss / invalidation | 240 / 0 / 0 / 0 |
| Region staging / correction temporary peak | 48,269,312 / 0 bytes |
| Peak allocated / reserved | 3,145,345,911 / 3,523,215,360 bytes |
| OOM / native error / wrapper failure | 0 / 0 / 0 |
| Runner / sampler / submit-to-terminal | 609.906305 / 490.848230 / 596.058423 s |

The MP4 integrity Gate passed: H.264, 864x480, 124/124 frames, 24 FPS, native
audio, zero black frames, zero corrupt frames, and no fatal CUDA or OOM. Its
SHA-256 was
`659dd5363320c5d1af2c73c70e594d5e6b8279aab2f77c67c2c74ee59e579b2e`.

The Compound Eye/Rust observation pipeline produced 23 lagged stable
candidates, but every candidate-bearing step also contained an uncertain
region. The block-wide fail-closed rule therefore emitted no executable stable
plan event. No block obtained the required three valid counterfactual
observations, admitted blocks remained zero, affected non-anchor steps remained
zero, and planned Q reduction remained 0.0%. Callback p95 was 349,114,868 ns,
also above the frozen 3,000,000 ns limit.

The opportunity Gate failed only the admitted-block, affected-step,
callback-p95, planned-Q-reduction, and stable-plan-event checks. Cache capacity,
exact CONTROL output, fallback, output integrity, static-QKV/graph/guard
removal, bounded memory, zero tensor-to-Rust traffic, and zero double work all
passed. With no pre-plan candidate, false-safe evaluation had no observations;
the measured false-safe count remained zero.

## SELECTIVE, quality, and runtime

The failed CONTROL opportunity Gate prohibited SELECTIVE. SELECTIVE Generation
count is zero, retry count remains zero, and no automatic or human quality
comparison was collected. Missing Selective work, cache, quality, and runtime
metrics remain `null` rather than being represented as zero.

The immutable Standard comparator was 488.847320 seconds sampler and
589.913016 seconds submit-to-terminal. CONTROL was 0.4093% slower in sampler
and 1.0417% slower submit-to-terminal, equal to 0.995924x and 0.989690x Standard
speedup respectively. CONTROL overhead alone does not determine Selective
admission, but no Selective speedup can be claimed because the Gate correctly
prevented that run.

## Fallback and final decision

All 1,000 blocks followed exact Full Compute, producing a valid standard-size
output. Missing/late/malformed plans, anchors, uncertain regions, invalid cache
lineage, and native errors remain fail-open to the original exact Full path.
No normal double work or exception fallback occurred. This verifies the Full
fallback behavior exercised by CONTROL while making no claim about real work
omission, quality equivalence, or acceleration.

The exact final decision is `A3_G1C_REUSE_NOT_ADMITTED`, with disposition
`FALLBACK_ONLY`. The failure cause is insufficient safe pre-plan opportunity
under the frozen block-wide uncertain-region rule, plus callback p95 above the
Gate. SELECTIVE, threshold changes, a same-layer retry, Sage, residency,
prefetch, native CUDA work, and A3-G1C-R1 were not started.

Private receipts and full logs remain outside Git. The bounded evidence is
recorded in
[`knowledge/h3/a3_g1c_preplan_direct_selective_reuse.yaml`](../../knowledge/h3/a3_g1c_preplan_direct_selective_reuse.yaml)
without prompts, local source paths, credentials, binaries, or full logs.
