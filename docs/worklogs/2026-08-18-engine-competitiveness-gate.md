# ENGINE_COMPETITIVENESS_GATE_BEFORE_INSTALLER

Date: 2026-08-18 (Asia/Seoul)

## Purpose

Determine whether a public, locally runnable T2V/I2V model or runtime is a
credible RTX 3060 12 GB successor or complement to the current H3 Standard
product path before installer work begins. This is a source-readonly research
task. It does not authorize a model download, installation, ComfyUI change, or
video generation.

The product question is:

> On RTX 3060 12 GB, is there a locally runnable T2V/I2V model or runtime with
> a better quality, generation-time, and VRAM combination than H3 Standard?

## Start State And Duplicate Gate

- Start branch: `product/p1-release-alpha`
- Start/local/remote/PR #95 HEAD:
  `e3c8c81ce3972d4ae024cb4df016d3761cf298d4`
- Start worktree: clean
- PR #95: open Draft, base `main`
- Research issue: #96
- Research branch: `research/engine-competitiveness-gate`
- PR #91, #92, #94, and #95 were inspected read-only and were not changed.
- Repository issues, PRs, branches, and worklogs contained no existing
  `ENGINE_COMPETITIVENESS_GATE` contract or equivalent candidate decision.
- No user file or running ComfyUI task was stopped.

## Frozen H3 Standard Baseline

The P1-A2 receipt is the comparison baseline. No H3 setting was changed.

| Field | Baseline |
|---|---|
| Product path | local HIVEFRAME -> loopback ComfyUI |
| Backend key | `minimax_h3_comfyui_local` |
| Workflow | `video_minimax_h3_t2v@31ab33fdb053` |
| Diffusion checkpoint | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| Video/audio VAE | FP16 / FP32 |
| Precision/offload | quantized components as named; explicit offload node UNKNOWN |
| Input | fixed local I2V image and prompt |
| Output | 864x480, 124 frames, 24 FPS, about 5 seconds |
| Sampling | 20 steps, `res_multistep`, `simple`, denoise 1.0, seed 101 |
| Guidance | fixed P1-A2 workflow value; numeric value UNKNOWN in this audit |
| Attention | native; Sage disabled |
| Product E2E | 559.990 seconds |
| Backend running -> terminal | 559.313 seconds |
| Backend submit -> terminal | 559.391 seconds |
| Integrity | H.264 MP4, 124/124 frames, audio present, zero black/corrupt frames |
| Control behavior | retry 0, fallback 0, external API 0 |
| Visual product rating | `LOW_QUALITY_BUT_FUNCTIONAL` |

The backend contract is loopback ComfyUI only. It uploads the input, submits a
prompt, polls queue/history, and fetches the result. The product busy guard
must observe an idle queue twice and must never interrupt foreign work. A new
engine must preserve queued/running/succeeded/failed/cancelled state mapping,
the result/receipt contract, external API zero, retry zero, and fallback zero.

Earlier evidence is context, not a new candidate run:

- H3 plus Sage reduced backend submit time from 586.973 to 486.247 seconds
  (17.160%), but missed its predeclared 1.3x gate and did not establish visual
  parity. Existing decision: `F0_SAGE_NO_GAIN`.
- The 480x288, 8-step H3 preview took about 156.86 seconds but is an optional
  low-resolution path without quality parity. It is not eligible evidence for
  this gate.
- Wan2.1 M0 remains a frozen, incomplete historical comparator. It is not
  rerun or reinterpreted here.

## Evidence Rules

- `A`: same RTX 3060 12 GB measurement.
- `B`: measurement on a materially similar 12 GB GPU.
- `C`: measurement on a higher-tier GPU or a non-identical workload; useful
  only as directional evidence.
- `D`: promotional, incomplete, community-only, or otherwise insufficient.
- A time measured on a different model version, GPU, resolution, frame count,
  step count, precision, offload mode, or cold/warm boundary is marked
  `NORMALIZATION REQUIRED` and is never converted by simple GPU ratios.
- Community RTX 3060 reports are auxiliary evidence only.
- Unverified values are `UNKNOWN`; they are not silently inferred.

## Candidate Inventory

### Core Technical Comparison

