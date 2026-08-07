# C4-S0 H3 Sub-Block Cost & Coupling Surface

Date: 2026-08-07
Status: verified once on the isolated Draft PR branch
Decision: `C4_S0_SUBBLOCK_COST_SURFACE_MAPPED`

## Purpose and authorization

C4-S0 asked one bounded product question: which source-backed execution groups
inside MiniMax H3 `DiTBlock` dominate the fixed Full Compute sampler, and which
one is the next plausible quality-preserving compute lever when measured cost,
coupling, controllability, observation compatibility, adapter isolation, and
Full Compute fallback are considered together?

This was measurement and ranking, not selective execution. The long-term
working product target remains `Quality >= Standard Full Compute` and accepted
result end-to-end performance of at least 2.0x. A component does not need to
deliver 2.0x in isolation to remain useful, but it must be structurally capable
of contributing real backend-work reduction without sacrificing the quality
or fallback contract.

The task began from clean `main` at
`e78416691f115710a00e4735c0dc981a8bcfee42`, after PR #73 was merged and Issue
#72 completed. Issue #74, branch `accel/c4-s0-h3-subblock-cost-coupling`, and
Draft PR #75 isolate the work. The Product-First Constitution, Quality-First
rules, Model-Replaceable Core boundary, execution context, and system map were
read first. No constitution conflict was found.

## C3-R4 handoff and evidence reuse

C3-R4 remains immutable evidence with decision
`C3_R4_DIRECTIONAL_SIMILARITY_TOO_LOW` and family disposition
`RESIDUAL_PREDICTOR_FAMILY_FALLBACK_ONLY`. C4-S0 did not modify or rerun C2,
C3-R1, C3-R2, C3-R3, C3-R4, Wan M0, or Sage. Full Compute remained the default
and safe fallback throughout. Product speedup claim remained zero.

The same-condition Full Compute sampler spans reused for the predeclared
instrumentation comparison were 486.603692, 488.459651, 488.710265, and
488.865380 seconds from immutable C0, C3-R2, C3-R3, and C3-R4 evidence. Their
median, 488.584958 seconds, was frozen before runtime with a +/-5% admission
band.

## Source admission and exact groups

