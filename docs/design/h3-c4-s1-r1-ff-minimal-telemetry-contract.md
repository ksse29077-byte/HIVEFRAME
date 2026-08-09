# C4-S1-R1 Minimal Telemetry Contract

Status: predeclared implementation contract

This revision consumes the single `REVISE_ONCE` granted by C4-S1. It asks the
same product question and keeps `FF_POSITIONWISE_LOW_IMPACT_TOKEN_SKIP_V1`
unchanged. Only measurement-only work is removed.

## Immutable selector behavior

- P0, P1, and P2 thresholds are unchanged.
- Attention is always Full Compute.
- Only target-video feed-forward rows are eligible.
- Non-video rows are always Full Compute.
- Anchor steps remain `0, 1, 18, 19`.
- Consecutive skip remains prohibited without intervening actual Full Compute.
- The minimum per-block video skip ratio remains 10%.
- Scalar history is refreshed only from actual Full Compute results.
- Invalid layout or state fails open to Full Compute.
- Full tensor cache, tensor-to-Rust transfer, and full host tensor copy remain zero.

## Removed measurement-only work

- Per-block CUDA event pairs: zero.
- Explicit CUDA synchronization in the hot path: zero.
- Detailed sub-block CUDA timing: not collected.
- 4,096-bin impact histogram: removed.
- One-second resource polling: disabled.
- CONTROL hot-path `.item()`, `.cpu()`, `.numpy()`, and `.tolist()`: zero.

Sampler wall time, submit-to-terminal time, runner total time, output integrity,
and fatal process/CUDA/OOM failures remain observable at existing runner
boundaries. Peak VRAM and RSS are `null/not_collected`, never zero-filled.

## Bounded impact aggregates

For each frozen policy, the GPU hot path retains only fixed-shape scalar
reductions: candidate count, impact sum, impact maximum, count above `0.010`,
and non-finite count. Host reads happen during finalize only.

No numeric p99 is produced. Its value is `null` with status
`derived_from_stricter_tail_gate`. Under the conservative nearest-rank
interpretation, `count(x > 0.010) / count(x) <= 0.005` means at least 99.5% of
observations are at most `0.010`; therefore p99 is also at most `0.010`. The
frozen tail-rate condition is retained rather than replaced or weakened.

## Frozen gates

CONTROL must remain within ±5% of the immutable C4-S0 sampler reference
`488.847320 s`. Only then may the unchanged P0/P1/P2 admission be evaluated.
A SELECTIVE generation is allowed only when one frozen policy passes every
opportunity and impact gate. Maximum generations are one CONTROL plus one
conditional SELECTIVE, with zero retries.

Failure of comparability or policy admission ends this exact selector as
`FALLBACK_ONLY`; no C4-S1-R2 is automatic. The C4-S0 feed-forward cost surface
and global-attention surface remain valid separate evidence.
