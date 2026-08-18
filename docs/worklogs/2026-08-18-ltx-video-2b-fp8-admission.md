# LTX-Video 0.9.8 Distilled 2B FP8 Admission

Date: 2026-08-18 (Asia/Seoul)

## Product Question And Decision

Can the exact LTX-Video 0.9.8 Distilled 2B FP8 candidate load and complete
one meaningful local I2V admission on RTX 3060 12 GB without OOM, retry,
fallback, external inference, or interruption of shared work?

Final decision:

`LTX_ADMISSION_READY_FOR_FORMAL_H3_COMPARISON`

Disposition: `KEEP_AS_OPTIONAL` pending a separately approved normalized H3
comparison. This decision is not `COMMERCIAL_ENGINE_READY`, does not admit the
installer, and does not establish a quality or speed win over H3.

## Start State

| Item | Value |
|---|---|
| Product reference branch/HEAD | `product/p1-release-alpha` / `e3c8c81ce3972d4ae024cb4df016d3761cf298d4` |
| Research branch/HEAD | `research/engine-competitiveness-gate` / `67f76ca309ce58969765c2bc926e649c7dd05d72` |
| Start branch/HEAD | `research/engine-competitiveness-gate` / `67f76ca309ce58969765c2bc926e649c7dd05d72` |
| Start worktree | clean |
| P1-A2 PR | #95, open Draft, unchanged |
| Engine research Issue/PR | #96 / #97, open, unchanged |
| Duplicate LTX admission work | none |
| New Issue | #98 |
| New branch | `admission/ltx-video-2b-fp8` |
| New Draft PR | #99, base `research/engine-competitiveness-gate` |

The H3 comparison baseline remains 864x480, 124 frames, 24 FPS, 20 steps,
559.990 seconds product E2E, and `LOW_QUALITY_BUT_FUNCTIONAL`. It was not
changed or rerun.

## License And Admission Scope

The admitted model is `Lightricks/LTX-Video` file
`ltxv-2b-0.9.8-distilled-fp8.safetensors` at immutable file revision
`17037c8743450dc873046790dd96fa805ccfaf8d`.

The model uses the LTX Video Open Weights License 0.X. The engineering review
records research and commercial use below the USD 10M annual-revenue threshold
subject to the license; entities at or above the threshold require paid terms.
Redistribution and SaaS require the applicable notices, attribution,
pass-through restrictions, and acceptable-use compliance. The licensor does
not claim rights in outputs, but restricted-use duties remain. Installer
packaging still requires legal review.

The scaled FP8 T5 text encoder is from
`comfyanonymous/flux_text_encoders` revision
`3bcfe977a9a2617a0b9025076030e217795fe028` under Apache-2.0. Neither fixed
download required a login or license-click gate.

## Isolation And Installation Plan

The existing ComfyUI 0.30.2 process already exposed all required LTX core
nodes. It was reused at loopback only because a second process would compete
with about 10 GB of initially resident H3 GPU memory. The shared queue was
read twice before installation and twice again immediately before submission;
all four snapshots were running zero and pending zero.

No ComfyUI source, custom node, Python package, environment, launcher, H3
workflow, or H3 checkpoint was changed. The two new files were placed in the
standard isolated model-type directories:

- `<comfyui-root>/models/checkpoints`
- `<comfyui-root>/models/text_encoders`

Rollback is to wait for an idle queue and remove only the two exact LTX files
and the LTX-only output/workflow artifacts. The original H3 files remain in
their existing separate asset root.

## Download Evidence

| File | Revision | Bytes | SHA-256 | UTC start -> complete |
|---|---|---:|---|---|
| `ltxv-2b-0.9.8-distilled-fp8.safetensors` | `17037c8743450dc873046790dd96fa805ccfaf8d` | 4,461,695,684 | `d6d8fa8ed3a98346787c2503ac80fb5d7cebcf80e356b79a2ba361fbadf97e15` | 09:25:54.466 -> 09:29:29.850 |
| `t5xxl_fp8_e4m3fn_scaled.safetensors` | `3bcfe977a9a2617a0b9025076030e217795fe028` | 5,157,348,688 | `a498f0485dc9536735258018417c3fd7758dc3bccc0a645feaa472b34955557a` | 09:29:29.853 -> 09:32:46.299 |

