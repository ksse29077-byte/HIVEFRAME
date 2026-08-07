# C3-R3 — Compact Residual Correction / Prediction

Status: Draft evidence; `C3_R3_PREDICTOR_SIMILARITY_TOO_LOW`

## Product question and constitutional boundary

Can one previous Full Compute residual plus channel-wise compact correction
metadata, derived from two consecutive Full Compute residuals, pass the
unchanged C3-R2 similarity Gate and safely enter real H3 block reuse?

Quality remained the first Gate. Output correctness, visual/temporal quality,
semantic stability, and Full Compute fallback precede compute reduction and
runtime. Product promotion was fixed to zero. This stage could establish only
mechanism evidence; it could not claim the long-term product target of quality
at least Standard and end-to-end speed at least 2x.

The task started from clean `main` at
`eaa2f73e4e3246cda546b6a550ccf73824ec7b46`, after reading `AGENTS.md`, the
execution context, task ledger, worklog, C3-R1/R2 evidence, and H3 hook code.
No constitutional conflict was found. Issue #70, branch
`accel/c3-r3-h3-compact-residual-correction`, and Draft PR #71 isolate the
work. Diagram impact is `updated`: the Living System Map now records the
bounded C3-R3 rejection and preserves Full Compute as the default.

## Frozen mechanism and architecture

`CHANNEL_AFFINE_RESIDUAL_PREDICTION_V1` predicts
`R_hat_next = gain * R_current + bias`. Before runtime, the implementation
froze channel standard deviation as the scale statistic, epsilon `1e-6`, gain
clipping `[0.90, 1.10]`, 256-row bounded FP32 reduction chunks, compact
metadata at no more than 64 KiB, and unchanged C3-R2 cosine/L2 thresholds of
`0.99` and `0.20`. Corrected metrics also had to be no worse than raw reuse.

Generic Rust Core gained a fixed-width `CorrectionPlanObservation` and
`CorrectionPlanDirective`. They contain digests, two source steps, cache and
predictor validity, calibrated-target state, Eye state masks, invalidation,
and fallback metadata. They contain no H3 name, tensor, pointer, path, hidden
width, or block number. The H3 adapter owns the 50-block mapping, segment
12..48, packed residual layout, CUDA residual, channel statistics, gain/bias,
and correction application. Existing C1/C2/C3-R1/C3-R2 ABIs were unchanged.

The memory contract allows one persistent full residual, zero persistent
predicted residuals, one transient segment snapshot, at most two simultaneous
residual-sized buffers, no per-block cache, no full activation `.float()`
materialization, no full tensor host copy, and zero tensor bytes to Rust.
After an admitted replay the chain is invalidated and two Full Compute steps
must re-seed it. Deterministic target spacing is therefore at least three.

## Model-free validation and implementation commit

The changed surface passed Python compile, eight C3-R3 focused tests, fourteen
C3-R2 regression tests, four C3-R2 Rust tests, three C3-R3 Rust tests, Rust
format/check, PyO3 release build/import, and an actual ABI roundtrip. The WSL
focused run skipped the unavailable Windows PyO3 binary; a Windows Python
3.12 ABI3 import subsequently passed all eight C3-R3 tests including the
roundtrip. No model or CUDA was used by these checks.

Commit `b48022e29641183972f34b740ea512b2b6764d1b` froze the code, formula,
thresholds, memory bounds, tests, and runtime probe before any Generation. It
was pushed normally before Draft PR #71 was created. Runtime source was not
changed after observing results.

## Source admission and CONTROL

