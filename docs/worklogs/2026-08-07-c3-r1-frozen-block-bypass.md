# C3-R1 Frozen Replay Selective Block Experiment

Date: 2026-08-07
Status: Draft PR evidence recorded; Issue remains open
Final decision: `C3_R1_LIVE_VETO_OPPORTUNITY_TOO_LOW`

## Product question

Can a precommitted six-step schedule, replayed from immutable C2-R2 Full
Compute evidence, omit real MiniMax H3 `DiTBlock` forwards in an otherwise
matched CONTROL/SELECTIVE pair, reduce execution time, and retain the fixed
quality and safety gates?

This is a frozen-replay mechanism experiment, not a live product policy. The
schedule was fixed before execution and could only be reduced by the live C2
safety gate. It could not add a selective step.

## Repository state and coordination

- Starting `main`: `b9618049cd33693154f4570b7a8f21734e5fa33d`
- Issue: [#65](https://github.com/ksse29077-byte/HIVEFRAME/issues/65)
- Branch: `accel/c3-r1-frozen-replay-block-selective`
- Draft PR: [#66](https://github.com/ksse29077-byte/HIVEFRAME/pull/66)
- Pre-run implementation commit:
  `a1a369abffcb6a61896bc22e5cbe46a55d22f537`
- Prior C3 decision: `C3_POLICY_OPPORTUNITY_TOO_LOW`, unchanged

The existing C3 report, receipt semantics, and rejected Gate were not edited.
C3-R1 is a separate follow-up with a separate schedule, ABI, run pair, and
decision record. The code was committed and pushed before either runtime
submission. No code, threshold, block set, schedule, or Gate changed after a
result was observed.

## Reused evidence and rationale

C0 identified the roughly 486-second sampler span. C1 verified the metadata-
only Rust callback boundary under Full Compute. C2-R2 admitted the exact
`x0.tensors[0]` float32 CUDA signal, a non-blocking fixed sketch, and 23
counterfactually validated Stable candidates with zero contradiction. The
installed H3 source and workflow hashes matched the existing C3 source
admission, so source inspection was not repeated.

The prior C3 policy applied a two-step cooldown and selected only four steps,
yielding 148/1,000 theoretical calls and failing its 18 percent pre-gate. This
separate experiment froze the raw C2-R2 candidates after only first/last
anchors. The resulting six-step ceiling was large enough to permit one actual
paired mechanism test without changing the prior C3 record.

## Frozen policy and opportunity

- Frozen schedule: `[5, 6, 8, 13, 16, 17]`
- Mandatory Full Compute anchors: `[0, 1, 18, 19]`
- Candidate blocks: `12..48`, 37 blocks
- Transformer blocks: 50
- Execution steps: 20
- Total block calls per run: `20 * 50 = 1,000`
- Theoretical bypass ceiling: `6 * 37 = 222`
- Theoretical reduction: `22.2%`
- Required actual reduction: `18%`

The prior C3 two-step cooldown was deliberately not part of this separately
approved frozen-replay contract. This does not revise the prior C3 decision.
Outside the frozen schedule every block remained Full Compute. Inside it, the
live safety gate required a valid source and prediction, at least two Stable
eyes, no Active eye, no global invalidation or overlap conflict, and matching
ABI/workflow/settings/model digests. A failure could only veto bypass and
restore Full Compute.

## Rust ABI and runtime wrapper

C3-R1 introduced separate ABI version 1 metadata structures:

- `C3FrozenBlockPlanObservation`: 208 bytes
- `C3FrozenBlockPlanDirective`: 80 bytes
- at most one Rust call per sampler callback
- zero Rust calls per transformer block
- zero tensor bytes to Rust

The C1 184/76-byte and C2 536/232-byte ABI sizes were unchanged. The
repository-owned wrapper calculated C2 state, evaluated the frozen plan once
per eligible callback, installed block replacements for CONTROL or SELECTIVE,
and restored every patch in `finally`. Identity bypass returned the source-
admitted packed residual container without cloning, host transfer, cache,
residual cache, or new full-size CUDA allocation.

## Model-free validation and pre-run freeze

The focused pre-run checks were completed before the first generation:

- focused Rust C3-R1 tests: 4 passed
- focused Python C3-R1 tests: 9 passed
- Python compile: passed
- PyO3 release check/build: passed
- C1/C2/C3 import and ABI roundtrip: passed
- `cargo fmt --all -- --check`: passed
- `git diff --check`: passed

The PyO3 build emitted the already-understood MSVC linker-artifact warning;
the extension imported and roundtripped successfully. Full Python and Rust
suites were intentionally not repeated under the approved focused-validation
budget. The release extension remained a local ignored build artifact.

## Fixed run contract

CONTROL and SELECTIVE each used a fresh owned loopback ComfyUI process, one
submission, and zero retry. They shared Local MiniMax H3, workflow revision
`video_minimax_h3_t2v@31ab33fdb053`, Sage node count 0, the unchanged private
prompt, seed 101, 864x480, 124 frames, 24 FPS, 20 steps, `simple` scheduler,
`res_multistep` sampler, denoise 1.0, native audio, and H.264 output. The only
execution difference was whether actual block bypass was enabled.

Media, prompt, full logs, callback events, resource samples, private receipts,
and machine paths remain outside Git. Public evidence refers only to
`C3_R1_CONTROL_ARTIFACT_ROOT` and `C3_R1_SELECTIVE_ARTIFACT_ROOT`.

## CONTROL result

The CONTROL run `control-a1a369a-001` succeeded.

| Metric | Result |
|---|---:|
| Submission / retry | 1 / 0 |
| Backend prompt ID | `554e5139-3caa-479c-b9e5-93896a3cbea1` |
| Callback / C2 Rust / C3 Rust | 20 / 20 / 18 |
| Model forwards | 20 |
| Observed block calls | 1,000 |
| Original / bypass block calls | 1,000 / 0 |
| Live-admitted frozen steps | 5, 6, 8, 13, 16, 17 |
| Mapping errors / wrapper failures | 0 / 0 |
| Sampler | 488.375941 s |
| Submit to terminal | 590.059343 s |
| Runner total | 604.950732 s |
| Peak ComfyUI sampled VRAM | 12,461,735,860 bytes |
| Peak NVIDIA sampled VRAM | 12,024,020,992 bytes |
| Peak process-tree RSS | 47,291,817,984 bytes |
| Peak system-used RAM | 62,304,276,480 bytes |
| Peak sampled GPU utilization | 100% |

The model/encoder boundary was 0.759871 seconds, prompt/AV conditioning
33.957528 seconds, video VAE decode 63.887063 seconds, audio VAE decode
1.271964 seconds, encoding 1.781742 seconds, result collection 0.571370
seconds, startup 13.658177 seconds, shutdown 0.001642 seconds, and unattributed
time 0.685434 seconds. These are node/runner wall spans, not GPU-kernel time.

The H.264 output is 864x480, 124/124 decoded frames, 24 FPS, one audio stream,
zero black frames, and zero corrupted frames. Its size is 263,000 bytes and
SHA-256 is
`a18645e8e0bd8942b023781d58edad2d19419e6a0b5402751c0cd296f1d67b8a`.
The private receipt SHA-256 is
`d868cce9ed40c75817fa2f93aff00d1233b0d8a0d281ee00e920ec86afba7226`.

## SELECTIVE result

The SELECTIVE run `selective-a1a369a-001` succeeded.

| Metric | Result |
|---|---:|
| Submission / retry | 1 / 0 |
| Backend prompt ID | `23eaae97-d460-45f6-b553-da8410be3c85` |
| Callback / C2 Rust / C3 Rust | 20 / 20 / 18 |
| Model forwards | 20 |
| Observed block calls | 1,000 |
| Original / bypass block calls | 852 / 148 |
| Actual selective steps | 5, 6, 13, 17 |
| Vetoed frozen steps | 8, 16 |
| Mapping errors / wrapper failures | 0 / 0 |
| Sampler | 423.206033 s |
| Submit to terminal | 524.274434 s |
| Runner total | 537.115170 s |
| Peak ComfyUI sampled VRAM | 12,461,735,860 bytes |
| Peak NVIDIA sampled VRAM | 11,923,357,696 bytes |
| Peak process-tree RSS | 47,041,257,472 bytes |
| Peak system-used RAM | 61,718,671,360 bytes |
| Peak sampled GPU utilization | 100% |

The call-accounting identity is exact: `1,000 - 852 = 148`. Step 8 was
vetoed with one Stable and zero Active eyes; step 16 was vetoed with zero
Stable and two Active eyes. Both had reason `stable_count_low`. No new step was
added. The actual reduction was therefore `148 / 1,000 = 14.8%`, below the
fixed 18 percent Gate.

The model/encoder boundary was 0.728165 seconds, prompt/AV conditioning
33.705888 seconds, video VAE decode 63.313335 seconds, audio VAE decode
1.293806 seconds, encoding 2.002317 seconds, result collection 0.729828
seconds, startup 9.622998 seconds, shutdown 0.001951 seconds, and unattributed
time 2.510850 seconds. Identity bypass itself had 0.2 microsecond p50, 0.3
microsecond p95, 0.9 microsecond maximum, and 29.1 microseconds cumulative
wrapper time.

The H.264 output is 864x480, 124/124 decoded frames, 24 FPS, one audio stream,
zero black frames, and zero corrupted frames. Its size is 492,252 bytes and
SHA-256 is
`25790f8ce91b035de5adbd2d70371cf6f034c8226a799005970088c94a6b0270`.
The private receipt SHA-256 is
`8783c3ba63e163034c1da7cf40b259ac305dc923b0a083be5d45ccf1b0b20aae`.

## Performance and resources

| Comparison | Result | Fixed target | Gate |
|---|---:|---:|---|
| Sampler speedup | 1.153991x | at least 1.20x | fail |
| Submit-to-terminal speedup | 1.125478x | at least 1.15x | fail |
| Runner speedup | 1.126296x | informational | not a product Gate |

The elapsed spans improved in this one pair, but both predeclared performance
targets failed and the actual opportunity floor failed. No speedup claim is
made. SELECTIVE peak NVIDIA sampled VRAM was below CONTROL and therefore
within the fixed CONTROL plus 256 MiB ceiling. Exact allocator peaks and GPU-
kernel duration were not collected; sampled VRAM and wall spans are not
relabelled as those metrics.

## Frame-aligned quality comparison

The 124 aligned frame pairs produced:

| Metric | Result | Fixed Gate | Gate |
|---|---:|---:|---|
| Mean SSIM | 0.805245 | at least 0.90 | fail |
| p05 SSIM | 0.764500 | at least 0.80 | fail |
| Minimum SSIM | 0.742023 | informational | - |
| Frames below SSIM 0.75 | 1.612903% | at most 5% | pass |
| Normalized MAE | 0.055380 | informational | - |
| Motion-energy ratio | 1.834976 | 0.75 to 1.25 | fail |

CONTROL motion energy was 0.786040 and SELECTIVE motion energy 1.442364.
The output hashes differ and `visual_equivalence` is `not_proven`. The quality
Gate failed. This is a lightweight objective comparison, not a user quality
acceptance result.

## Safety and prohibited mechanisms

Across both runs, OOM, retry, CUDA-error, traceback, NaN, black-frame, and
corrupted-frame counts were zero under their recorded checks. C3 moved zero
tensor bytes to Rust, made zero full-tensor host copies, and retained zero
persistent C3 GPU cache entries. It did not use cache reuse, residual cache,
attention/token/latent/whole-step skip, regional compute, partial repair,
Fast Mode, SageAttention, or training.

CONTROL and SELECTIVE were the only two approved generations. There was no
third run, automatic retry, profile sweep, threshold change, or post-result
code modification.

## Final decision and claim boundary

The predeclared decision ordering assigns
`C3_R1_LIVE_VETO_OPPORTUNITY_TOO_LOW` because live safety veto reduced actual
opportunity below 18 percent. The quality and performance target failures are
also preserved and would prevent readiness independently, but they do not
replace the more specific opportunity decision.

This pair verifies once that the repository-owned identity wrapper omitted
148 real `DiTBlock` forward invocations and restored Full Compute on live
veto. It does not prove a safe dynamic product policy, cross-prompt quality,
cross-hardware behavior, cache reuse, regional compute, partial repair, or a
product Fast Mode. Speedup claim and product promotion remain zero. C4 or any
further generation requires separate approval.