| Candidate | Release / scale / size | Modes and native profile | 12 GB path | Public timing evidence | Quality and integration evidence | Group |
|---|---|---|---|---|---|---|
| LTX-Video 0.9.8 distilled 2B FP8 | Lightricks; 2025-07-16; 2B; FP8 4.46 GB, BF16 6.34 GB | T2V/I2V; 1216x704 at 30 FPS is documented; frame count is `8n+1`; distilled path recommends no more than 8 steps and no CFG/STG | Official Comfy material says 8-10 GB VRAM for the distilled FP8 path; 12 GB minimum and 16 GB recommended for the 2B family; 32 GB+ host RAM recommended | 5 seconds, 24 FPS, 768x512 in about 2 seconds on H100; grade C, `NORMALIZATION REQUIRED`; RTX 3060 time UNKNOWN | Native ComfyUI support and official workflows; Diffusers/Python support; fast candidate but fine-detail/identity parity is UNKNOWN | A, speed role |
| Wan2.2 TI2V-5B | Wan-AI; 2025-07-28; 5B; official snapshot about 34.2 GB, Comfy diffusion weight 9,999,658,848 bytes | T2V/I2V; 1280x704 or 704x1280; 121 frames at 24 FPS supports about 5 seconds | Official direct Wan path says at least 24 GB with offload/T5 on CPU; official Comfy docs say native offloading fits well on 8 GB. RTX 3060 feasibility therefore depends on the Comfy path | Official claim: under 9 minutes for a 5-second 720p video on an unspecified consumer GPU; grade C/D, `NORMALIZATION REQUIRED`; exact steps/load boundary UNKNOWN | Native ComfyUI workflow and Diffusers; strong motion/aesthetic claims; exact face, hand, and I2V identity metrics UNKNOWN | A, balance/quality role |
| Wan2.2 I2V-A14B 4-step FP8 through LightX2V | Wan/ModelTC; HF card 2026-04-12, GitHub news 2026-04-20; two 14B MoE experts; about 30 GB for two FP8 DiT files before encoders/VAE | I2V; 720p; 4-step distilled path | LightX2V broadly supports 14B on 8 GB VRAM plus 16 GB RAM, but the candidate-specific published configuration documents 24 GB+; 12 GB is UNKNOWN | Model card says about 2x faster than ComfyUI without an RTX 3060 matched receipt; grade C/D, `NORMALIZATION REQUIRED` | Potential high-quality 4-step route; separate runtime and large staged weights increase integration and disk risk | B |
| LTX-2.5 distilled 22B | Lightricks; 2026-08-11; 22B transformer plus Gemma4-12B, video/audio VAEs and upscaler; official download set about 66 GiB | T2V/I2V with synchronized audio; 121-frame examples | Windows is supported, but NATTEN fast path is Linux+CUDA; Windows falls back to Triton/eager. Official 12 GB inference evidence is UNKNOWN | No official matched RTX 3060 12 GB 5-second receipt; grade D | Most complete native audio candidate and strong fidelity claims; large install, gated weights, custom license, and 12 GB uncertainty block admission | B |
| SkyReels-V2 I2V 1.3B 540P | Skywork; 2025; 1.3B; checkpoint size UNKNOWN in this audit | I2V; 544x960, 97 frames, 24 FPS, 50 steps | Official peak is 14.7 GB at 540p; fitting 12 GB would need extra offload or a reduced profile | RTX 3060 matched time UNKNOWN; grade D | Human-centric model, Diffusers support; no verified native Comfy path and 50 steps weaken the speed case | B |
| SkyReels-V3 R2V 14B | Skywork; 2026-01-29; 14B; exact full download size UNKNOWN | Reference-to-video, not a conventional general I2V/T2V replacement; 720p target | Low-VRAM mode is documented for under 24 GB using FP8, block offload, and 540p/480p; exact 12 GB proof UNKNOWN | RTX 3060 matched time UNKNOWN; grade D | Reference consistency is the focus; contract mismatch and custom license require more work | B |
| LongCat-Video 13.6B | Meituan; 2025; 13.6B; exact download size UNKNOWN | T2V/I2V/continuation; 720p at 30 FPS | Single-GPU execution exists, but official RTX 3060 12 GB feasibility is UNKNOWN | Official wording is only "within minutes" without a matched GPU/profile; grade D | Broad modes and MIT model license; no verified current Comfy/native HIVEFRAME route | B |
| HunyuanVideo-1.5 8.3B | Tencent; 2025-11-21; 8.3B; exact download size UNKNOWN | T2V/I2V; official Comfy path targets 24 GB | 12 GB official evidence insufficient | RTX 3060 matched time UNKNOWN; grade D | Technically credible, but model license territory excludes South Korea | C |
| FramePack / FramePack-F1 13B | lllyasviel; 2025; Hunyuan-derived 13B | I2V/continuation; progressive frame generation | Officially runs at 6 GB VRAM on Windows | 4090 about 2.5 seconds/frame, TeaCache about 1.5 seconds/frame; laptops claimed 4-8x slower; grade C/D, `NORMALIZATION REQUIRED` | Good long-video memory behavior, but inherited Hunyuan territory restriction blocks South Korean product use | C |
| CogVideoX-2B | Zhipu/Z.ai; 2024; 2B; exact download size UNKNOWN | T2V only; 720x480, 49 frames, 8 FPS, about 6 seconds, 50 steps | 12 GB exact evidence UNKNOWN | About 90 seconds A100 / 45 seconds H100; grade C, `NORMALIZATION REQUIRED` | Apache-2.0, but old 8 FPS T2V-only profile and no evidence of an H3 product-quality improvement | C |
| Mochi 1 preview 10B | Genmo; 2024; 10B; exact download size UNKNOWN | T2V only; 480p | Official single-GPU path is about 60 GB VRAM; Comfy reports under 20 GB, still above 12 GB | RTX 3060 timing UNKNOWN; grade D | Apache-2.0 but fails the 12 GB admission requirement | C |
| Allegro-TI2V 2.8B | Rhymes AI; 2024; 2.8B; exact download size UNKNOWN | T2V/I2V; 720p, 88 frames, 15 FPS, about 6 seconds, 100 steps | About 9.3 GB with CPU offload | About 20 minutes on one H100; grade C, `NORMALIZATION REQUIRED` | Apache-2.0 and fits through offload, but published performance is not competitive | C |
| Wan2.1 T2V-1.3B | Wan-AI; 2025; 1.3B | T2V only | Historical local M0 comparator | Existing local evidence is incomplete and frozen | Not eligible for a new run under this task | C |
| H3 Standard plus Sage | Existing H3 model/runtime | Same standard profile | Fits current machine | Local grade A: 486.247 seconds submit time, 17.160% lower than the paired standard run | Missed the predeclared 1.3x gate; visual parity not established | C |

