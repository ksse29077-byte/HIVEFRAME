# M0 Baseline Operations

## Current workstation finding

The inspected workstation has:

- Intel Arc A770 with 16,256 MB dedicated display memory;
- AMD integrated graphics with 2,021 MB dedicated memory;
- no NVIDIA GPU, `nvidia-smi`, CUDA toolkit, PyTorch, Diffusers, or Accelerate;
- 61.6 GiB host RAM;
- about 705.5 GiB free on drive C at inspection time.

The pinned official Wan implementation imports `flash_attn`, invokes CUDA paths, and documents its reference execution on NVIDIA RTX hardware. The Arc A770 has enough nominal VRAM for the publisher's stated 8.19 GB 1.3B requirement, but it is not compatible with the pinned official CUDA backend. An Intel XPU port would be a separate experimental backend and must not be mixed into the official M0 receipt.

## Pinned upstream

- Code: `https://github.com/Wan-Video/Wan2.1.git`
- Code revision: `9737cba9c1c3c4d04b33fcad41c111989865d315`
- Model: `Wan-AI/Wan2.1-T2V-1.3B`
- Model revision: `37ec512624d61f7aa208f7ea8140a131f93afc9a`
- License: Apache-2.0

The model card states an 8.19 GB VRAM requirement for T2V 1.3B and recommends 480P. The official example reports roughly four minutes for a five-second 480P video on an RTX 4090 without quantization.

## Download disclosure

No model files have been downloaded.

- Exact repository payload reported by the official Hugging Face API: `17,573,837,064` bytes
- Decimal size: about `17.574 GB`
- Binary size: about `16.367 GiB`
- Proposed local destination: `models/Wan2.1-T2V-1.3B`
- Absolute destination from this checkout:
  `C:\Users\ksse2\Documents\Codex\2026-07-30\referenced-chatgpt-conversation-this-is-untrusted-2\outputs\HIVEFRAME\models\Wan2.1-T2V-1.3B`
- Reserved free space after download: `10 GiB`

The directory is excluded from Git. Download requires explicit user approval after this disclosure.

## Commands

The runner has no third-party import requirement for planning and preflight:

```powershell
$env:PYTHONPATH = "python"
python hiveframe_m0.py download-plan
python hiveframe_m0.py preflight
```

Verify model sizes after an approved download:

```powershell
python hiveframe_m0.py verify-model
python hiveframe_m0.py verify-model --full
```

Run one deterministic sample only when preflight is ready:

```powershell
python hiveframe_m0.py run --prompt-id static-speaking-person
```

Run all ten prompts:

```powershell
python hiveframe_m0.py run-suite
```

If preflight is blocked, the runner writes a blocked receipt instead of attempting a degraded CPU/XPU execution.

## Receipt coverage

The current wrapper records:

- exact code/model revision and license;
- prompt ID, prompt text, seed, resolution, frames, steps, solver, shift, and guidance;
- wall time, child-process peak host RAM, sampled NVIDIA VRAM and utilization;
- stdout/stderr paths, output size, and SHA-256;
- environment, package, and Git fingerprint;
- explicit blockers, failures, and null fields.

GPU kernel, denoising-step, VAE encode/decode, and scheduler timings remain `null` until the next instrumentation hook is implemented. They are never estimated from wall time.

## Next environment decision

Choose one path before downloading:

1. **Recommended for canonical M0:** use an NVIDIA CUDA host with at least 12–16 GB VRAM and keep the pinned official backend.
2. **Separate research track:** evaluate PyTorch XPU/Diffusers on Arc A770, using a different backend identifier and never comparing it as the official baseline.
