# 2026-08-24 H3 End-to-End Bottleneck Profile

## Objective

Freeze the exhausted V4 path and identify a measured H3 acceleration candidate
whose projected product impact is at least 10 percent end to end.

## Start Gate

- PR #138 remained OPEN and DRAFT and was not modified.
- PR #138 local, remote, and GitHub HEAD matched
  `6747e96a6ca94cdb4f137aebc36b86eb4b5b08b4`.
- The source worktree was clean.
- Issue #139 was created.
- Branch `codex/h3-e2e-bottleneck-profile-plan` was created from the exact PR
  #138 HEAD.

## Existing Evidence

The immutable evidence inventory is
`artifacts/h3-high-impact-profile-existing-evidence-20260824.json`. P1-A2
measured 559.391 seconds submit to terminal. The comparable C4-S0 Full Compute
run measured 488.847 seconds in the sampler and 589.913 seconds submit to
terminal. Its six child spans covered 91.253 percent of the sampler, below this
task's 95 percent accounting Gate. V4's final 537.654-second sampler included
19.646 GB of observer evidence transfers and is not a Standard-path profile.

This established that one additional Standard Generation is necessary and
that no previous generation should be repeated.

## Implementation

`H3AggregateTimingController` temporarily wraps the exact installed H3 model
and block methods. It reproduces the source operation order while recording
deferred CUDA event pairs for aggregate leaf categories and enclosing model
and sampler spans. It resolves them after sampler completion with one
synchronization. The callback contains aggregate scalar timings only.

The dedicated ComfyUI node and one-shot runner enforce the unchanged Standard
profile, private first-frame identity, source and workflow hashes, fresh-runtime
ownership, queue emptiness, output integrity, 95 percent accounting, and zero
V4/SELECTIVE/partial-Q/omission execution.

## Focused Verification Before Generation

- Python compilation: PASS.
- New aggregate profiler unit tests: 5 PASS.
- C4-S0 regression tests: 10 PASS, 1 environment-dependent source test SKIP.
- Generation submissions: 0.
- GPU starts: 0.

## Formal Profile

Commit `7615ce5...` was pushed and stacked Draft PR #140 was opened. The clean
local/origin HEAD, fixed source/workflow/input identities, zero active product
jobs, zero foreign ComfyUI runtimes, free port 8191, and idle 10 MiB GPU
baseline passed Admission.

Exactly one Standard Full Compute profile was submitted. Submission/GPU
start/completion was `1/1/1`; retry/fallback was `0/0`; SELECTIVE, partial-Q,
Attention omission, V4 observer, V4 transfer, and tensor payload D2H were zero.
The callback observed 20 model forwards and 1,000 calls for every leaf group,
22,042 bounded event objects, no mapping/wrapper failures, no hot-path CPU
synchronization, and one 0.0000385-second finalize synchronization.

Sampler wall was 530.495782 seconds and its CUDA event span was 529.616500
seconds. Submit-to-terminal was 635.249150 seconds and verified
submit-to-output was 636.010680 seconds. The non-overlapping top-level ledger
and nested sampler ledger both accounted for 100 percent without adding parent
spans to child spans.

Attention consumed 386.567680 seconds including norm/modulation and residual;
the QKV/RoPE/kernel/out candidate surface was 380.238468 seconds. The Attention
kernel alone was 314.551627 seconds. MLP/FFN consumed 100.811781 seconds. Video
VAE decode was 62.207073 seconds, input/prompt conditioning 38.719113 seconds,
and model pre/post/offload residual 37.786917 seconds. Exact H2D/D2H transfer
time remains explicitly uncollected because the bounded contract prohibited a
transfer trace, tensor D2H, and per-call synchronization.

Output integrity passed with H.264, 864x480, 124 frames, 24 FPS, native audio,
zero black/corrupted frames, and no exact adjacent duplicates. The owned
runtime tree stopped, its console helper exited naturally, port 8191 and owned
processes returned to zero, GPU returned to 10 MiB, and no external process was
terminated.

## Decision

The selected next implementation task is
`H3_TIER_B_EXACT_ATTENTION_BACKEND_QKV_ROPE_OUT_FUSION_AB`. A conservative 20
percent reduction of its measured surface projects 76.047694 seconds or
11.956984 percent E2E, a Tier-B planning estimate. It fits RTX 3060 12 GB only
with at most 256 MiB incremental VRAM, at least 128 MiB remaining reserve, no
persistent cache, and exact Standard fallback.

V4 remains `EXPERIMENTAL_AUXILIARY_FROZEN`, disabled by default, with no
executable plan and zero product contribution. Existing final evidence shows
all 13 Rust block/region candidates were rejected as `CACHE_REJECT_NOT_STABLE`;
zero selected candidates then produced final reason 9,
`PRE_GATE_BELOW_THREE_PERCENT`. The 3.007449 percent row evidence opportunity
therefore remained a 0 percent Rust plan.

The selected Tier-B task projects approximately 559.963 seconds
submit-to-output and does not make the two-minute target credible by itself.
Current E2E would need an 81.132 percent reduction; with non-sampler time fixed,
the sampler would need a 97.270 percent reduction. No optimization or
additional Generation was started after the profile.

```text
H3_HIGH_IMPACT_PROFILE_COMPLETE_READY_FOR_IMPLEMENTATION
```
