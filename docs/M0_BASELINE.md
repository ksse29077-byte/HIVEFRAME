# M0 Baseline Operations

M0 is limited to a reproducible Wan 2.1 T2V 1.3B baseline. It does not implement patch scheduling, boundary exchange, temporal cache, LoRA training, distributed multi-GPU execution, or a GUI.

## Current workstation decision

The inspected workstation has:

- Intel Arc A770 with 16,256 MB dedicated display memory;
- AMD integrated graphics with 2,021 MB dedicated memory;
- no NVIDIA GPU, `nvidia-smi`, CUDA toolkit, PyTorch, Diffusers, or Accelerate;
- 61.6 GiB host RAM;
- about 705.5 GiB free on drive C at inspection time.

The pinned official Wan code constructs `cuda:N` devices and depends on `flash_attn`. The Arc A770 has enough nominal VRAM for the publisher's stated 8.19 GB 1.3B requirement, but it cannot run this pinned official CUDA backend. An Intel XPU port would be a separate experimental backend and must not be mixed into the canonical M0 receipt.

Recommended settings for a compatible NVIDIA baseline host:

| Setting | Smoke | Baseline |
|---|---:|---:|
| dtype | bfloat16 | bfloat16 |
| device | cuda:0 | cuda:0 |
| resolution | 832×480 | 832×480 |
| frames | 17 | 49 |
| FPS | 16 | 16 |
| denoising steps | 4 | 50 |
| scheduler | UniPC | UniPC |
| guidance | 6.0 | 6.0 |
| model CPU offload | enabled | enabled |
| T5 on CPU | enabled | enabled |

The smoke profile is only a pipeline check and is not a quality result. The full settings retain the project's requested 49-frame target while using the official 1.3B-supported 480P dimensions.

## Pinned code and checkpoint

These are separate admitted artifacts:

### Official code

- Repository: `https://github.com/Wan-Video/Wan2.1.git`
- Revision: `9737cba9c1c3c4d04b33fcad41c111989865d315`
- License: Apache-2.0 from the pinned source repository
- Commercial use and modification: permitted under Apache-2.0
- Redistribution: include the license, mark modified files, retain applicable attribution notices, and preserve NOTICE content if a future pinned source contains NOTICE
- NOTICE at the pinned revision: none observed

### Official checkpoint

- Repository ID: `Wan-AI/Wan2.1-T2V-1.3B`
- Revision: `37ec512624d61f7aa208f7ea8140a131f93afc9a`
- License: separately published Apache-2.0 checkpoint license
- Commercial use and modification: permitted under Apache-2.0
- Redistribution: the same Apache-2.0 license, modification, attribution, and possible NOTICE duties apply
- NOTICE at the pinned revision: none observed
- Additional model-card conditions: lawful and non-harmful use; no malicious personal-data exposure, misinformation, harm to people/groups, or targeting vulnerable populations

This verification is recorded in `data_ledger/models/wan21_t2v_1_3b.json`. Commercial release still requires a final product/legal review.

## Mandatory pre-download disclosure

No model or large file has been downloaded.

| Item | Planned value |
|---|---:|
| Official repository payload | 17,573,837,064 bytes / 17.574 GB / 16.367 GiB |
| Expected installed snapshot | approximately 18.0 GB |
| Temporary and cache headroom | 18.0 GB |
| Required post-install reserve | 10 GiB |
| Recommended free space before download | 46,737,418,240 bytes / 46.737 GB / about 43.53 GiB |
| Free space observed on C | about 705.5 GiB |

Exact model destination:

```text
C:\Users\ksse2\Documents\Codex\2026-07-30\referenced-chatgpt-conversation-this-is-untrusted-2\outputs\HIVEFRAME\models\Wan2.1-T2V-1.3B
```

Exact Hugging Face cache and temporary-download destination:

```text
C:\Users\ksse2\Documents\Codex\2026-07-30\referenced-chatgpt-conversation-this-is-untrusted-2\outputs\HIVEFRAME\models\.hf-cache
```

Both directories are excluded from Git. The download command is only printed by `download-plan`; the runner has no command that automatically downloads weights. Explicit user approval is required before running the printed download command.

## Gated execution order

Planning and preflight require no third-party model packages:

```powershell
python hiveframe_m0.py download-plan
python hiveframe_m0.py preflight
```

After a separately approved download, verify key sizes and hashes:

```powershell
python hiveframe_m0.py verify-model
python hiveframe_m0.py verify-model --full
```

Execution order is enforced:

```powershell
# 1. One low-cost pipeline check
python hiveframe_m0.py smoke

# 2. Same prompt and seed, cold then warm in one loaded process
python hiveframe_m0.py run --prompt-id static-speaking-person

# 3. Only after smoke and hash reproducibility pass
python hiveframe_m0.py run-suite
```

The smoke gate is tied to the project Git commit, code revision, model revision, and configuration hash. A changed input invalidates the gate. The canonical ten-prompt suite is a separate stage and cannot start until both smoke and cold/warm reproducibility gates pass.

## Fixed generation inputs

Every command records and fixes:

- positive and negative prompt;
- deterministic seed;
- width and height;
- frame count and FPS;
- denoising steps, guidance, shift, and scheduler;
- dtype and device;
- model offload and T5 CPU placement;
- exact model ID/revision and code revision.

Prompt extension is disabled because it would introduce an external model or API and undermine the canonical input.

## Timing and resource receipt

The instrumented wrapper separates, when supported:

- model load wall time and CUDA-event time;
- positive and negative prompt-encode wall/CUDA time;
- total denoising wall/CUDA time;
- every denoising step's wall/CUDA time, including the scheduler step;
- VAE decode wall/CUDA time;
- video preprocessing/encode wall/CUDA time;
- full child wall-clock time;
- peak PyTorch allocated/reserved VRAM;
- sampled NVIDIA VRAM and utilization;
- child-process peak host RAM.

T2V has no input VAE encode stage, so that field is `null` with a not-applicable reason. Scheduler-only overhead is not isolated by the non-invasive hook; it remains `null` with a reason instead of being estimated.

Each receipt also contains:

- model ID/revision and code repository/revision;
- HIVEFRAME Git commit and dirty state;
- OS, Python, package, PyTorch, CUDA, driver, and GPU inventory;
- complete fixed settings and settings/configuration hashes;
- exact child execution command;
- start/end timestamps;
- output paths, byte counts, and SHA-256;
- errors, partial instrumentation, and unsupported-metric reasons.

Failed and blocked runs still write partial receipts.

## Cold, warm, and reproducibility

The reproducibility command loads the model once, then runs the same prompt and seed twice:

- `cold`: first generation after model load;
- `warm`: second generation with the same in-process model and runtime caches.

Both outputs are hashed. Matching hashes pass the gate. A mismatch fails the gate and records possible nondeterministic CUDA kernels, driver/library differences, uncontrolled upstream random state, and video-encoder nondeterminism for investigation. A mismatch is never reported as success.

## Current measured values

Only environment and safety behavior have been measured on this PC:

- Arc A770 dedicated VRAM: 16,256 MB;
- host RAM: 61.6 GiB;
- C free space: approximately 705.5 GiB;
- preflight: blocked because CUDA, runtime packages, pinned upstream checkout, and checkpoint are absent;
- blocked-run safety test: exit code 2, zero videos, one partial receipt.

Model load, prompt encode, denoising, VAE decode, video encode, CUDA time, and generation memory values are not yet measured because the official backend cannot execute on this PC and the model has not been downloaded.