### Capability And Product-Fit Details

| Candidate | Face/hands/identity | Temporal/motion | Prompt and artifacts | ComfyUI / Python | Windows/WSL2 and HIVEFRAME change surface |
|---|---|---|---|---|
| LTX-Video 0.9.8 2B | Exact metrics UNKNOWN; smaller distilled model risks fine-detail loss | Official material reports improved motion, but matched temporal metrics UNKNOWN | Improved prompt/detail claims; exact artifact rate UNKNOWN | Native Comfy core plus official workflows; Diffusers supported | Windows-supported Comfy route; add model family/workflow/backend capability mapping, not a product replacement yet |
| Wan2.2 TI2V-5B | Exact face, hand, and input-identity metrics UNKNOWN | Official model emphasizes complex motion and temporal quality | Strong prompt/aesthetic claims; matched artifact rate UNKNOWN | Native Comfy workflow and Diffusers | Best compatibility with current loopback backend; new workflow/node/model admission and output capability mapping required |
| Wan2.2 A14B LightX2V | Exact identity metrics UNKNOWN | Distilled motion quality claimed, matched evidence UNKNOWN | Fine-grained detail claims; exact artifacts UNKNOWN | LightX2V runtime; Comfy comparison only | Separate Python runtime is a larger integration surface; staged dual-expert loading is a risk |
| LTX-2.5 22B | Official high-fidelity claims; exact identity/hands metrics UNKNOWN | Synchronized video/audio and motion claims; matched evidence UNKNOWN | Prompt fidelity claimed; exact artifact rate UNKNOWN | Official Python runtime; current Comfy integration status UNKNOWN | Windows fallback kernels may lose speed; gated, very large asset set and audio contract changes |
| SkyReels-V2 1.3B | Human-centric design; exact hands/identity metrics UNKNOWN | Exact temporal metric for this profile UNKNOWN | Prompt/artifact metrics UNKNOWN | Diffusers; native Comfy path UNKNOWN | Likely separate runtime or community nodes; 14.7 GB published peak exceeds device |
| SkyReels-V3 14B | Reference-consistency focus; exact metric UNKNOWN | Long/reference motion evidence is qualitative here | Prompt/artifact metrics UNKNOWN | Official Python; Comfy status UNKNOWN | Contract is R2V, plus aggressive offload and likely WSL2/Linux work |
| LongCat-Video 13.6B | Official exact metrics not captured; UNKNOWN | Continuation and 720p30 are strengths | Prompt/artifact matched data UNKNOWN | Diffusers/single GPU; Comfy status UNKNOWN | Separate runtime likely; 12 GB and latency admission unresolved |

