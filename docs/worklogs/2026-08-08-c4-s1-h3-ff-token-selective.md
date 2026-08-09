# C4-S1 H3 Feed-Forward Positionwise Low-Impact Token Selective Compute

Date: 2026-08-08
Status: bounded CONTROL evidence recorded on an isolated Draft PR branch
Decision: `C4_S1_INSTRUMENTATION_OVERHEAD_TOO_HIGH`
Constitution disposition: `REVISE_ONCE`

## Product question and authorization

C4-S1 asked one bounded product question: while MiniMax H3 global attention
remains Full Compute, can previous actual Full Compute evidence and current
pre-MLP observables identify video-token rows whose feed-forward contribution
is low enough to omit, reduce real MLP input work, and preserve Standard
quality?

The working product goal remains `Quality >= Standard Full Compute` and at
least 2.0x accepted-result end-to-end performance. C4-S1 was not required to
reach 2.0x alone, but any admitted component had to reduce actual backend work
without weakening quality or fallback. A small valid component could remain
composable; lack of isolated 2.0x was not a rejection reason.

The task began from clean `main` at
`f2d79ac5492a123818d691b875075ae191fa5b88`, after PR #75 was merged and Issue
#74 completed. Issue #76, branch `accel/c4-s1-h3-ff-token-selective`, and Draft
PR #77 isolate the work. The Product-First Constitution, Quality-First rule,
Model-Replaceable Core boundary, execution context, system map, C4-S0 cost
surface, C2 observation evidence, and C3-R1 quality evidence were read first.
No constitution conflict was found.

## Immutable C4-S0 handoff

C4-S0 remains immutable evidence with decision
`C4_S0_SUBBLOCK_COST_SURFACE_MAPPED`. It measured global attention at 70.2245%
and the full `feed_forward_positionwise` logical group at 19.4935% of sampler
CUDA event span. C4-S1 did not treat 19.4935% as attainable reduction: the
group includes `norm2`, modulation, and MLP, while this experiment could omit
only selected MLP rows. Global attention was unchanged and executed at Full
Compute for every block and step.

The frozen CONTROL comparison used the C4-S0 sampler wall span of 488.847320
seconds with a +/-5% admission band. A CONTROL outside that band had to stop
before policy selection or SELECTIVE Generation with decision
`C4_S1_INSTRUMENTATION_OVERHEAD_TOO_HIGH`.

## Source, segment, and token-identity admission

