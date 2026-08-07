# C3-R2 — Quality-Preserving Segment Residual Replay

Status: `verified_once`; Draft PR evidence, not product admission

Starting main: `5c9155cd0391e7067e540bad2e6e9ce57f31bbe9`

Issue: [#67](https://github.com/ksse29077-byte/HIVEFRAME/issues/67)

Branch: `accel/c3-r2-h3-segment-residual-reuse`

Draft PR: [#68](https://github.com/ksse29077-byte/HIVEFRAME/pull/68)

## Product question and quality-first rule

Can HIVEFRAME reuse the one-step-old transformation residual produced by H3
blocks 12 through 48, omit those 37 original forwards on a bounded set of
safe steps, and preserve the matched Full Compute output closely enough to
pass the fixed automatic quality Gate? Evaluation order is output correctness,
quality, semantic/structural stability, Full Compute fallback, actual compute
reduction, and only then runtime speed. Any quality failure rejects the
mechanism regardless of observed speed.

C3-R1 remains immutable evidence. It verified 148 real identity-bypass calls,
1.153991x sampler and 1.125478x submit-to-terminal ratios, but failed quality
with mean/p05 SSIM 0.805245/0.764500 and motion-energy ratio 1.834976.
`SELECTIVE_BLOCK_BYPASS_IDENTITY` is therefore not a product strategy.

## Architecture and adapter boundary

Core owns generic `ReusePlanObservation` / `ReusePlanDirective`, calibrated
target membership, cache-age/provenance validity, live STABLE/ACTIVE/UNCERTAIN
safety, invalidation, and fail-open decisions. The Core contract contains only
fixed-width scalar metadata and digests. It has no H3 block count, DiTBlock,
patches_replace, x0 path, activation shape, tensor, pointer, prompt, path, or
CUDA address.

The replaceable H3 adapter owns `SEGMENT_RESIDUAL_REPLAY_V1`, the packed image
activation, blocks 12..48 inclusive, GPU snapshot/cache ownership, residual
similarity reductions, and the patches_replace wrapper. C1, C2, and C3-R1
ABIs remain unchanged.

## Source admission and in-place ownership

The installed MiniMax H3 source SHA-256 remains
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`,
the same source admitted by C3-R1. `DiTBlock.forward` accumulates gated
attention and MLP residuals into packed `x` in place. The ordered block loop
passes the replacement wrapper's returned `img` directly to the next block;
prefetch queue operations remain outside each wrapper. The packed segment
input/output therefore retain shape, dtype, device, and logical stream
contract, and Block 49 receives the replay result normally.

Because the stream mutates in place, the adapter takes exactly one GPU clone
at Block 12 on Full Compute steps. After Block 48, that same snapshot buffer is
converted in place to `segment_output - segment_input`. The target is one
persistent residual cache plus at most one transient snapshot, zero per-block
caches, no CPU/NumPy snapshot, and no full-tensor host copy. Removing the
repository-owned guider clone restores the unchanged Standard path.

## Frozen pre-run gates

- Frozen ceiling: steps `[5, 6, 8, 13, 16, 17]`.
- Full Compute anchors: `[0, 1, 18, 19]`.
- Candidate segment: blocks 12..48 inclusive, 37 calls.
- Cache source: Full Compute only; reuse never creates cache.
- Cache age: exactly one; reuse consumes it once.
- Consecutive reuse: forbidden; maximum four target steps and 14.8% of 1,000
  original block calls.
- Residual cosine similarity: at least 0.99.
- Normalized residual L2: at most 0.20.
- Similarity definition:
  `||delta_t - delta_(t-1)||_2 / ||delta_(t-1)||_2`; its norm is derived on
  GPU from `||a||² + ||b||² - 2<a,b>`. Cosine is
  `<a,b> / (||a|| ||b||)`. Only resulting scalars cross to host.
- Maximum-safe selection: greedy chronological selection among admitted
  frozen candidates, rejecting a target consecutive to the last selected
  target and capping the result at four. Thresholds will not change after
  CONTROL.
- Live reuse additionally requires cache age/provenance/finite validity,
  valid source and prediction, stable count at least two, active count zero,
  no global invalidation, no overlap conflict, no fatal flag, and no previous
  reuse. Live C2 can only veto a calibrated target.
- Automatic quality Gate: mean SSIM >= 0.95; p05 >= 0.90; minimum >= 0.85;
  frames below 0.85 <= 2%; normalized MAE <= 0.03; motion-energy and
  gradient-energy ratios each in `[0.90, 1.10]`.
- READY mechanism Gate: quality passes, at least three actual reuse steps,
  at least 11.1% block-call reduction, sampler ratio >= 1.08x, E2E ratio >=
  1.05x, and all safety/resource conditions. Even a pass has product
  promotion zero and visual equivalence `not_proven`.

## Fixed CONTROL and SELECTIVE contract

`CONTROL_RESIDUAL_CAPTURE` performs all 1,000 original calls and zero replay
while retaining C2, C3-R2 Rust planning, snapshot/capture, lifecycle,
provenance, similarity, and memory accounting. A successful bounded CONTROL
with at least two safe calibrated targets is required before SELECTIVE.

`SELECTIVE_RESIDUAL_REPLAY` applies `current_img + cached_segment_delta` once
at Block 12, calls no original block in 12..48 for that step, and resumes
ordinary Full Compute at Block 49. Required accounting is
`1000 - selective_original_calls == reuse_steps * 37`.

Both runs, if admitted, use a fresh loopback ComfyUI process, the same private
prompt digest, seed 101, 864x480, 124 frames, 24 FPS, 20 steps, simple
scheduler, res_multistep sampler, denoise 1.0, native audio, H.264, Sage count
zero, and retry zero. Maximum generation count is two; a failed CONTROL or a
CONTROL with fewer than two safe targets forbids SELECTIVE.

## Pre-runtime verification

Focused verification covers the new Rust ABI and deterministic fail-open
policy; Python cache ownership, replay accounting, adapter restoration, and
workflow mapping; PyO3 release build/import and C1/C2/C3-R1/C3-R2 ABI
roundtrips; Python compilation; Rust formatting; and diff checks. Full suites
are deliberately excluded by the work order and Product-First verification
budget.

The focused pre-runtime results were four C3-R2 Rust tests and 47 focused
Python tests spanning C1, C2, C3-R1, and C3-R2. Python compilation, Rust
format/check, PyO3 release build/import, four ABI checks, source admission, and
the model-free adapter tests passed. The implementation was frozen in commit
`0ec5945539b3fb357710bc354ecce9260d90db6d` before runtime execution. No full
Python or Rust suite was run because the work order expressly prohibited it.

## CONTROL execution

Exactly one fresh-process `CONTROL_RESIDUAL_CAPTURE` generation was submitted
under the fixed profile. The private prompt remained unchanged and is not
published; its public logical ID is `private_unchanged`. Seed 101, 864x480,
124 frames, 24 FPS, 20 steps, simple scheduler, res_multistep sampler, denoise
1.0, native audio, H.264, and Sage count zero were retained. The run succeeded
with retry zero and produced an H.264 MP4 that decoded 124/124 frames with one
audio stream. Its output SHA-256 is
`80d9a23a98a7ba8f2312e9c3d1d6d57bb2652aaacd8111c174cf3380d90b403f`.
The private receipt SHA-256 is
`b6d495c25bdeaa00b7a7c2491458662e4f7145a10a0126d50205ddc43097fff5`.
The sanitized public-summary SHA-256 is
`c907519c86c76fa6d8662ba4964454d6ca8f7a453ba07dcacdc2d9dabb38ef77`.
Media, complete logs, prompt, raw tensors, and private paths remain outside
Git under logical root `C3_R2_ARTIFACT_ROOT`.

CONTROL recorded 20 model forwards, 1,000 original block calls, zero replay
calls, 20 residual captures, 20 cache generations, zero invalidations, zero
mapping errors, and zero wrapper failures. C2 observed 20 callbacks, 20 Rust
calls, and 20 Full Compute directives. C3-R2 made 18 Rust calls, made no
Python fallback, sent zero tensor bytes to Rust, and copied no full tensor to
host. The C3-R2 Rust-boundary p95 was 11.6 microseconds and cumulative boundary
span was 138.6 microseconds. Exact GPU-kernel time was not collected because a
profiler run was not authorized; sampler and runner wall spans are not
GPU-kernel duration.

## Residual ownership and memory

The recorded cache was `torch.bfloat16` on `cuda:0`. One residual held
165,838,848 bytes. The adapter retained at most one persistent residual and
one transient snapshot, so the maximum additional residual-sized storage was
331,677,696 bytes; per-block cache count remained zero. The receipt retained
the shape digest
`5bef4951a27aecd6bdfc02eaa7b795e77873f43a50270eca45a71b4b8f0288b7`,
but not the literal shape. `[26992, 3072]` is therefore a derived shape from
the recorded byte count, BF16 element width, and installed H3 hidden width,
not an independently recorded measurement.

System sampling observed peak ComfyUI VRAM 12,459,802,548 bytes, peak NVIDIA
VRAM 11,990,466,560 bytes, device memory 12,884,377,600 bytes, peak
process-tree RSS 47,340,367,872 bytes, peak system-wide used RAM
62,809,526,272 bytes, and peak GPU utilization 100 percent. The ComfyUI peak
left 424,575,052 bytes of device headroom. The run completed without OOM, but
this is a narrow one-run margin and not a general memory guarantee. Allocator
reserved values are allocator accounting, not proof of physical residency.

## Fixed residual-similarity calibration

The CONTROL diagnostics were finite for every candidate, but none met both
frozen thresholds (cosine at least 0.99 and normalized L2 at most 0.20):

| Target/source | Normalized L2 | Cosine | Result |
|---|---:|---:|---|
| 5/4 | 0.210538 | 0.979908 | rejected |
| 6/5 | 0.315677 | 0.952363 | rejected |
| 8/7 | 0.274341 | 0.964360 | rejected |
| 13/12 | 0.238931 | 0.971456 | rejected |
| 16/15 | 0.162921 | 0.986979 | rejected: cosine |
| 17/16 | 0.167788 | 0.986941 | rejected: cosine |

The calibrated schedule was therefore frozen as an empty list. Thresholds,
selection order, quality Gate, and source were not changed after observing
the result. The required minimum for SELECTIVE was two targets, so the work
order prohibited Run B. This is an admission result, not an execution failure.

## Timing and unavailable paired evidence

CONTROL sampler/denoising time was 488.459651 seconds,
submit-to-terminal was 589.181692 seconds, and runner total was 606.164826
seconds. Recorded non-overlapping supporting spans were startup 15.687050,
model/encoder loader boundary 0.692439, prompt 33.781469, video VAE 63.367373,
audio VAE 1.267128, encode 1.588313, collection 0.557203, shutdown 0.001576,
and unattributed 0.762624 seconds. Resource polling itself accumulated
54.480924 seconds of query overhead across 532 samples and is disclosed rather
than silently subtracted.

Because SELECTIVE was correctly not run, actual replay steps, actual omitted
block calls, paired sampler/E2E/runner ratios, SSIM, normalized MAE,
motion-energy ratio, gradient-energy ratio, and visual equivalence comparison
are `not_collected`, not zero. Actual compute reduction is zero because no
selective execution occurred. C3-R1 remains the only identity-bypass pair and
is not overwritten or directly ranked against an absent C3-R2 SELECTIVE
output.

## Safety, fallback, and final decision

CONTROL recorded OOM 0, retry 0, CUDA error 0, NaN/Inf residual 0, black frame
0, corrupt frame 0, external API calls 0, model downloads 0, and third
generation 0. Full Compute remained the active execution path, cache provenance
and one-shot lifecycle were bounded, and removing the repository wrapper
restores the Standard path. No installed source, original workflow, model
asset, C1/C2/C3-R1 ABI, or prior evidence was modified.

The bounded final decision is `C3_R2_RESIDUAL_SIMILARITY_TOO_LOW`. The segment
residual mechanism and memory ownership were validated once in CONTROL, but
zero safe calibrated targets means residual replay, quality preservation,
actual compute reduction, and runtime gain were not tested. Speedup claim,
quality guarantee, visual-equivalence claim, and product promotion remain
zero/false/not proven. Ready transition, merge, and Issue close remain zero.
Any follow-up requires separate approval and must not silently relax the fixed
similarity thresholds or extend cache age.