## License Review

This is an engineering reading of public terms, not legal advice. A candidate
with unresolved terms cannot pass a commercial gate.

| Candidate | Weight license | Commercial/SaaS | Local installer redistribution | Derivatives / output | Attribution, gate, and material restrictions | Result |
|---|---|---|---|---|---|---|
| LTX-Video 0.9.8 | LTXV Open Weights License 0.X; code repo Apache-2.0 is separate | Allowed below USD 10M annual revenue, subject to restrictions; USD 10M+ requires a paid agreement | Permitted subject to license/pass-through obligations; bundled distribution needs legal packaging review | Derivatives subject to terms; licensor does not claim output rights, but restricted uses remain | License/notice obligations; no repository login/accept gate found | Commercially testable with revenue and distribution controls |
| Wan2.2 TI2V-5B | Apache-2.0 | Allowed | Allowed with Apache notices/terms | Apache derivative terms; no model-specific output ownership restriction found | Preserve license/notices; no acceptance gate identified | Lowest license risk in shortlist |
| Wan2.2 A14B LightX2V | LightX2V and Wan base state Apache-2.0; transitive files must be verified | Likely allowed, pending exact downloaded-file audit | Likely allowed with notices, pending transitive audit | Apache terms expected | No gate identified; verify every selected asset before download | `COMMERCIAL UNKNOWN` until transitive audit |
| LTX-2.5 22B | LTX-2 Open Weights License covering LTX-2.5/2.x | Allowed below USD 10M; paid agreement at/above USD 10M | Permitted with pass-through restrictions and notices; installer packaging needs review | Derivatives restricted by terms; no licensor output claim, but use restrictions apply | Hugging Face acceptance/login token required; extensive restricted-use/transparency duties | Commercially possible but high operational/legal friction |
| SkyReels-V2/V3 | Skywork Community License | Commercial use appears available, subject to custom terms | Exact installer redistribution obligations need legal review | Derivative/output details require exact-term review | Internet-service and safety-review obligations may apply | `COMMERCIAL UNKNOWN` |
| LongCat-Video | MIT on model repository | Allowed | Allowed with notice | Permissive | Preserve notice | Low apparent license risk; technical admission still weak |
| HunyuanVideo-1.5 | Tencent Hunyuan custom license | Territory restricted | Not acceptable for this product location | Custom restrictions | License explicitly does not apply in South Korea, EU, or UK | Excluded |
| FramePack / F1 | FramePack code Apache-2.0; base Hunyuan weights under Tencent terms | Base-weight territory restriction controls model use | Not acceptable for this product location | Derived model remains tied to base terms | South Korea excluded by base license | Excluded |
| CogVideoX-2B | Apache-2.0 | Allowed | Allowed with notices | Apache terms | Preserve notice | Low license risk |
| Mochi 1 | Apache-2.0 | Allowed | Allowed with notices | Apache terms | Preserve notice | Low license risk |
| Allegro-TI2V | Apache-2.0 | Allowed | Allowed with notices | Apache terms | Preserve notice | Low license risk |

## Classification

### Group A: Recommended For One Admission Test

1. **LTX-Video 0.9.8 distilled 2B FP8**: the strongest documented 12 GB
   speed path, small enough to stage locally, and available through native
   ComfyUI. Its main uncertainty is whether 2B distilled quality can improve
   on the already weak H3 output.
2. **Wan2.2 TI2V-5B**: the strongest balance/quality candidate with official
   native ComfyUI integration and Apache-2.0 weights. Its main uncertainty is
   the contradictory 8 GB Comfy versus 24 GB direct-runtime memory guidance
   and the lack of a matched RTX 3060 timing.