The installed H3 source digest was exactly
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`.
Source inspection verified a 5,376-wide positionwise Linear/SwiGLU/Linear MLP,
one MLP call per block, and the final contiguous target-video segment. The
fixed observed layout was `[1, 24, 37, 30, 54]`, producing 14,985 video rows,
439 non-video rows, and 15,424 total rows per block. Video row order is
`batch-latent_time-patch_h-patch_w (nthw)` and is admitted only while the full
layout signature, source digest, model digest, and workflow digest match.

Audio, text/conditioning, unknown, or ambiguously mapped rows are always Full
Compute. A segment, shape, order, device, dtype, digest, or runtime mismatch
fails open to the original full MLP.

## Frozen mechanism and causal contract

Commit `6c21862ae4edb5b0f1dd9929efc6fc280b0ed9a2` fixed
`FF_POSITIONWISE_LOW_IMPACT_TOKEN_SKIP_V1`, tests, instrumentation, and all
Gates before runtime. No algorithm, threshold, or schedule was changed after
the result.

Only `prev_h_norm`, `prev_ff_delta_ratio`, `prev_gate_norm`, and
`history_valid` from a previous *actual Full Compute* MLP result may be used
with current pre-MLP `curr_h_norm` and `curr_gate_norm`. Current MLP output and
current `ff_delta` are CONTROL oracle diagnostics only and cannot enter the
live selector. Steps 0, 1, 18, and 19 are anchors. A skipped row immediately
invalidates its history, so skip-to-skip chaining is prohibited until an
intervening actual Full Compute result refreshes it.

The fixed policies were:

| Policy | Previous FF delta ratio | h-norm change | gate-norm change |
|---|---:|---:|---:|
| P0 | <= 0.0025 | <= 0.005 | <= 0.005 |
| P1 | <= 0.005 | <= 0.010 | <= 0.010 |
| P2 | <= 0.010 | <= 0.020 | <= 0.020 |

At least 10% of a block's video rows had to be skipped before compact MLP
execution; otherwise the original full MLP was required. An admitted selective
block could call MLP at most once, on gathered active plus non-video rows, then
scatter only those contributions. Skipped rows would receive a zero FF update.
Attention was always Full Compute. `Observation != Compute Authority`; C2
state may veto toward Full Compute but cannot grant a skip.

## Architecture and memory boundary

Generic HIVEFRAME Core owns capability semantics, invalidation, fallback,
aggregate telemetry, and Quality-First decisions. The H3 adapter owns H3
segment layout, row indices, `DiTBlock`, `norm2`, modulation, `self.mlp`, CUDA
gather/scatter, and scalar lifecycle. No H3 class name, token layout, or block
count moved into Generic Core.

The existing Rust ABI was unchanged. Tensor-to-Rust transfer was zero bytes.
Observed persistent scalar metadata was 11,238,750 bytes, below the fixed
67,108,864-byte budget. Persistent full-tensor caches, host full-tensor copies,
and Rust-owned model tensors were all zero.

## Model-free validation

Fifteen focused tests passed before runtime. They covered exact policy values,
source and segment admission, token ordering, arbitrary-row MLP structure,
oracle/live separation, non-video and anchor Full Compute, invalid-history and
nonfinite fail-open, no consecutive skip, gather/scatter semantics, one MLP
call maximum, zero skipped contribution, active-row parity, the 10% efficiency
guard, wrapper restoration, serialization, and admission decisions.

Python compile, custom-node import, JSON parsing, `git diff --check`, and public
path/secret/binary checks passed. Unrelated full Python/Rust suites were not
repeated because the Product-First rules require focused validation and the
change was adapter-isolated.

## Preserved pre-runtime invocation failure

The first launch attempt, `ff-token-selective-6c21862-001`, used an incorrect
output-root environment-variable name. The runner stopped at configuration
before ComfyUI start, model load, workflow submission, GPU work, or Generation.
Its Generation and retry counts are both zero and its evidence is retained as
`results_eligible=false`. The invocation was corrected without changing code,
algorithm, threshold, or schedule; this was not a Generation retry.

## CONTROL Generation

Exactly one eligible fresh owned loopback ComfyUI Generation ran the fixed
profile: seed 101, 864x480, 124 frames, 24 FPS, 20 steps, `simple`,
`res_multistep`, denoise 1.0, native audio, H.264, and Sage disabled. Retry was
zero. The CONTROL executed 20 model forwards, 1,000 blocks, 1,000 MLP calls,
and 15,424,000 MLP input rows. Omitted video rows, non-video omissions,
attention omissions, mapping errors, wrapper failures, and actual work
reduction were all zero. The instrumentation integrity Gate passed.

The output decoded 124/124 frames at 864x480 and 24 FPS with one audio stream.
Black and corrupt frame counts were zero. OOM, retry, and fatal CUDA-error
counts were zero. The output was 263,028 bytes with SHA-256
`ae06ef4c1ab2223b8de86bbcd18ded1a938b24e5a0767d9c853b4292deca2f87`.

Sampler wall was 519.822272 seconds, submit-to-terminal was 619.667309
seconds, and runner entry through owned-runtime stop was 628.411549 seconds.
The sampler was 30.974952 seconds, or 6.336324%, slower than the immutable
488.847320-second C4-S0 reference. This exceeded the frozen 5% band, so the
CONTROL comparability Gate failed.

Deferred CUDA-event spans recorded 107.224084 seconds for the full FF group,
91.207117 seconds for the actual MLP, 5.670098 seconds for gather/mask, and
1.601064 seconds for scatter/residual across 1,000 calls. These are CUDA event
spans, not profiler kernel-duration sums. There was one final synchronization.
Profiler, CUPTI, Nsight, and kernel-by-kernel profiling were disabled, so
`gpu_kernel_seconds` is `null` and `not_collected`, not zero.

One-second sampled peaks were 11,589,910,528 bytes NVIDIA system VRAM,
12,461,735,860 bytes ComfyUI process-observed VRAM, and 47,107,780,608 bytes
process-tree RSS. They are sampled values, not exact allocator peaks. Exact
allocator peak remains `null`/`unavailable` because the external runner cannot
safely query the ComfyUI allocator.

## Shadow policy observations

The following values are CONTROL shadow observations, not execution authority:

| Policy | Predicted rows | Video-row reduction | All-row reduction | Steps | Blocks | Impact mean | p99 | max | >0.010 rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 | 8 | 0.0000534% | 0.0000519% | 5 | 1 | 0.002301 | 0.002710 | 0.002704 | 0% |
| P1 | 78 | 0.0005205% | 0.0005057% | 15 | 2 | 0.004236 | 0.007581 | 0.007571 | 0% |
| P2 | 1,000 | 0.0066733% | 0.0064834% | 16 | 9 | 0.008144 | 0.011011 | 0.016236 | 7.4% |

All nonfinite counts were zero. These observations are far below the frozen
10% all-row and 20% video-row opportunity floors, and P2 affected only nine
blocks while the minimum was ten. However, the official decision stops at the
earlier CONTROL comparability Gate. No policy was selected or promoted, and
the data was not used to authorize SELECTIVE execution.

## SELECTIVE, quality, and final decision

SELECTIVE Generation count is zero. Actual selective MLP calls, rows, omitted
rows, runtime, quality, and paired output metrics are `not_collected`, not
fabricated as zero. Automatic SSIM/MAE/motion/gradient Gates and visual review
were therefore not run. `visual_equivalence` remains `not_proven`.

The technical decision is `C4_S1_INSTRUMENTATION_OVERHEAD_TOO_HIGH` and the
constitution disposition is `REVISE_ONCE`. This does not prove that
feed-forward selective compute as a family is impossible. It proves that this
instrumented CONTROL path was not comparable enough to authorize the planned
SELECTIVE pair. Full Compute remains the only executed and safe default.

Actual backend work reduction, paired speedup evidence, speedup claim, quality
promotion, and product promotion are all zero. Global attention remains an
unchanged 70.2245% future cost surface. The cumulative 2.0x product objective
is neither achieved nor weakened by this bounded result.

A possible next action is a separately approved, one-time reduction of
CONTROL shadow-instrumentation overhead while preserving the exact selector,
thresholds, causal contract, and Quality Gate. C4-S2, threshold search,
attention optimization, another Generation, or product promotion did not
start automatically.

## Evidence, privacy, and diagram impact

The repository stores only this sanitized aggregate record and the knowledge
YAML. Prompt, media, full receipts, runtime logs, private paths, and resource
samples remain outside Git. External API calls, model downloads, installed
source changes, original-workflow changes, Rust ABI changes, training,
Ready transitions, merges, and Issue closes were zero.

Diagram impact: `updated`. The architecture boundary is unchanged, but the
current evidence progression changed from a planned FF candidate to an
implemented CONTROL-shadow path blocked by instrumentation comparability.