Total payload was 9,619,044,372 bytes (about 8.96 GiB). C: had 540.61 GiB
free before installation. Files were downloaded sequentially to `.partial`
names, promoted only after each transfer completed, and verified once by exact
size and SHA-256 before submission. No partial file remained. Curl retry was
not enabled. The official license snapshot remains outside Git with private
installation evidence.

## Runtime And Fixed Admission Profile

| Field | Value |
|---|---|
| ComfyUI | 0.30.2, `dec5d9450a5290bcf63430409ea41018e67f41c3` |
| Python / PyTorch / CUDA | 3.13.12 / 2.12.1+cu130 / 13.0 |
| GPU / driver | NVIDIA GeForce RTX 3060 12 GB / 610.88 |
| Mode | I2V |
| Input | existing private P1 image; SHA-256 `493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411` |
| Privacy | local dog image; no person; file and local path remain outside Git |
| Prompt | private runtime environment input; SHA-256 `e1c86816d98d8485e1ba98e246f2eff817df70c37339d312d958d60ee00d7da3` |
| Negative prompt | private runtime environment input; SHA-256 `22185ed52e438fd1539cec2c9579ed4ee7d4336dfcd27ff8c425675c39048fd2` |
| Seed | 101 |
| Resolution | 768x512 |
| Frames / FPS / duration | 33 / 24 / 1.375 seconds |
| Steps | 8 |
| Sampler / scheduler | Euler / native `LTXVScheduler` |
| Scheduler values | max shift 2.05, base shift 0.95, stretch true, terminal 0.1 |
| Guidance / STG | 1.0 / disabled |
| Precision | FP8 LTX checkpoint and FP8 scaled T5 |
| CPU offload | ComfyUI automatic model management; no explicit offload node |
| VAE | embedded in the official single-file checkpoint |
| Expected VRAM | official directional 8-10 GB |
| Expected host RAM / runtime | UNKNOWN / UNKNOWN before execution |
| Temperature | cold LTX model load; shared ComfyUI process already running |

This is a meaningful minimum admission, not a competitive H3 profile. It did
not use 1 step, a meaningless frame count, an upscaler, frame interpolation,
TeaCache, Sage, or a lowered H3 setting.

## Lifecycle And Counters

Observed lifecycle:

```text
queued -> running -> succeeded
```

| Counter | Value |
|---|---:|
| Product or test jobs created | 1 |
| Backend submissions | 1 |
| GPU executions started | 1 |
| Completed generations | 1 |
| Retry | 0 |
| Fallback | 0 |
| External inference API calls | 0 |
| External job terminations | 0 |
| OOM | 0 |
| Wan2.2 downloads/runs | 0 / 0 |

Only the private input load node was reported as cached. The LTX model,
conditioning, sampling, VAE decode, and video encode were not reported cached.

## Timing And Resources

| Measurement | Result | Method |
|---|---:|---|
| Queue wait / submit -> running | 0.004045 s | loopback queue observation |
| Running -> terminal | 10.895037 s | queue/history monotonic observation |
| Submit -> terminal | 10.899082 s | loopback monotonic observation |
| Total Admission E2E | 18.553888 s | includes file verification and result integrity flow |
| Model loading only | UNKNOWN | not separately exposed by Comfy HTTP lifecycle |
| Output creation only | UNKNOWN | not separately exposed |
| Video encoding only | UNKNOWN | not separately exposed |
| Peak NVIDIA used VRAM | 11,207 MiB (10.944 GiB) | `nvidia-smi`, 0.5-second sampling |
| Peak Comfy/system VRAM used | 12,290,852,936 bytes (11.447 GiB) | Comfy `/system_stats` |
| Peak system-wide used RAM | 43,720,257,536 bytes (40.718 GiB) | total minus free in `/system_stats` |
| Peak / mean GPU utilization | 100% / 46.5% | `nvidia-smi`, 20 samples |