The installed H3 source SHA-256 remained
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`,
identical to C3-R1/R2 evidence. The packed input/output contract, 50 blocks,
segment 12..48, Block 49 handoff, dtype/device preservation, and unchanged
Standard workflow revision `video_minimax_h3_t2v@31ab33fdb053` were admitted.

Exactly one fresh-process `CONTROL_CORRECTION_SHADOW` Generation ran with the
fixed private prompt, seed 101, 864x480, 124 frames, 24 FPS, 20 steps,
`res_multistep`, `simple`, native audio, and Sage disabled. It succeeded with
retry, OOM, CUDA error, non-finite, black-frame, and corrupt-frame counts zero.
The H.264 output decoded 124/124 frames and one audio stream. Output SHA-256 is
`3b6d4e0d648d06fb9e63bff255cc0d4a7873a6927aeb727bad9b6335805b64b3`.

CONTROL observed 20 callbacks, 20 C2 Rust calls, 18 C3-R3 Rust calls, 1,000
original block calls, 20 residual captures, and zero replay calls. The
observed H3 channel count was 5,376; gain+bias plus small provenance occupied
43,264 bytes. Nineteen predictors were created and all were finite. The
observed gain range reached the frozen clip edges; 185 low and 12,655 high
channel instances were clipped across predictor constructions.

The bounded full residual occupied 165,838,848 bytes. The maximum two-buffer
allowance was 331,677,696 bytes. Peak sampled ComfyUI VRAM was 12,458,721,204
bytes and NVIDIA sampled VRAM was 11,856,248,832 bytes on a 12,884,377,600-byte
device. Process-tree sampled peak RSS was 46,984,065,024 bytes. These are
sampled process/system values; the ComfyUI PyTorch allocator peak was
unavailable to the external runner and is recorded as null, not zero.

## Calibration result

All six diagnostics were finite, but none passed the combined Gate:

| Target | Sources | Raw L2 / cosine | Corrected L2 / cosine | Result |
|---|---|---|---|---|
| 5 | 3,4 | 0.210538 / 0.979908 | 0.204514 / 0.978947 | reject |
| 6 | 4,5 | 0.315677 / 0.952363 | 0.305535 / 0.952805 | reject |
| 8 | 6,7 | 0.274341 / 0.964360 | 0.271103 / 0.963112 | reject |
| 13 | 11,12 | 0.238931 / 0.971456 | 0.241757 / 0.970361 | reject |
| 16 | 14,15 | 0.162921 / 0.986979 | 0.160045 / 0.987110 | reject |
| 17 | 15,16 | 0.167788 / 0.986941 | 0.171937 / 0.985586 | reject |

Step 16 was the best corrected candidate, but cosine remained below 0.99.
Some candidates improved L2 or cosine, yet no candidate passed both fixed
thresholds and the raw-non-regression rule. The selected target list is empty,
below the predeclared minimum of two.

## Timing and decision

CONTROL sampler, submit-to-terminal, and runner spans were 488.710265,
589.371095, and 600.215317 seconds. Channel statistics consumed 0.103886
seconds cumulatively, gain/bias construction 0.177786 seconds, and six paired
similarity diagnostics 0.224211 seconds. C3-R3 Rust boundary p95 was 11.7
microseconds and the cumulative boundary span was 151 microseconds. Exact GPU
kernel duration was not collected because no profiler run was authorized.

Because calibrated targets were zero, the contract prohibited SELECTIVE.
SELECTIVE Generation, corrected replay, omitted block calls, paired visual
quality, sampler/E2E ratios, and visual equivalence are uncollected rather than
reported as zero. Generation count is one, retry count zero, SELECTIVE count
zero, and third Generation count zero.

The final decision is `C3_R3_PREDICTOR_SIMILARITY_TOO_LOW`. This means the
fixed channel-affine predictor did not provide sufficient quality-first
admission for this profile. It does not invalidate HIVEFRAME selective compute
as a general direction, and it does not authorize lowering C3-R2 thresholds.
Full Compute remains the default and safe fallback. Speedup claim, quality
guarantee, product promotion, and product acceleration readiness remain zero
or false. A next research stage requires separate approval.

## Evidence custody

Private media, prompt, complete receipt, resource samples, runtime log, and
local paths remain outside Git. Public knowledge contains only logical IDs,
digests, bounded measurements, and claim limits. Private receipt and callback
receipt SHA-256 values are recorded in the C3-R3 knowledge entry. External API
calls, model downloads, installed-source changes, original workflow changes,
Ready transitions, merge operations, and Issue closure were all zero.
