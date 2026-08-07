# C3-R2 — Quality-Preserving Segment Residual Replay

Status: implementation and pre-runtime validation in progress  
Starting main: `5c9155cd0391e7067e540bad2e6e9ce57f31bbe9`  
Issue: [#67](https://github.com/ksse29077-byte/HIVEFRAME/issues/67)  
Branch: `accel/c3-r2-h3-segment-residual-reuse`

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

Runtime results, calibrated schedule, resource/quality evidence, claim
boundary, and final decision will be appended only after the frozen source is
committed and the authorized execution gates are applied. Private videos,
prompt, raw tensors/residuals, detailed receipts/logs, and visual-review assets
remain outside Git under logical root `C3_R2_ARTIFACT_ROOT`.