The installed H3 source digest was exactly
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`.
`DiTBlock`, its 50-block model default, direct submodules, helper calls, and
forward order matched the predeclared contract. The installed source and
original workflow were not edited.

The source-order groups were frozen before Generation:

| Group | Source boundary | Coupling |
|---|---|---|
| `modulation_parameter_projection` | `self.adaln_proj(t_emb)` creates shift/scale/gate values | `REDUCTION_OR_BROADCAST` |
| `attention_norm_modulation` | `norm1` plus `_mod_scale_shift` | `POSITIONWISE_OR_LOCAL` |
| `attention_global_mixing` | H3 attention including QKV, RoPE, optimized attention, and output projection | `GLOBAL_MIXING` |
| `attention_residual_update` | attention-side `_mod_gate` | `POSITIONWISE_OR_LOCAL` |
| `feed_forward_positionwise` | `norm2`, modulation, and `mlp` | `POSITIONWISE_OR_LOCAL` |
| `feed_forward_residual_update` | MLP-side `_mod_gate` | `POSITIONWISE_OR_LOCAL` |

Classification is structural evidence, not skip authority. The first group has
unknown subset-execution and output-shape-preservation status. Global attention
requires all tokens and global context. The four positionwise groups are
source-structurally local, output-shape preserving, wrapper-reachable, adapter
isolatable, and capable of falling back to the original operation. These facts
do not establish a safe partial-execution implementation.

## Instrumentation contract and model-free validation

Commit `d1ffa3e8b6f975e32ef2be4509f0e41f1129237d` fixed the source parser,
six-group map, operation-identical H3 adapter wrapper, deferred CUDA-event
collector, event bounds, buckets, report format, comparison Gate, and ranking
rules before runtime. No algorithm change was made after that commit.

Each group and enclosing block received an event pair on the active CUDA
stream. Events were resolved after sampler completion with exactly one CUDA
synchronization. The upper bound and observed counts were 7,001 event pairs
and 14,002 event objects: six groups plus one parent block across 1,000 block
calls, plus one sampler pair. PyTorch profiler, CUPTI, Nsight, and kernel-level
profiling were disabled. Therefore all GPU measurements below are CUDA event
spans, not GPU kernel-duration sums; `gpu_kernel_seconds` is `null` with a
`not_collected` reason.

The groups are sequential children of the parent `DiTBlock` span. Child spans
are compared with the parent but are not added to it. The measured child sum
was 446,055.006558 ms versus a 446,077.034332 ms parent, leaving 22.027774 ms
unattributed inside the parent without inventing a balancing value.

Focused model-free validation passed 11 tests. It covered result and order
parity, source parsing, event bounds, one synchronization, nested accounting,
exception restoration, wrapper removal, unsupported-event null semantics,
serialization, and the absence of skip/reuse directives. Python compile, JSON
parse, changed-package import, and `git diff --check` passed. The first manual
custom-node import omitted the ComfyUI package root and failed before model or
GPU work; the corrected import-only invocation passed. This was an invocation
preflight issue and did not consume a Generation or change code.

## Single fixed Full Compute Generation

Exactly one fresh owned loopback ComfyUI process ran the fixed Local H3 profile:
seed 101, 864x480, 124 frames, 24 FPS, 20 steps, `simple`,
`res_multistep`, denoise 1.0, native audio, H.264, and Sage disabled. Retry,
second Generation, and SELECTIVE Generation counts were zero.

Runtime parity passed: 20 model forwards, 1,000 `DiTBlock` calls, all six groups
called 1,000 times, mapping errors zero, wrapper failures zero, and skip, reuse,
prediction, regional execution, token omission, and attention omission all
zero. The H.264 output decoded 124/124 frames at 864x480 and 24 FPS with one
audio stream. Corrupt and black-output indicators were zero; OOM and CUDA error
counts were zero. The output SHA-256 is
`2786d894e8027b75f8d2e45f1aba365b41c9a338a916838aadd0159e52789192`.

The sampler wall span was 488.847320 seconds, submit-to-terminal was
589.913016 seconds, and runner entry through owned-runtime stop was 599.260183
seconds. The sampler differed from the frozen 488.584958-second reference by
0.053698%, well inside +/-5%; instrumentation comparability passed. The owned
runtime was explicitly terminated after the successful terminal result, so
its child-process stop return code is not a Generation failure.

Sampled resource telemetry recorded 11,589,910,528 bytes as the peak NVIDIA
system-sampled VRAM value, 12,464,555,956 bytes as the peak ComfyUI process
sample, and 46,921,318,400 bytes as peak process-tree RSS. These are one-second
samples, not allocator-exact peaks. The external runner cannot safely inspect
the ComfyUI process's PyTorch allocator peak, so that metric remains `null`
and `unavailable` rather than zero.

## Cost surface

| Logical group | Total ms | p50 ms | p95 ms | DiTBlock share | Sampler share | Coupling | Ideal ceiling |
|---|---:|---:|---:|---:|---:|---|---:|
| modulation projection | 108.431 | 0.089088 | 0.113664 | 0.0243% | 0.0222% | reduction/broadcast | 0.0222% |
| attention norm/modulation | 4,255.818 | 4.274176 | 4.287488 | 0.9541% | 0.8707% | positionwise/local | 0.8707% |
| global attention mixing | 343,228.570 | 343.555084 | 344.195068 | 76.9438% | 70.2245% | global mixing | 70.2245% |
| attention residual update | 1,584.282 | 1.584128 | 1.587200 | 0.3552% | 0.3241% | positionwise/local | 0.3241% |
| feed-forward positionwise | 95,276.471 | 95.278595 | 96.222206 | 21.3587% | 19.4935% | positionwise/local | 19.4935% |
| feed-forward residual update | 1,601.435 | 1.601536 | 1.604608 | 0.3590% | 0.3277% | positionwise/local | 0.3277% |

Each ideal ceiling assumes that the entire measured group span disappears with
zero closure, verification, orchestration, or quality cost. Every value is
`THEORETICAL_ONLY`; none is attainable reduction, combined speedup, or a
product claim.

The parent `DiTBlock` mean/p50/p95 were 446.077034/446.415863/447.491058 ms.
Early/middle/late block means were 446.012636, 446.123797, and 446.095772 ms.
Early/middle/late denoise-step means were 445.091105, 446.590213, and
446.628577 ms. The deterministic buckets were not changed after Generation.
The surface is nearly uniform by block and by steady-state step; the first
step's model initialization is represented separately by wall telemetry and
is not reassigned into CUDA group spans.

## Ranking, overlap, and decision

Global attention is the dominant measured component at 70.2245% of sampler
event span, but it is globally coupled and not structurally subset-executable
under the inspected source contract. It remains Full Compute. The selected
`NEXT_PRIMARY_COMPUTE_LEVER` is therefore `MIXED_SUBBLOCK_SELECTIVE`, with
`feed_forward_positionwise` as the selected group: retain global attention
while investigating, under a separate approval, whether the 19.4935%
positionwise surface can participate in observation-guided bounded execution
without losing transformation quality.

Secondary candidates preserve global attention first as the dominant but
separately constrained attention-specific surface, followed by attention
norm/modulation, feed-forward residual update, attention residual update, and
modulation projection. The feed-forward group overlaps future regional
compute, is independent from the attention kernel and VAE, and can remain
isolated in the H3 adapter. This makes it potentially composable with other
independent savings toward the final 2.0x target, but no combined-speedup
number is manufactured here.

Compound Eye observations may eventually provide candidate region/activity
metadata, but `Observation != Compute Authority`. Any uncertain, invalid, or
unsupported condition must execute Full Compute. No C4-S1 implementation,
MLP partial execution, attention change, token/region omission, cache, or
automatic next stage was started.

The final technical decision is `C4_S0_SUBBLOCK_COST_SURFACE_MAPPED`. Actual
selective work reduction, speedup claim, quality promotion, and product
promotion are all zero. Quality/speed comparison is not applicable because
the computation path was intentionally unchanged. Full Compute remains the
default and safe fallback.

## Evidence, privacy, and diagram impact

The repository stores only the sanitized aggregate knowledge record. Prompt,
media, full receipts, runtime logs, local paths, and detailed resource samples
remain outside Git. External API calls, model downloads, source modifications,
Rust ABI changes, training actions, Ready transitions, merges, and Issue closes
were all zero.

Diagram impact: `updated`. C3-R4 publication and the bounded C4-S0 mapping
change the published evidence progression and selected next candidate, without
admitting the planned optimized path.