### Group B: Reserve

- Wan2.2 A14B 4-step LightX2V: candidate-specific 12 GB proof and transitive
  asset/license audit are missing.
- LTX-2.5 22B: latest and feature-rich, but the 66 GiB asset set, gated custom
  license, Windows fallback path, and absent 12 GB evidence make first testing
  disproportionate.
- SkyReels-V2 1.3B: published 14.7 GB peak exceeds the device and 50 steps
  weakens the speed case.
- SkyReels-V3 14B: exact 12 GB feasibility is unknown and R2V does not directly
  replace the current I2V contract.
- LongCat-Video 13.6B: permissive license and broad modes are promising, but
  12 GB feasibility, exact latency, and Comfy integration are unknown.

### Group C: Excluded From The Next Test

- HunyuanVideo-1.5 and FramePack/F1: South Korea is excluded by the applicable
  Hunyuan model license.
- CogVideoX-2B: T2V-only, 8 FPS/49-frame legacy profile and no credible H3
  product-quality gain.
- Mochi 1: published memory requirements exceed 12 GB.
- Allegro-TI2V: about 20 minutes on H100 at its published profile is not a
  credible latency competitor.
- Wan2.1 T2V-1.3B: frozen historical M0 comparator, not an eligible rerun.
- H3 plus Sage: already failed its own speed gate and lacks visual parity.
- H3 low-resolution preview: not a new engine and prohibited as a competitive
  quality shortcut.

## Shortlist

Only two candidates meet the evidence bar. A third is not forced.

### 1. LTX-Video 0.9.8 Distilled 2B FP8: Speed Role

- Test value: strongest official 12 GB claim and native Comfy path.
- Expected improvement: materially lower sampler and total latency.
- Primary risk: low parameter count/distillation may preserve the same
  unacceptable fine-detail weakness as H3 or introduce identity drift.
- New download if approved: FP8 diffusion checkpoint and only the official
  encoders/VAE required by the selected native workflow; exact total bytes and
  hashes must be captured before approval to download.
- Install change: add assets outside the current H3 tree; no replacement or
  mutation of current Comfy/models.
- Conflict risk: low for native Comfy core, but exact installed Comfy version
  compatibility must be read-only checked before download.
- RTX 3060 formal time: UNKNOWN; no numerical prediction is accepted.

### 2. Wan2.2 TI2V-5B: Balance/Quality Role

- Test value: 5B hybrid T2V/I2V, 720p native profile, Apache-2.0, official
  Comfy workflow, and the best chance of visible quality improvement.
- Expected improvement: better motion, aesthetic consistency, and detail at a
  latency no worse than the H3 baseline.
- Primary risk: offload may fit VRAM but move the bottleneck into host RAM/PCIe,
  and official timing is not normalized to this machine.
- New download if approved: exact Comfy-repackaged TI2V diffusion file plus
  required T5/CLIP/VAE files; expected full official snapshot is about 34.2 GB,
  but selected-file total must be enumerated before download.
- Install change: separate model assets and a new workflow; current H3 assets
  and nodes stay immutable.
- Conflict risk: low-to-medium; native Comfy integration is favorable, but
  installed node/schema compatibility must be checked first.
- RTX 3060 formal time: UNKNOWN; no proportional estimate is accepted.

## Proposed Generation Test Plan

This plan is not authorized by this document. Each candidate receives exactly
one minimal admission submission. Failure stops that candidate with no retry.
Only a passed admission may proceed to the candidate's cold and warm formal
runs after separate user approval.

### Shared Controls

- Confirm queue idle twice through the P1-A2 busy guard. Any foreign work
  blocks the run; nothing is cancelled.
- Capture GPU, driver, Comfy commit/version, node versions, free disk, host RAM,
  selected file URLs, byte sizes, SHA-256 hashes, and license snapshots before
  installation or launch.
- Keep every candidate in a separate asset/workflow namespace. Do not modify or
  overwrite H3 checkpoints, workflow, nodes, or defaults.
- Use the same local dog input image and semantically equivalent fixed prompt.
- Use seed 101 only where the model exposes a reproducible seed contract.
- Produce about 5 seconds at 24 FPS. Use 864x480 only when native/supported;
  otherwise use the nearest official landscape profile and mark
  `NORMALIZATION REQUIRED`.
