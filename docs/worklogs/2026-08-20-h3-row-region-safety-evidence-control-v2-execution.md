# H3 Row Region Safety Evidence CONTROL V2 Execution

## Authorization and scope

Issue #119 tracks the one-time constitutional exception for exactly one H3
Standard Full Compute CONTROL Generation. The work starts from exact Draft PR
#118 head `aaf4e325c511860a5d5b5f6579cea18f270425d6` on branch
`codex/h3-row-region-safety-evidence-control-v2-execution`.

The authorized product question is whether a complete independent H3 CONTROL
can produce safe row/region holdout evidence and a deterministic Rust CachePlan
V2 with at least 3% evidence-based planned Q reduction. This run cannot execute
SELECTIVE, partial-Q, cache-reuse omission, Attention omission, product
integration, LTX, Wan, or Installer work. Retry and fallback Generation are
zero.

## Start Gate

- PR #118 remote head: `aaf4e325c511860a5d5b5f6579cea18f270425d6`
- Checkout head: `aaf4e325c511860a5d5b5f6579cea18f270425d6`
- Worktree at branch creation: clean
- Console-helper ownership V2 implementation: present
- Console-helper focused regression fixtures: present
- Existing protected PRs: unchanged

The earlier base-mismatch stop performed no runtime start, submission, or GPU
work and is not counted as a retry.

## Immutable P1-A2 profile reference

The P1-A2 succeeded Standard I2V receipt is the fixed comparison source. Its
input identity digest is
`493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411`,
its workflow digest is
`31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6`,
and its prompt is retained privately with only its digest recorded in CONTROL
evidence.

The frozen profile is 864x480, 124 frames, 24 FPS, 20 steps, seed 101,
`res_multistep`, `simple`, Standard precision/offload/checkpoint behavior, and
Sage disabled. Fast, Selective, partial-Q, omission, and fallback profiles are
disabled.

## Admission result

The model-free Gate passed before any runtime start or submission. External
product jobs, foreign ComfyUI runtimes, foreign listeners, and the dedicated
8191 listener were all zero. The input, prompt, workflow, source, immutable
oracle, and release PyO3 identities matched. Release verification remained
15/15 PyO3 tests with skip zero, 12 Rust CachePlan tests, zero Rust tensor
bytes, at most one Rust call per generation, and zero Rust hot-path calls.

The projected CUDA peak was 12,514,625,897 bytes against 12,884,377,600 bytes
of physical VRAM, leaving 369,751,703 bytes and passing the 256 MiB minimum.
The 2 GiB reserve remains `UNSATISFIED_BY_BASELINE`, as explicitly allowed by
the authorization. After the dedicated runtime started, the pinned ring was
page locked at exactly 96,538,624 bytes, host admission passed, the queue was
0/0, and console-helper ownership V2 passed. Only then was `/prompt` called.

## Single CONTROL result

Submission/GPU start/completion was 1/1/0. Retry, fallback Generation,
SELECTIVE, partial-Q, and Attention omission were all zero. The fixed H3
Standard Full Compute sampler executed all 20/20 steps. ComfyUI reported 784
seconds for the prompt; the final progress event arrived 779.790 seconds after
submit and the complete runner lifecycle was 808.622 seconds.

The workflow then failed closed while finalizing the background CPU oracle.
`HybridControlOracleWorker._consume` called
`slot.transfer_start.elapsed_time(slot.event)`, but `slot.event` had been
created without `enable_timing=True`. PyTorch raised `ValueError: Both events
must be created with argument 'enable_timing=True'`, which became
`ControlV2EvidenceError: background CPU oracle failed` and a ComfyUI
`execution_error` terminal event.

Because finalization failed, the bounded 480-record holdout batch, false-safe,
false-unsafe, planned Q reduction, Rust live compile, Rust offline replay, and
output integrity are all `NOT_ESTABLISHED`. Rust live/replay calls were 0/0 and
no output artifact was admitted. Partial worker state is not used as evidence.

## Resource and shutdown receipt

Peak sampled NVIDIA VRAM was 11,724,128,256 bytes, leaving 1,160,249,344 bytes
of physical headroom. Peak sampled ComfyUI VRAM was 12,004,259,239 bytes, peak
process-tree RSS was 43,216,089,088 bytes, and peak system RAM use was
62,878,056,448 bytes. These are sampled values, not allocator-exact peaks.

The verified launcher/runtime Python tree was stopped, the trusted console
helper exited naturally, direct console-helper termination was zero, and
foreign-process termination was zero. POST_SHUTDOWN ownership passed with no
owned identities, no foreign runtimes, no 8191 listener, and GPU memory back at
the 10 MiB baseline.

Immutable receipt digests:

- private/public summary SHA-256:
  `b51398700b169f32b2ed5fd29532288e6554946ffd00c32ce3c19e012c309bf6`
- callback SHA-256:
  `a7263727c3cf33f0bc9e3cc64af5a2c7bd993f71db32671a030eb433cd6d3954`
- pinned admission SHA-256:
  `e65ac8fa8db72ba063a9fc288f87257d6e5939a4b6f54535c61cb64befc281d1`

Final decision:
`H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_FAILED`.

The one-time exception ended after this single CONTROL. No code remediation,
retry, executor integration, or subsequent research stage was started.
