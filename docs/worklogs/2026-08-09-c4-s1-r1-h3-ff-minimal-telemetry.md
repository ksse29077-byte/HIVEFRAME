# C4-S1-R1 — Minimal Telemetry / Selector Overhead Truth

Status: Draft PR evidence; publication not authorized

## Product question and constitutional boundary

C4-S1-R1 consumes the single `REVISE_ONCE` granted by C4-S1. It asks whether
the exact causal feed-forward selector can recover CONTROL comparability when
measurement-only instrumentation is minimized, and only then whether the same
selector earns conditional SELECTIVE execution authority.

The working product objective remains `Quality >= Standard Full Compute` and
accepted-result end-to-end speed at least 2.0x. This bounded experiment was
not required to reach 2.0x alone. A positive component could accumulate with
other admitted components; a negative result cannot weaken quality or timing
Gates. Full Compute remains the default and fallback.

The task began from `main@fd6ea5b19c5b770afb7c47f162ab6d382c4ebd6b`
with a clean worktree. PR #77 was merged and Issue #76 completed. Existing
C4-S0 and C4-S1 reports, receipts, thresholds, decisions, and Git evidence
were not rewritten. Issue #78, branch
`accel/c4-s1-r1-h3-ff-minimal-telemetry`, and Draft PR #79 isolate this
revision. Commit `28c21dc0f4d0887aa72b250f03f090ed688cb122` fixed the
implementation and Gates before runtime.

## Immutable selector and allowed revision

`FF_POSITIONWISE_LOW_IMPACT_TOKEN_SKIP_V1`, P0/P1/P2 values, anchor steps
`0, 1, 18, 19`, target-video-only eligibility, non-video Full Compute,
actual-Full-Compute scalar history, invalidation, no consecutive skip, the 10%
per-block guard, all opportunity and quality Gates, and global-attention Full
Compute execution are unchanged. No policy, threshold, search, or new selector
was introduced.

The revision removed only measurement-only work:

- per-block CUDA event pairs: 0;
- explicit hot-path CUDA synchronization: 0;
- CONTROL hot-path `.item()` reads: 0;
- hot-path tensor-to-CPU/full-host transfer: 0;
- 4,096-bin impact histogram: removed, with zero bins;
- one-second resource sampling: disabled;
- detailed FF/MLP/gather/scatter timing: `null/not_collected` with reasons.

Sampler wall, submit-to-terminal, runner total, output integrity, OOM/fatal
CUDA/process failure, and Full Compute fallback remained observable. Peak VRAM
and process-tree RSS were deliberately not sampled and are not fabricated as
zero. A post-run receipt-envelope audit found that the shared helper labeled
their actual private receipt status `unavailable` and unit `seconds`; the code
was normalized afterward to explicit `not_collected` and byte units without
changing the runtime result, algorithm, thresholds, Gate, or immutable private
receipt. No Generation was repeated.

Selector-required current h/gate norms, prior actual-Full-Compute scalar
history, all three causal masks, and history refresh remained active in
CONTROL. Each policy accumulated only fixed-shape GPU scalars: candidate count,
impact sum, maximum, count above 0.010, and non-finite count. Host reads happened
at finalize only.

## p99 decision-equivalence proof

The frozen Gate requires `impact > 0.010` rate at most 0.005. Therefore at
least 99.5% of finite observations are at most 0.010, which conservatively
implies the nearest-rank p99 is at most 0.010. R1 records numeric p99 as
`null`, status `derived_from_stricter_tail_gate`, and derives
`p99_gate_pass` from the unchanged tail-rate Gate. It neither estimates a
percentile nor weakens the threshold. Focused tests prove the boundary:
5/1,000 above threshold passes, while 6/1,000 fails.

## Model-free validation and static audit

Python compilation, changed-package import, config parsing, and
`git diff --check` passed. The new focused suite plus the existing C4-S1 suite
ran 27 tests successfully; one installed-source test was skipped because its
optional explicit root variable was absent, while the source file and exact
SHA-256 were independently verified before runtime. Static and behavioral
tests confirmed zero per-block events, explicit synchronization, histogram,
CONTROL host scalar reads, and host tensor transfer; unchanged policy values,
anchors, 10% guard, history semantics, video/non-video behavior, fail-open,
wrapper restoration, bounded aggregates, p99 implication, fixed comparison
Gate, and workflow mapping were covered. Rust changed by zero files and Rust
build count was zero under the focused-validation contract.