- Use the candidate's official quality profile. Do not reduce resolution,
  frames, or steps to manufacture a win.
- Separate model-load time, sampler time, backend submit-to-terminal, and total
  product E2E. Record cold and warm boundaries explicitly.
- Record peak VRAM and host RAM, output frame count/FPS/codec/duration, black or
  corrupt frames, non-finite failures, retry, fallback, and external API use.
- Perform blinded H3-versus-candidate review for input identity, face/eyes/muzzle,
  fine texture, motion naturalness, temporal consistency, prompt adherence,
  deformation, flicker, blur, and other artifacts. Hands are marked N/A for
  this fixed dog input, not silently scored as passing.
- Do not add an upscaler, frame interpolation, synthetic audio, TeaCache, or a
  second optimization during initial comparison. Those are separate variables.

### LTX-Video Admission And Formal Profile

- Admission: official native Comfy distilled FP8 I2V workflow, 768x512 or the
  nearest workflow-native size, 33 frames, 24 FPS, 8 distilled steps, no
  CFG/STG, one submission. Purpose: prove model load, 12 GB survival, schema,
  image conditioning, and valid video output; it is not competitive evidence.
- Admission stop: OOM, model/node mismatch, non-finite result, corrupt video,
  external access, fallback, retry, or over 15 minutes submit-to-terminal.
- Formal cold and warm runs: 864x480 when accepted by the official workflow,
  otherwise 768x512 with normalization; 121 frames at 24 FPS; 8 distilled
  steps; same input/prompt; no optional upscaler.

### Wan2.2 TI2V-5B Admission And Formal Profile

- Admission: official native Comfy TI2V workflow, 1280x704 landscape, 25 frames
  or the smallest official `4n+1` frame count accepted by the workflow, native
  official sampler/steps, one submission. Purpose: prove 12 GB offload, node
  schema, image conditioning, and valid output; it is not competitive evidence.
- Admission stop: the shared failures above, host-memory exhaustion or sustained
  system unresponsiveness, or over 20 minutes submit-to-terminal.
- Formal cold and warm runs: 1280x704, 121 frames, 24 FPS, official workflow
  sampler/steps/precision/offload unchanged. This differs from H3 resolution
  and is therefore `NORMALIZATION REQUIRED`; report both pixels-per-frame and
  observed time, never a derived H3-equivalent time.

## Proposed Gates Requiring User Approval

### Mandatory Admission Gate

- Completes on RTX 3060 12 GB without OOM.
- Output integrity passes with the expected duration, frame count, and FPS.
- External API is zero; fallback is zero; retry is zero.
- Commercial use is not `UNKNOWN` for the exact downloaded files.
- The candidate can be integrated behind the current backend/result/busy-guard
  contract without changing or interrupting H3.

### Competitive Gate

A candidate must pass one track. All times are total product E2E, and each
track also requires valid sampler and backend submit-to-terminal receipts.

- **Speed track**: no critical visual regression versus H3 and E2E at or below
  420.0 seconds (at least 25% faster than 559.990 seconds).
- **Quality track**: clear blinded visual improvement versus H3, no critical
  defect, and E2E at or below 559.990 seconds.
- **Balanced track**: clear visual improvement, no critical defect, E2E at or
  below 300.0 seconds, and peak VRAM at or below 12,288 MiB.

The repository has no previously approved numerical competitiveness gate.
These are proposals, not final acceptance criteria.

### Installer Eligibility Gate

Installer work remains blocked until one exact engine/profile has:

- all mandatory and competitive gates passing;
- a blinded rating of at least `ACCEPTABLE_FOR_ALPHA`, not
  `LOW_QUALITY_BUT_FUNCTIONAL`;
- total product E2E at or below 180.0 seconds for the fixed about-5-second
  comparison, reflecting the stated two-minute-range product goal;
- complete exact-file license, attribution, download-size, hash, disk, RAM,
  Windows/WSL2, and uninstall/isolation records.

This stronger installer threshold is also a proposal and requires explicit
user approval. A competitive test pass alone does not authorize installer
implementation.

## Sources

All sources were checked on 2026-08-18. Official sources are primary unless a
row is explicitly graded D.

- LTX-Video repository and runtime:
  https://github.com/Lightricks/LTX-Video
