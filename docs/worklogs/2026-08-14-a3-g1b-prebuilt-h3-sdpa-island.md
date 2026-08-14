# A3-G1B Prebuilt H3 SDPA Conditional Island

Date: 2026-08-14

Issue: [#93](https://github.com/ksse29077-byte/HIVEFRAME/issues/93)

Branch: `accel/a3-g1b-prebuilt-sdpa-conditional-island`

Base main: `f5d2bf8c2f80612909eef21c555d764a116f7062`

Decision: `A3_G1B_STATIC_ISLAND_MEMORY_NOT_ADMITTED`

Disposition: `STOP`

## Product question

Can one sampler-prebuilt, shared, static PyTorch SDPA conditional island omit
real H3 Attention work and reduce runtime without reducing quality?

The task stopped at the mandatory VRAM pre-admission Gate. No static island
allocation, model load, Phase A CUDA execution, CONTROL, SELECTIVE, or retry
was performed.

## Repository start and historical PRs

The work started from clean `main`. Local `main`, `origin/main`, and HEAD all
matched the required base. PR #91 and PR #92 were both Draft/Open and remained
unchanged: no Ready transition, merge, close, commit, or force push.

PR #91 was used only as a source-readable historical evidence boundary. The
following repository-owned concepts were inspected: Rust `FORCE_FULL` /
`GPU_CHECK`, GPU guard ownership, A3 cache lineage,
`REGION_CHANNEL_MEAN_DELTA`, the H3 block wrapper, candidate selection, work
accounting, cache traffic, and receipt shape. No PR #91 commit was
cherry-picked and no code was ported because pre-admission failed before the
implementation Gate.

The rejected live-capture design includes
`GPUConditionalAttentionIsland.capture()`, `begin_capture_to_if_node`, live
Q/K/V capture, and any sampler hot-path recapture. None was reused.

## Installed runtime and API Gate

| Item | Observed |
|---|---|
| Python | 3.13.12 |
| PyTorch | 2.12.1+cu130 |
| PyTorch CUDA build | 13.0 |
| GPU | NVIDIA GeForce RTX 3060 |
| Physical VRAM | 12,884,377,600 bytes |
| `torch.cond` | available |
| `torch.compile` | available |
| `cudagraphs` backend | available |
| Installed exact backend | `attention_pytorch` |
| Sage | disabled |
| xFormers | disabled |

The installed exact path is ComfyUI `attention_pytorch`, which calls
`comfy.ops.scaled_dot_product_attention` with no mask, dropout 0.0, and
`is_causal=False`. Inductor was not used.

## Exact H3 Attention signature

The installed H3 source constructs 50 `DiTBlock` instances from one
`num_attention_heads=56`, `attention_head_dim=128` configuration. The
canonical prior real H3 CONTROL recorded 15,424,000 theoretical Q rows over
20 model forwards and 50 blocks, fixing 15,424 rows per block call.

The resulting single fixed signature is:

| Tensor | Shape | Dtype | Device |
|---|---|---|---|
| Q | `[1, 56, 15424, 128]` | BF16 | CUDA |
| K | `[1, 56, 15424, 128]` | BF16 | CUDA |
| V | `[1, 56, 15424, 128]` | BF16 | CUDA |
| Core output | `[1, 15424, 7168]` | BF16 | CUDA |

All 50 blocks use the same heads, head dimension, packed sequence, backend,
dtype, device, mask, dropout, causal flag, and output reshape contract.
Therefore the multi-signature rejection did not apply.

## Static island byte calculation

Each Q, K, V, safe-core, or output tensor contains 110,559,232 BF16 elements
and requires 221,118,464 bytes.

| Persistent tensor | Bytes |
|---|---:|
| `static_q` | 221,118,464 |
| `static_k` | 221,118,464 |
| `static_v` | 221,118,464 |
| `static_safe_core` | 221,118,464 |
| `static_predicate` | 1 |
| Minimum without a distinct static output | 884,473,857 |
| `static_output`, if required | 221,118,464 |
| Total with static output | 1,105,592,321 |

Compiled graph bookkeeping and SDPA workspace were not estimated as zero.
They were left uncollected because compile/capture was prohibited after the
minimum tensor set already failed the Gate. Consequently 884,473,857 bytes is
a conservative lower bound, not a worst-case estimate.

## VRAM pre-admission

The prior canonical Standard H3 run measured a system-sampled peak of
12,460,611,508 bytes on the same 12,884,377,600-byte GPU. Peak headroom was
therefore 423,766,092 bytes.

The persistent minimum, even with no separate output tensor, exceeds that
headroom by 460,707,765 bytes. With the output tensor it exceeds headroom by
681,826,229 bytes. Both comparisons exclude graph bookkeeping and SDPA
workspace, so neither can be repaired by a more favorable unmeasured runtime
overhead assumption.

An idle preflight reported 11,799,625,728 bytes free through PyTorch before a
model load. That idle value is not an admission result: the island is
persistent during sampling and must coexist with the measured Standard peak.
Loading the model or allocating the island could not make the peak-safety
inequality pass. The task therefore did not force a model load or allocation.

The exact Gate result is `vram_admitted=false`, with decision
`A3_G1B_STATIC_ISLAND_MEMORY_NOT_ADMITTED`. Buffer reduction, quantization,
CPU offload changes, block residency, alternate capture, child graphs, custom
SDPA, and custom kernels were not started.

## Prebuild and Phase A

`torch.cond`, `torch.compile`, and the `cudagraphs` backend were present, but
the conditional callable was not compiled. Compile, warmup, capture,
instantiate, and replay counts are all zero. Their timings are not collected.

Phase A SAFE, UNSAFE, exact parity, and predicate toggle were not run because
the VRAM Gate precedes Phase A. No reduced-shape substitute was used. Runtime
compile and recapture counts remain zero.

## CONTROL, SELECTIVE, quality, and runtime

| Item | Result |
|---|---|
| CONTROL Generation | 0 |
| SELECTIVE Generation | 0 |
| Retry | 0 |
| Native Full parity | not collected |
| Admitted blocks / false-safe | not collected |
| Planned / actual Q reduction | not collected |
| Exact / reuse branch executions | 0 / 0 |
| Static GPU copy traffic | 0 bytes |
| Cache H2D / D2H | 0 / 0 bytes |
| Guard D2H / host reads / hot-path sync | 0 / 0 / 0 |
| Automatic quality | not collected; pass false |
| Human quality | not collected |
| Sampler / submit / runner speedup | not collected |

SSIM, nMAE, motion, gradient, and temporal metrics were not zero-filled. The
fixed quality thresholds were unchanged. No speedup, quality, work omission,
or product promotion is claimed.

## Fallback and publication

Standard Full Compute remains unchanged, independently callable, and the
product default. Since no experimental runtime path executed, the fallback
surface was preserved without being exercised.

The Phase A implementation commit was intentionally not created because the
contract permits it only after Phase A passes. This evidence is carried by the
single allowed documentation/Knowledge commit. A Draft PR is created after
that commit is pushed. Ready, Merge, Issue close, G1B-R1, and automatic next
experiment remain zero.

