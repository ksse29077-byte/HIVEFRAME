# C2 Local H3 Compound Eye Shadow Policy

Date: 2026-08-06
Status: Draft PR C2-R1 evidence recorded; Issue remains open
Final decision: `C2_SHADOW_REVISE_ONCE`

## Product question

Can one real Local H3 sampler callback expose a bounded `x0` signal from which a five-eye `overlap_2x2` topology can propose conservative next-step `STABLE`, `ACTIVE`, and `UNCERTAIN` states while the actual workflow remains Standard Full Compute?

The initial approved run answered only the plain-tensor signal-admission part:
no. The callback executed 20 times, but its `x0` object was not a
`torch.Tensor`. That initial result remains immutable evidence below. A later
read-only source investigation identified one exact container path, and C2-R1
tested only that path under a separate one-run approval.

## Repository state

- Starting main: `4635f4750553a24037793e6ebbfa077f06d2474a`
- C1 merge: PR #60, normal merge commit `4635f4750553a24037793e6ebbfa077f06d2474a`
- Issue: [#61](https://github.com/ksse29077-byte/HIVEFRAME/issues/61)
- Branch: `core/c2-h3-compound-eye-shadow`
- Draft PR: [#62](https://github.com/ksse29077-byte/HIVEFRAME/pull/62)
- Pre-measurement implementation commit: `cd4e5cd8a8016c599657bf5ab967a31d53086390`
- Worktree was clean before the single runtime submission.

## Reused C1 evidence

C1's 20/20 callback/Rust/Full Compute regression, 38.1 microsecond boundary p95, 2.592 millisecond conservative policy span, and fail-open contract were reused. C1 was not rerun and its ABI, node, receipt, knowledge, and historical failure evidence were not edited.

## Source inspection

The installed ComfyUI 0.30.2 source was inspected read-only before implementation. `latent_preview.prepare_callback` constructs `callback(step, x0, x, total_steps)`, and the sampler calls it with its `denoised` object as `x0`. The relevant source files matched their recorded SHA-256 values in the private receipt. Public documents use `<comfyui-root>` rather than a machine path.

The actual callback object then failed `isinstance(x0, torch.Tensor)` on all 20 callbacks. Therefore:

- x0 shape: `null/not_collected` (`x0_not_tensor`)
- x0 dtype: `null/not_collected` (`x0_not_tensor`)
- x0 device: `null/not_collected` (`x0_not_tensor`)
- substitution with `x`, nested members, RGB, VAE preview, prompt state, QKV, or weights: 0

## Predeclared topology and sketch

- EyeTopology: one global low-resolution eye plus four fixed overlapping regional eyes (`overlap_2x2`), total 5
- ExecutionTopology: `full_compute`
- Global eye write scope: none
- Regional write scopes: fixed quadrants with one 4x4-sketch-cell halo
- Sketch source: only `x0`
- Reduction: batch/channel/temporal mean, mean absolute value, and RMS; adaptive spatial 4x4
- Fixed values: 4 x 4 x 3 = 48
- Quantization: signed int32, scale 4096
- Maximum admitted host transfer: one 48-float block (192 bytes) per callback
- Tensor bytes to Rust: 0
- Persistent GPU state: 0

The scale and thresholds were committed before the actual run and were not changed afterward:

| Rule | Fixed ppm |
|---|---:|
| Stable delta limit | 20,000 |
| Active delta limit | 80,000 |
| Global invalidation limit | 150,000 |
| Stable validation limit | 30,000 |
| Local/global ratio limit | 950,000 |

The first two callbacks could not propose stable state. A candidate at callback N was to be validated only at N+1, and the last callback was excluded. Stable/active overlap conflict escalated the stable eye to uncertain. Global invalidation prohibited all stable candidates.

## C2 ABI and fail-open

`CompoundEyeShadowObservation` ABI v1 is 536 bytes and `CompoundEyeShadowDirective` is 232 bytes. The PyO3 boundary admits two fixed 48-int sketches and fixed digests/flags only. It permits one Rust call per normal callback and only actual `FULL_COMPUTE` or `ESCALATE_FULL_COMPUTE` decisions. All skip, reuse, and partial-compute counters are structurally zero.

The runtime wrapper used module-local concurrency state, preserved the original callback arguments, and always delegated to Standard H3. Signal rejection was recorded as fail-open without calling Rust. That behavior kept actual H3 Full Compute but made the shadow gate ineligible.

## Focused model-free verification

- Rust C2 tests: 7 passed
- Rust workspace check: passed
- C2 plus C1 focused Python tests: 20 passed
- Actual PyO3 C2 ABI roundtrip: passed
- Python compile for C2 files: passed
- `cargo fmt --all -- --check`: passed
- `git diff --check`: passed before the first commit

The focused tests cover fixed sizes, determinism, five-eye routing, first/warm-up uncertainty, synthetic stable/active/uncertain paths, global invalidation, overlap conflict, invalid ABI/non-finite fail-open, 48-value sketching, one-call boundary, unchanged callback arguments, next-step validation, missing observations, last-step exclusion, fixed quantization, zero tensor FFI, C1 preservation, workflow patching, Gate outcomes, and C3 candidate uniqueness.

## Actual generation

Exactly one owned loopback Standard H3 workflow was submitted. No retry occurred.

| Item | Result |
|---|---:|
| Generation submissions | 1 |
| Retry | 0 |
| Callback count | 20 |
| Rust call count | 0 |
| Full Compute fail-open callbacks | 20 |
| Signal failures | 20 x `x0_not_tensor` |
| Stable candidates | 0 |
| Validated stable | 0 |
| Contradicted stable | 0 |
| Sketch host transfers | 0 |
| Full tensor host copies | 0 |
| Raw tensor Rust transfers | 0 |
| Actual skip/cache/partial | 0 / 0 / 0 |
| Sage nodes | 0 |
| OOM / retry / CUDA error | 0 / 0 / 0 |

The runtime succeeded because signal rejection did not change actual execution. It is not a successful C2 shadow admission.

## Timing and memory

| Metric | Result | Meaning |
|---|---:|---|
| Runtime startup | 13.646798 s | owned process launch to API ready |
| Submit to terminal | 585.362693 s | one workflow submission |
| Sampler node | 486.528057 s | includes model materialization/orchestration; not kernel time |
| Video VAE decode | 63.832046 s | WebSocket node span |
| Audio VAE decode | 1.284768 s | WebSocket node span |
| Encoding | 1.706291 s | create/save video spans |
| Runner total | 600.382758 s | runner entry through owned runtime stop |
| Shadow p95 | 0 s | no sketch or Rust work admitted; not performance evidence |
| Rust boundary p95 | `null/not_collected` | Rust call count 0 |
| Cumulative shadow | 0 s | no signal admitted; not evidence of a cheap admitted path |
| Peak NVIDIA sampled VRAM | 11,923,357,696 bytes | one-second system sampling |
| Peak process-tree RSS | 46,995,505,152 bytes | aggregate process-tree sampling |
| Peak system-wide used RAM | 62,728,011,776 bytes | system-wide sample |
| Estimated retained host shadow state | 30,972 bytes | bounded receipt/event estimate |
| GPU kernel time | `null/not_collected` | profiler was not authorized |

## Output integrity

The repository-external artifact at logical root `C2_ARTIFACT_ROOT` is H.264, 864 x 480, 124/124 decoded frames, 24 FPS, one audio stream, zero black frames, and zero corrupted frames. Size is 262,853 bytes; SHA-256 is `1ae93b511a7998a25f4984850192e6ae11ed1bafadcdfc1f2d4a6a8954227534`.

Raw prompt, video, runtime log, callback events, resource samples, private receipts, actual paths, and build binaries remain outside Git.

## Gate and C3 handoff

The final Gate is `C2_SHADOW_SIGNAL_NOT_ADMITTED`. Stable coverage and contradictions are not measurable because no sketch entered the policy. The exact C3 selection is `no_c3_admission`; see [the C3 handoff](../design/h3-c3-selective-compute-handoff.md).

No safe hook is selected to reduce the 486-second sampler phase. Rust controlled no GPU work, and metadata speed alone has no product value. Standard fallback is immediate, but RTX 3060 or other-backend C3 trials and partial repair are not admitted.

## Claim boundary and omissions

This evidence verifies once that the repository wrapper can fail open while one real Standard H3 video completes, and that the actual callback object does not meet the predeclared plain-tensor signal contract. It does not verify Compound Eye state quality, selective compute, cache reuse, compute reduction, speedup, VRAM reduction, partial repair, or a product default.

C1, M0, M1, Sage, quality, profiler, alternate signal, alternate topology, threshold sweep, second generation, Fast Mode, and training runs were omitted. Thresholds were not relaxed after seeing the result. H3 knowledge remains `verified_once`, never `promoted`.

## C2-R1 exact container adapter regression

The read-only C2-S0 investigation established the exact public source contract
`comfy.nested_tensor.NestedTensor -> tensors[0]`. No recursive tensor search,
`x` substitution, private attribute, RGB/VAE preview, QKV, model weight, or
prompt state was admitted. The third branch commit fixed that one path and
passed Python compilation, 14/14 focused model-free tests, diff checking,
secret/path scanning, and binary scanning before a normal push. The model-free
test path loaded no model and executed no CUDA work.

Exactly one C2-R1 owned-runtime workflow was then submitted. There was no
retry or additional generation. The structural adapter admitted all 20
callbacks and observed:

- container: `comfy.nested_tensor.NestedTensor`, two ordered tensors
- video path: `x0.tensors[0]`
- video layout: `[B,C,T,H,W]`
- video shape: `[1,24,37,30,54]`
- observed dtype/device: `torch.float32` / `cuda`
- Rust calls / Full Compute directives: 20 / 20
- escalation / fallback: 0 / 0
- raw tensor bytes to Rust / full-tensor host copies: 0 / 0
- sketch transfers: 20 x 192 bytes = 3,840 bytes
- skip / cache reuse / partial compute: 0 / 0 / 0

The actual dtype contradicted the committed post-run source gate, which
required `torch.bfloat16`. Structural extraction consequently reached Rust,
while `source_x0_admitted` was false in the final gate. Because contract
mismatch was supposed to stop Rust before evaluation, this is a clear
wrapper/admission-contract defect. The result is not reinterpreted as a
successful admission and the code was not changed after the run.

### Stable counterfactual validation

The first 19 callbacks provided 76 eligible regional eye-steps. Their
candidate counts were 25 stable, 4 active, and 47 uncertain. All 25 stable
candidates were checked against the next actual Full Compute callback and all
25 validated; contradicted and unvalidated counts were both zero. Stable
coverage was 32.894737% and contradiction rate was 0%. One global invalidation
and zero overlap conflicts were observed. These figures are one-run shadow
evidence only, not authorization to skip work.

### C2-R1 timing and memory

| Metric | p50 | p95 | max |
|---|---:|---:|---:|
| Sketch reduction enqueue | 0.000165 s | 0.000903 s | 0.058090 s |
| GPU-to-host 48-float transfer | 7.139598 s | 7.146729 s | 7.147384 s |
| Host quantization | 0.000053 s | 0.000063 s | 0.000066 s |
| Observation build | 0.000007 s | 0.000010 s | 0.000010 s |
| Rust boundary | 0.000030 s | 0.000038 s | 0.001073 s |
| Rust policy | 0.000004 s | 0.000005 s | 0.000640 s |
| Total shadow callback | 7.139903 s | 7.147004 s | 7.147646 s |

The cumulative shadow span was 135.699001 seconds, above the fixed 4.866-second
limit. Total-shadow p95 also exceeded the fixed 0.1118-second limit. Rust
boundary p95 passed its 0.001-second limit, and submit-to-terminal was
588.591221 seconds, within 616.336 seconds. The 48-value `.to(cpu)` operation
caused a blocking device synchronization and dominates the shadow cost; it is
not GPU-kernel duration.

Persistent shadow state was estimated as 30,972 host bytes, 0 Rust-retained
bytes, and 0 GPU-retained bytes. Peak NVIDIA sampled VRAM was 11,990,466,560
bytes and peak process-tree RSS was 47,056,539,648 bytes. Exact allocator and
GPU-kernel durations remain unavailable because no profiler run was authorized.

### Output and decision

The private H.264 output is 864x480, 124/124 decoded frames, 24 FPS, one audio
stream, zero black or corrupted frames, and 262,853 bytes. Its SHA-256 is
`41bfa11d705f4352417810aa2dc36edad522bd0acd47b2f37804c3be1785bfef`.
OOM, retry, CUDA-error, NaN, traceback, and execution-error signatures were all
zero under the recorded checks. Runner total was 600.557512 seconds, sampler
487.735403 seconds, and video VAE decode 63.563118 seconds. No speedup is
claimed from a single wall-clock result.

The runner emitted `C2_SHADOW_SIGNAL_NOT_ADMITTED`; the evidence review assigns
the more specific bounded result `C2_SHADOW_REVISE_ONCE` because the committed
dtype gate and pre-Rust adapter enforcement disagree. The transformer-block
hook returned by the counterfactual selector is candidate-only and is not C3
admission. Final C3 selection remains `no_c3_admission`. A separately approved
revision would need to predeclare the actual float32 callback contract and a
nonblocking/device-resident sketch path before any further generation.

Actual skip, cache reuse, partial compute, speedup claim, product promotion,
Ready transition, merge, and Issue closure remain zero. Private prompt, media,
receipts, raw events, complete logs, and machine paths remain outside Git.