- LTX-Video weights and file sizes:
  https://huggingface.co/Lightricks/LTX-Video/tree/main
- LTXV Open Weights License 0.X:
  https://huggingface.co/Lightricks/LTX-Video/blob/main/LTX-Video-Open-Weights-License-0.X.txt
- LTX-Video paper:
  https://arxiv.org/abs/2501.00103
- Official Comfy LTX-Video model information:
  https://comfy.org/models/ltx-video
- Wan2.2 official repository:
  https://github.com/Wan-Video/Wan2.2
- Wan2.2 TI2V-5B model card:
  https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B
- Official Comfy Wan2.2 guide:
  https://docs.comfy.org/tutorials/video/wan/wan2_2
- Comfy Wan2.2 TI2V-5B diffusion file:
  https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/blob/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors
- LightX2V repository:
  https://github.com/ModelTC/LightX2V
- Wan2.2 distilled LightX2V weights:
  https://huggingface.co/lightx2v/Wan2.2-Distill-Models
- LTX-2.5 repository/readme:
  https://github.com/Lightricks/LTX-2
- LTX-2.x license:
  https://github.com/Lightricks/LTX-2/blob/main/LICENSE
- SkyReels-V2 repository and license:
  https://github.com/SkyworkAI/SkyReels-V2
  https://github.com/SkyworkAI/SkyReels-V2/blob/main/LICENSE.txt
- SkyReels-V3 repository:
  https://github.com/SkyworkAI/SkyReels-V3
- LongCat-Video model card:
  https://huggingface.co/meituan-longcat/LongCat-Video
- HunyuanVideo-1.5 repository and license:
  https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5
  https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/blob/main/LICENSE
- FramePack repository and Hunyuan base license:
  https://github.com/lllyasviel/FramePack
  https://github.com/Tencent-Hunyuan/HunyuanVideo/blob/main/LICENSE.txt
- CogVideoX model card and repository:
  https://huggingface.co/zai-org/CogVideoX-2b
  https://github.com/zai-org/CogVideo
- Mochi repository and model card:
  https://github.com/genmoai/mochi
  https://huggingface.co/genmo/mochi-1-preview
- Allegro repository:
  https://github.com/rhymes-ai/Allegro

## Unknowns And Required Preflight

- Exact installed host RAM total and currently free disk space were unavailable
  to this read-only sandbox probe. Prior H3 receipts show large host-memory use,
  but no total is inferred.
- Exact H3 guidance value and explicit offload node were not re-derived because
  this task forbids repeating prior evidence work.
- Exact RTX 3060 timing for both shortlisted candidates is UNKNOWN.
- Wan2.2 official 8 GB Comfy and 24 GB direct-runtime guidance must be resolved
  against the exact selected workflow and file set.
- Exact LTX required companion-file total, hashes, and current installed Comfy
  compatibility require a no-download preflight.
- Exact Wan selected-file total, hashes, native sampler/step defaults, and node
  compatibility require a no-download preflight.
- Human review criteria and the proposed 420/300/180-second thresholds require
  user approval before they become gates.

## Verification And Cost Receipt

- Repository/GitHub state, duplicate records, H3/P1-A2 evidence, backend
  contract, official model cards/repos/licenses, and candidate integration
  material were inspected read-only.
- Local GPU query confirmed NVIDIA GeForce RTX 3060, 12,288 MiB, driver 610.88,
  compute capability 8.6.
- Model downloads: 0
- Checkpoint installs: 0
- ComfyUI changes: 0
- Actual video generations: 0
- External inference API calls: 0
- Installer changes: 0
- Roadmap changes: 0
- PR #91/#92/#94/#95 changes: 0
- Diagram impact: none; this document proposes unsupported future candidates
  and changes no current architecture or verified product capability.

## Decision And Next Action

Research decision:

`ENGINE_COMPETITIVENESS_SHORTLIST_READY_FOR_APPROVAL`

The approved candidate count is not yet set. No candidate is promoted to the
product, and installer work remains blocked. The recommended next action is a
separately authorized, bounded admission task in this order:

1. LTX-Video 0.9.8 distilled 2B FP8 admission.
2. If approved independently, Wan2.2 TI2V-5B admission.

Before either action, the user must approve the proposed gates, exact download
and disk budget after preflight, environment isolation, and the per-candidate
one-admission/no-retry generation budget.
