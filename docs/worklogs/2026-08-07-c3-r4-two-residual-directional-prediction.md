# C3-R4 Two-Residual Directional Prediction

Status: Draft evidence; `C3_R4_DIRECTIONAL_SIMILARITY_TOO_LOW`

Family disposition: `RESIDUAL_PREDICTOR_FAMILY_FALLBACK_ONLY`

## Purpose and constitutional boundary

C3-R4 asked whether two consecutive **actual Full Compute** H3 segment
residuals carry a useful tensor-space direction for predicting the next
residual without weakening the C3-R2 Quality Gate. The mechanism was frozen as

`R_hat_t(alpha) = R_(t-1) + alpha * (R_(t-1) - R_(t-2))`.

This was the last bounded residual-predictor revision. Quality remained ahead
of runtime, `UNCERTAIN` remained Full Compute, and every invalid source or
policy state retained a Full Compute fallback. Mechanism evidence was kept
separate from product evidence: product promotion and product acceleration
readiness were fixed false. The starting `main` was
`d9371aa3e009d446299ebb5cb95fd53f159b978d`; Issue #72, branch
`accel/c3-r4-h3-two-residual-directional-prediction`, and Draft PR #73 isolate
the work. C3-R2 and C3-R3 reports, receipts, thresholds, and decisions were
not edited.

## Predeclared mechanism and Gate

Commit `6ff07264b65279f716c9bb36d65b58e74396ce13` fixed the code, tests,
formula, memory contract, source contract, run budget, and decision rules
before any C3-R4 Generation. Alpha `0.0` was the raw previous-residual
diagnostic. One global alpha had to be selected from the immutable non-zero
grid `[-0.50, -0.25, -0.125, 0.125, 0.25, 0.50, 0.75, 1.00]` using, in
order: maximum spaced admitted count, maximum selected minimum cosine,
minimum selected maximum normalized L2, minimum absolute alpha, and minimum
numeric alpha. Per-target fitting, continuous search, and post-result tuning
were prohibited.

Each non-zero candidate had to satisfy all four conditions: cosine at least
`0.99`, normalized residual L2 at most `0.20`, cosine no worse than raw, and
L2 no worse than raw. Frozen target candidates were steps 5, 6, 8, 13, 16,
and 17; anchors remained 0, 1, 18, and 19. Deterministic spacing required a
difference of at least three, and at least two spaced targets were required
before a SELECTIVE run. Replayed or predicted residuals could never seed a
later prediction.

## Exact metrics and model-free verification

For `A=R_(t-2)`, `B=R_(t-1)`, `D=B-A`, `Y=R_t`, and `P=B+alpha D`, six
scalar sufficient statistics (`A·A`, `B·B`, `Y·Y`, `A·B`, `A·Y`, `B·Y`)
produce exact cosine and the unchanged C3-R2
`||Y-P||_2 / ||P||_2`. CONTROL did not allocate eight full predicted tensors;
bounded FP32 chunks accumulated small FP64 scalars. Model-free direct-vector
and sufficient-statistic results agreed to 12 decimal places for raw and all
eight alpha values.

Focused verification passed:

- C3-R3 plus C3-R4 Python regression: 16/16.
- C3-R3 generic Rust admission regression: 3/3.
- Python compile, Cargo format, workspace check, and release build.
- PyO3 extension import and the existing tensor-free correction ABI roundtrip.
- CONTROL 1,000-call accounting, SELECTIVE model-free 37-call replay,
  two-step re-seed, invalid-source fail-open, guider cloning, and wrapper
  restoration.

The Rust Core ABI was reused as `c3-r3.correction-plan.1` without a semantic
change. Generic Core received only scalar metadata and digests. H3-specific
packed residual tensors, blocks 12 through 48, CUDA reductions, history
rotation, and replay application remained in the H3 adapter. Tensor bytes to
Rust and per-block Rust calls remained zero.

## Source and memory admission

