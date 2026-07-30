# M0 WSL2 RTX 3060 Validated Environment

Status: model-free host qualification complete on 2026-07-30. No Wan
checkpoint or Hugging Face model file was downloaded, and no model generation
was run.

## Validated host

| Component | Validated value |
|---|---|
| Windows GPU driver exposed to WSL | 610.88 |
| WSL distribution | Ubuntu 24.04.4 LTS, WSL version 2 |
| WSL kernel | 6.18.33.2-microsoft-standard-WSL2 |
| GPU | NVIDIA GeForce RTX 3060, compute capability 8.6 |
| VRAM | 12,288 MiB reported by `nvidia-smi`; 12,884,377,600 bytes reported by PyTorch |
| WSL RAM / swap | 32,386,969,600 bytes / 8 GiB |
| System Python | 3.12.3, preserved |
| Isolated Python | CPython 3.10.20 |
| PyTorch / TorchVision | 2.4.1+cu124 / 0.19.1+cu124 |
| PyTorch CUDA / cuDNN | 12.4 / 9.1.0 |
| FlashAttention | 2.7.4.post1 |

PyTorch detected CUDA, the RTX 3060, and BF16 support. FP16 and BF16 matrix
multiplications returned finite results. An actual BF16 FlashAttention
operation with shape `[1, 128, 8, 64]` also returned finite results.
TorchVision, Diffusers, Transformers, Accelerate, and FlashAttention imports
all succeeded.

The full CUDA Toolkit was not installed. The PyTorch CUDA runtime and a matching
prebuilt FlashAttention wheel were sufficient, so `nvcc` is intentionally
absent.

## Installed locations

```text
/home/ksse2/.local/python-3.10.20
/home/ksse2/.venvs/hiveframe-m0
/home/ksse2/src/Wan2.1
/home/ksse2/hiveframe-m0-state
```

The official Wan source checkout is detached and clean at:

```text
9737cba9c1c3c4d04b33fcad41c111989865d315
```

The source checkout is code only and is not a checkpoint.

## Package sources and pins

- CPython 3.10.20: official `python.org` source archive; SHA-256
  `de6517421601e39a9a3bc3e1bc4c7b2f239297423ee05e282598c83ec0647505`.
- PyTorch 2.4.1 and TorchVision 0.19.1: official PyTorch CUDA 12.4 wheel
  index, `https://download.pytorch.org/whl/cu124`.
- FlashAttention 2.7.4.post1: official Dao-AILab GitHub release wheel
  `flash_attn-2.7.4.post1+cu12torch2.4cxx11abiFALSE-cp310-cp310-linux_x86_64.whl`;
  SHA-256
  `a8719a86d0cd12a105739151f9e45ac8c2ecb840a83ed7a080a88d1645a98440`.
- Remaining Python packages: pinned PyPI packages recorded in
  `python/requirements-m0.wsl2.lock.txt`.
- Compiler, CPython build headers, SSL, SQLite, zlib, readline, and related
  system libraries: Ubuntu 24.04 archives.
- Wan code: official `Wan-Video/Wan2.1` GitHub repository.

`dashscope` and `gradio` were not installed because the M0 official local T2V
command does not use the hosted prompt-extension service or GUI. They remain
outside the model-free M0 execution path.

## Activate and verify

From Ubuntu:

```bash
source /home/ksse2/.venvs/hiveframe-m0/bin/activate
export PYTHONPATH=/mnt/c/Users/ksse2/Documents/Codex/2026-07-30/referenced-chatgpt-conversation-this-is-untrusted-2/outputs/HIVEFRAME/python
export HIVEFRAME_WAN_CODE_DIR=/home/ksse2/src/Wan2.1
export HIVEFRAME_MODEL_DIR=/home/ksse2/ai/models/Wan2.1-T2V-1.3B
export HIVEFRAME_HF_CACHE_DIR=/home/ksse2/ai/cache/huggingface
export HIVEFRAME_M0_REPORT_DIR=/home/ksse2/hiveframe-m0-state
cd /mnt/c/Users/ksse2/Documents/Codex/2026-07-30/referenced-chatgpt-conversation-this-is-untrusted-2/outputs/HIVEFRAME

python -m pip check
python -m unittest discover -s python/tests -v
python hiveframe_m0.py download-plan
python hiveframe_m0.py preflight \
  --output /home/ksse2/hiveframe-m0-state/preflight.json
```

Before checkpoint approval, `preflight` must stop with exactly one blocker:
`model_missing`. `download-plan` must report `"download_performed": false`.

## Model and cache path decision

Use the WSL Linux filesystem for large, frequently read model and cache files:

```text
Model: /home/ksse2/ai/models/Wan2.1-T2V-1.3B
Cache: /home/ksse2/ai/cache/huggingface
```

These paths are short, separate, and were deliberately not created during host
qualification. The earlier Windows locations are addressable as
`/mnt/c/AI/Models` and `/mnt/c/AI/HFCache`, but Linux-native ext4 storage is
preferred for model loading, cache metadata, and many-file workloads. Keeping
the source repository on `/mnt/c` is acceptable for the small M0 codebase.

## Pending checkpoint gate

The approved identity remains:

```text
Repository: Wan-AI/Wan2.1-T2V-1.3B
Revision:   37ec512624d61f7aa208f7ea8140a131f93afc9a
Download:   17,573,837,064 bytes (17.574 GB / 16.367 GiB)
Installed:  approximately 18.0 GB
Headroom:   46,737,418,240 bytes recommended before download
```

At qualification time the Linux filesystem had 1,014,041,579,520 bytes
available, so capacity is sufficient. This is not approval to download.

Only after explicit approval:

1. Re-run `download-plan` and confirm repository, revision, size, destination,
   cache destination, and `"download_performed": false`.
2. Download with the exact repository and revision printed by that plan.
3. Run `python hiveframe_m0.py verify-model --full`.
4. Run `preflight` again and require zero blockers before any generation.

## Required execution order after later approval

The M0 gates remain:

1. one 832x480, 17-frame, 4-step smoke run;
2. cold run;
3. warm run in the same process;
4. same-seed output-hash reproducibility decision;
5. the separate canonical ten-prompt suite only after all earlier gates pass.

On this 12 GB card, keep BF16, model CPU offload, and T5 on CPU enabled. The
smoke profile is expected to fit. The 49-frame, 50-step baseline is a plausible
but unverified tight-memory path; host RAM transfer and VAE decode are likely
bottlenecks. A real answer requires the still-unapproved checkpoint run.

## Storage footprint

The WSL filesystem used 10,666,201,088 additional bytes during setup,
including:

- isolated environment: 6,288,043,910 bytes;
- pip download cache: 3,245,092,641 bytes, reclaimable later;
- CPython prefix: 232,369,624 bytes;
- Wan source checkout: 21,931,650 bytes;
- Ubuntu build dependencies and other filesystem changes: the remainder.

The exact environment fingerprint is
`data_ledger/environments/wsl2_ubuntu2404_rtx3060_m0.json`.

## Known warnings and limits

- Wan imports emit deprecation warnings for `torch.cuda.amp.autocast`; they do
  not block M0.
- Python 3.10 compatibility requires the pinned `tomli` fallback because the
  standard-library `tomllib` and `datetime.UTC` are newer interfaces.
- No checkpoint integrity check, video generation, latency measurement, peak
  VRAM measurement, cold/warm comparison, or output reproducibility claim has
  been made.
- The 12 GB baseline memory assessment remains provisional until the approved
  smoke gate runs.