## Fixed CONTROL execution

Exactly one fresh owned loopback ComfyUI CONTROL Generation ran the frozen H3
profile: seed 101, 864x480, 124 frames, 24 FPS, 20 steps, `simple`,
`res_multistep`, denoise 1.0, native audio, H.264, and Sage disabled. The
installed source digest and workflow revision matched the immutable values.
The private prompt hash matched C4-S1; the prompt itself remains outside Git.
Retry was zero.

CONTROL completed 20 model forwards, 1,000 block calls, 1,000 MLP calls, and
15,424,000 full/actual MLP rows. Omitted video rows, attention omissions,
non-video omissions, fail-open events, mapping errors, wrapper failures,
full-tensor caches, host full-tensor copies, and tensor-to-Rust bytes were all
zero. Scalar history used 11,238,750 of the 67,108,864-byte budget. Every
minimal-instrumentation integrity check passed.

The output decoded 124/124 frames at 864x480 and 24 FPS, H.264, with one audio
stream. Black and corrupt frame counts, OOM, retry, and fatal CUDA errors were
zero. The private video is 263,031 bytes with SHA-256
`1ebc1eaeb6a597d5996d327c80b759207d16dc126611af19713d14dadc50d490`.
Media, prompt, full receipts, runtime log, event log, and local paths remain
outside Git.

Sampler wall was `520.4888703000033 s`, submit-to-terminal was
`626.2422419000068 s`, and runner total was `645.1564394999878 s`. Relative
to the immutable C4-S0 reference `488.847320 s`, sampler delta was
`+31.641550300003303 s` or `+6.472685643444522%`, outside the fixed +/-5%
band. Relative to C4-S1's `519.822272 s`, the minimal path was
`+0.6665983000033293 s` or `+0.12823580979680095%`; this diagnostic is not a
speedup claim.

## Diagnostic policy observations

The masks produced the same candidate counts as C4-S1, confirming selector
continuity. They are diagnostic only because the earlier CONTROL comparison
Gate failed; official policy admission was not evaluated.

| Policy | Rows | Video ratio | All-row ratio | Steps | Blocks | Mean | Max | >0.010 rate | Derived p99 Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P0 | 8 | 0.0000534% | 0.0000519% | 5 | 1 | 0.002301 | 0.002704 | 0% | pass |
| P1 | 78 | 0.0005205% | 0.0005057% | 15 | 2 | 0.004236 | 0.007571 | 0% | pass |
| P2 | 1,000 | 0.0066733% | 0.0064834% | 16 | 9 | 0.008144 | 0.016236 | 7.4% | fail |

All non-finite counts were zero. Numeric p99, p50, and p95 are uncollected.
P0/P1/P2 impact sums were respectively 0.0184065674, 0.3303835115, and
8.1435753698. No policy received compute authority.

## Gate, claim boundary, and disposition

The fixed CONTROL comparability Gate failed, so SELECTIVE Generation count is
zero. Actual selective MLP rows, omitted rows, backend work reduction, paired
runtime, quality, SSIM/MAE/motion/gradient results, visual equivalence, and
human review are `not_collected` or `not_proven`, not recorded as zero.

The technical decision is
`C4_S1_R1_MINIMAL_PATH_OVERHEAD_TOO_HIGH`; constitution and exact-selector
disposition are `FALLBACK_ONLY`. The single C4-S1 revision is consumed. There
is no automatic C4-S1-R2. This rejects neither the measured 19.4935%
feed-forward cost surface nor other separately approved feed-forward
mechanisms. Global attention remains unchanged Full Compute evidence at
70.2245%. Actual backend work reduction, speedup claim, quality promotion,
and product promotion are zero. The cumulative quality-preserving 2.0x goal
remains unchanged and unproven.

External API calls, model downloads, source/workflow changes, training,
Ready transition, merge, and Issue close are zero. Diagram impact is
`updated`: the exact C4-S1 selector now terminates at R1 `FALLBACK_ONLY`, while
the independent feed-forward and attention cost surfaces remain visible as
unadmitted future evidence. No next stage started.