The installed H3 source SHA-256 remained
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`.
The approved workflow remained
`video_minimax_h3_t2v@31ab33fdb053`. Its fixed profile remained seed 101,
864x480, 124 frames, 24 FPS, 20 steps, `simple`, `res_multistep`, denoise 1.0,
native audio, H.264, and Sage disabled.

One residual occupies 165,838,848 bytes. C3-R4 allowed at most two persistent
actual residuals, zero persistent direction tensors, zero persistent predicted
residuals, and one transient predicted residual only during admitted replay.
Using the immutable C3-R3 sampled peak of 12,458,721,204 bytes on a
12,884,377,600-byte device, the additional persistent residual left a
projected 259,817,548-byte headroom. Admission passed, but this narrow margin
is one-run evidence and not a general OOM guarantee.

## CONTROL execution

Exactly one fresh-process `CONTROL_DIRECTIONAL_SHADOW` Generation ran. It used
Full Compute for all blocks and replayed nothing. It completed with one
submission, retry 0, OOM 0, and CUDA-error signature count 0. The output was
H.264, 864x480, 124/124 decoded frames at 24 FPS with one audio stream, no
black frame, and no corrupt frame. The output was 263,075 bytes with SHA-256
`a06b7b667234220f8f7555abbf895709f4ccea002c0e0114c83d5567417c2a77`.
Private prompt, media, raw tensors, receipts, logs, and paths remain outside
Git.

Execution accounting was exact: 20 model forwards, 1,000 original block
calls, 20 actual residual captures, zero replay calls, zero mapping errors,
and zero wrapper failures. C2 callback/Rust/Full Compute counts were
20/20/20. C3-R4 made 18 Rust metadata calls; boundary p95 and cumulative
spans were 11.6 microseconds and 153.9 microseconds. Rust-policy p95 and sum
were 2.0 microseconds and 18.2 microseconds. Full-tensor host-copy bytes,
tensor bytes to Rust, and full-sized FP32 materializations were zero.

Observed predictor ownership reached two persistent residuals and three live
predictor-owned residual-sized buffers while capturing/rotating history;
direction and persistent prediction counts remained zero. Because CONTROL did
not apply a prediction, its transient predicted residual count was zero. The
maximum observed additional residual-sized GPU bytes were 497,516,544.
ComfyUI and NVIDIA sampled peaks were 12,457,869,236 and 12,024,020,992 bytes.
Process-tree RSS peaked at 46,721,306,624 bytes and system-wide used RAM at
62,626,402,304 bytes. The external runner cannot safely read the internal
PyTorch allocator peak, so that value is `null/unavailable`, not zero.

Sampler, submit-to-terminal, and runner spans were 488.865380, 589.375047,
and 600.256371 seconds. Other observed phase spans were 9.626010 seconds for
runtime startup, 0.758088 for loader nodes, 33.750541 for prompt
conditioning, 63.206449 for video VAE decode, 1.276822 for audio VAE decode,
1.495469 for encoding, 0.579298 for result collection, and 0.696841
unattributed. Exact GPU-kernel duration was not collected because no profiler
run was authorized.

Directional scalar statistics summed to 0.545473 seconds across the six
frozen targets; alpha evaluation summed to 0.000164 seconds and history
rotation to 0.000246 seconds. Residual-capture spans summed to 144.676384
seconds, but they include GPU synchronization and overlap asynchronous work;
they are not additive with sampler or original-block spans.

## Calibration result

All 48 non-zero target/alpha diagnostics were finite. No value passed the
unchanged threshold pair. Only target 8 at alpha -0.25 and -0.125 improved
both raw metrics, but both remained far below the cosine and L2 thresholds.
The deterministic tie-break selected global alpha `-0.125` after every alpha
had zero spaced admitted targets. This diagnostic selection conferred no
execution authority. The calibrated target list was empty.

Raw `(cosine, normalized L2)` values were:

| target | raw cosine | raw L2 | best relevant observation |
|---:|---:|---:|---|
| 5 | 0.978682 | 0.215555 | alpha 0.125 lowers L2 but lowers cosine |
| 6 | 0.953835 | 0.310717 | no threshold or raw-non-regression pass |
| 8 | 0.963325 | 0.278479 | alpha -0.25/-0.125 improve raw but miss both thresholds |
| 13 | 0.970223 | 0.244211 | no threshold or raw-non-regression pass |
| 16 | 0.987685 | 0.158645 | L2 passes raw; every alpha still misses cosine 0.99 |
| 17 | 0.986640 | 0.169628 | L2 passes raw; every alpha still misses cosine 0.99 |

The complete candidate-by-alpha matrix is preserved in
`knowledge/h3/c3_r4_two_residual_directional_prediction.yaml`. The raw values
from this independent run are not bitwise identical to prior C3-R2/R3 raw
values despite matching metric definitions and source/workflow hashes. The
cause is `not_attributed`; the difference was not used to alter the Gate or
rewrite prior evidence.

## Decision and family disposition

With zero spaced calibrated targets against the required minimum of two,
SELECTIVE Generation was prohibited. SELECTIVE count, third Generation count,
retry count, external API calls, and model downloads are all zero. Replay
steps, omitted block calls, paired quality metrics, runtime ratios, visual
equivalence, and actual compute reduction are `null/not_collected`, not zero.
The activation NaN/Inf scan was not collected; output decode and runtime error
gates passed.

The final technical decision is
`C3_R4_DIRECTIONAL_SIMILARITY_TOO_LOW`. Under the predeclared terminal rule,
the residual-predictor family disposition is
`RESIDUAL_PREDICTOR_FAMILY_FALLBACK_ONLY`: no C3-R5, alpha-grid expansion,
threshold relaxation, polynomial/per-step/learned predictor, or automatic
next experiment is authorized. Full Compute remains the default and safe
fallback. Speedup claim, quality guarantee, product promotion, and product
acceleration readiness remain zero or false.

Diagram impact: `none`. This bounded adapter experiment introduced no new
long-lived product component, ownership boundary, or admitted data flow; the
Living System Map therefore was not changed.

## Publication state

Issue #72 remains open. Draft PR #73 remains Draft. Ready transition, merge,
and Issue closure are zero. The implementation and evidence will use at most
the two predeclared commits.