The proposed 420/559.990/300/180-second competitiveness values were not used
as Admission pass criteria. The 10.899-second result is not compared directly
to H3 because frame count, duration, resolution, model, and workflow differ.

## Output Integrity

| Gate | Result |
|---|---|
| Container / codec | MP4 / H.264 |
| Resolution | 768x512 |
| Decoded frames | 33/33 |
| FPS / duration | 24.0 / 1.375 seconds |
| Audio streams | 0; expected for this LTX-Video profile |
| Black frames | 0 |
| Corrupt/decode-error frames | 0 |
| Adjacent exact duplicate frames | 0; ratio 0.0 |
| File bytes | 133,324 |
| Local result HTTP | 200 |
| Downloadable / playable | true / true |
| Output SHA-256 | `8ed7ff72fde4a17f328c87a7ea52b2e50495c6de753f100701089a1a4b59f10f` |
| Integrity Gate | PASS |

The generated MP4, contact sheet, prompt, full workflow, local paths, runtime
receipt, and license snapshot remain outside Git.

## Conservative Visual Review

Five fixed frames (0, 8, 16, 24, 32) were inspected.

| Dimension | Admission observation |
|---|---|
| Input identity | PASS; the small white dog and protective cone remain recognizable |
| Face stability | PASS in sampled frames; eyes, nose, muzzle, and head shape remain coherent |
| Hands | NOT_APPLICABLE; no human hands in the private input |
| Motion naturalness | Promising; the head turns gradually from front toward the side |
| Background stability | No obvious large bed or pillow displacement in sampled frames |
| Temporal flicker | No obvious sampled-frame discontinuity; full formal review still required |
| Object distortion | No catastrophic dog or cone deformation observed |
| Prompt adherence | PASS for subtle head movement and fixed-camera intent |
| Overall detail | Coherent fur and facial detail at the admission profile |

Admission visual grade: `PROMISING_FOR_FORMAL_GATE`.

Comparison status: `FORMAL_NORMALIZED_COMPARISON_REQUIRED`. The short output
does not prove H3 parity, H3 superiority, commercial quality, or stable
five-second temporal behavior.

## H3 Preservation And Safety

After Admission, the shared queue returned to running zero and pending zero.
The product endpoint remained HTTP 200 with the Local H3 backend ready and
generation enabled. The four H3 model files retained their pre-run byte sizes
and modification times. ComfyUI remained at the same commit with a clean Git
worktree. No H3 workflow, checkpoint, custom node, package, user job, or
external task was modified, deleted, cancelled, or interrupted.

## Verification

- Focused LTX contract tests: 8/8 passed before the run and again after the
  final privacy/deadline guard change.
- Python AST parse: PASS.
- Exact model, text-encoder, and private-input SHA-256: PASS.
- Required native Comfy nodes and model discovery: PASS.
- Double idle Gate immediately before submit: PASS.
- One local core I2V workflow: PASS.
- Full Python/Rust suites: skipped; this bounded adapter addition does not
  change the common runtime or release candidate.
- Separate Python bytecode write check: unavailable because the desktop
  sandbox denied creation of a new cache directory; import and tests passed.

## Git And Artifact Boundary

Tracked changes contain only the admission contract, runner, focused tests,
model/download ledger records, execution-context/system-map status, and this
worklog. Weights, private input, prompt text, generated video, contact sheet,
full private receipt, and installation evidence are not tracked.

- Issue: #98
- Branch: `admission/ltx-video-2b-fp8`
- Draft PR: #99
- Contract implementation commit: `03d6cc3`
- Ready: no
- Merge: no
- Diagram impact: updated; LTX changes from inactive to `verified_once`
  admission evidence, while the product path remains H3.

## Final Boundary And Next Approval

The exact Admission requirements passed: install, model load, GPU start,
OOM-free completion, retry/fallback/external API/external termination zero,
and output integrity PASS.

The work stops here. Wan2.2 download/install/run, a second LTX generation,
warm run, five-second LTX output, normalized H3 comparison, product backend
integration, commercial promotion, and installer work all require separate
user approval.
