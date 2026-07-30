# M0 NVIDIA CUDA Host Handoff

This guide prepares a separate NVIDIA machine to continue the existing M0
baseline. It does not authorize a checkpoint download. Do not run the model
download or GPU stages until the user gives explicit approval on that host.

## Supported and recommended host

Use a native x86-64 Linux host. FlashAttention is primarily supported on Linux;
its Windows build path remains less mature.

| Level | Requirement |
|---|---|
| GPU architecture | NVIDIA Ampere, Ada, or Hopper for BF16 FlashAttention |
| Practical minimum | 12 GB VRAM with model offload and T5 on CPU |
| Recommended | 24 GB VRAM, such as RTX 3090/4090, RTX A5000, L4, A10, A100, or H100 |
| Host RAM | 32 GB minimum; 64 GB recommended |
| Disk | At least 46.737 GB free before the approved checkpoint download; 60 GB or more is preferred |
| OS | Ubuntu 22.04 LTS or another supported glibc 2.28+ Linux distribution |

The publisher reports an 8.19 GB VRAM path for T2V-1.3B and demonstrates the
single-GPU path on RTX 4090. HIVEFRAME recommends extra VRAM because M0 also
collects instrumentation and retains the unmodified BF16 baseline.

Turing GPUs are not canonical M0 targets: the selected BF16 path and current
FlashAttention-2 support target Ampere or newer.

## Reproducibility anchor

The recommended first-host combination is:

- NVIDIA driver `550.54.14` or newer on Linux;
- CUDA Toolkit 12.4 when FlashAttention must be compiled locally;
- Python 3.10;
- PyTorch 2.4.1 with CUDA 12.4 wheels;
- TorchVision 0.19.1 with CUDA 12.4 wheels;
- FlashAttention built against that exact Python, PyTorch, and CUDA combination.

Wan requires PyTorch 2.4.0 or newer. The selected 2.4.1/0.19.1 pair is a
conservative patch-level anchor, not a claim that newer combinations are
unsupported. CUDA 12.4 requires driver 550.54.14 or newer on Linux. Do not mix a
CPU TorchVision wheel with a CUDA PyTorch wheel.

Before installing packages, verify:

```bash
nvidia-smi
python3.10 --version
```

Create an isolated environment and install the anchored pair:

```bash
cd /opt/hiveframe
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel packaging psutil ninja
python -m pip install \
  torch==2.4.1 torchvision==0.19.1 \
  --index-url https://download.pytorch.org/whl/cu124
python -m pip install \
  -r python/requirements-m0.in \
  -c python/constraints-m0.cuda124.txt
```

If FlashAttention must be installed separately, install it only after PyTorch:

```bash
MAX_JOBS=4 python -m pip install flash-attn --no-build-isolation
```

Then verify the runtime before cloning or downloading a checkpoint:

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda); print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
python -c "import flash_attn; print(flash_attn.__version__)"
```

After the first successful smoke test, preserve `python -m pip freeze` with the
receipt bundle. The current constraints file is an installation anchor, not yet
a fully validated transitive lock.

## Receive the repository and pin official Wan code

Receive or clone HIVEFRAME, then check out the approved HIVEFRAME commit. Clone
the official Wan source separately and detach it at the already admitted
revision:

```bash
git clone https://github.com/ksse29077-byte/HIVEFRAME.git /opt/hiveframe
cd /opt/hiveframe
git checkout <approved-hiveframe-commit>

git clone https://github.com/Wan-Video/Wan2.1.git /opt/wan21
git -C /opt/wan21 checkout --detach 9737cba9c1c3c4d04b33fcad41c111989865d315
git -C /opt/wan21 status --short
git -C /opt/wan21 rev-parse HEAD
```

The Wan checkout must be clean and the final command must print exactly
`9737cba9c1c3c4d04b33fcad41c111989865d315`.

## Use short external paths

The runner accepts absolute paths in `configs/m0.wan21.toml`. Environment
variables are preferred because they keep the tracked configuration unchanged:

```bash
export HIVEFRAME_WAN_CODE_DIR=/opt/wan21
export HIVEFRAME_MODEL_DIR=/mnt/models/wan21-1.3b
export HIVEFRAME_HF_CACHE_DIR=/mnt/cache/huggingface
export HIVEFRAME_M0_REPORT_DIR=/mnt/results/hiveframe-m0
```

Supported overrides:

| Variable | Purpose |
|---|---|
| `HIVEFRAME_WAN_CODE_DIR` | Pinned official Wan source checkout |
| `HIVEFRAME_MODEL_DIR` | Final checkpoint directory |
| `HIVEFRAME_HF_CACHE_DIR` | Hugging Face cache and temporary files |
| `HIVEFRAME_M0_REPORT_DIR` | Preflight, gates, videos, logs, instrumentation, and receipts |

Windows also accepts short absolute paths. For example:

```powershell
$env:HIVEFRAME_WAN_CODE_DIR = 'D:\wan'
$env:HIVEFRAME_MODEL_DIR = 'D:\models\wan13'
$env:HIVEFRAME_HF_CACHE_DIR = 'D:\hf-cache'
$env:HIVEFRAME_M0_REPORT_DIR = 'D:\m0'
```

Run `download-plan` after setting the variables. Its printed destinations are
the authoritative paths for the pending approval:

```bash
python hiveframe_m0.py download-plan
python hiveframe_m0.py preflight
```

Before approval, `preflight` is expected to remain blocked only where the
checkpoint is absent. Do not treat that expected blocker as a failed setup.

## Checkpoint download and revision verification

The admitted checkpoint remains:

```text
Wan-AI/Wan2.1-T2V-1.3B
revision 37ec512624d61f7aa208f7ea8140a131f93afc9a
```

Only after explicit download approval, use the exact repository, revision,
cache, and destination printed by `download-plan`. The equivalent Linux command
is:

```bash
HF_HOME="$HIVEFRAME_HF_CACHE_DIR" huggingface-cli download \
  Wan-AI/Wan2.1-T2V-1.3B \
  --revision 37ec512624d61f7aa208f7ea8140a131f93afc9a \
  --local-dir "$HIVEFRAME_MODEL_DIR"
```

Then verify the admitted large files by size and SHA-256:

```bash
python hiveframe_m0.py verify-model --full
python hiveframe_m0.py preflight
```

The revision is enforced by the download command. `verify-model --full`
independently checks the pinned SHA-256 values for the VAE, DiT, and T5 files.
It does not claim a full hash manifest for every small metadata file.

## Enforced execution sequence

Use one result root consistently so the gate receipts remain together:

```bash
# 1. One low-cost smoke generation.
python hiveframe_m0.py smoke

# 2-4. One command loads the model once, then produces cold and warm outputs
# with the same prompt and seed and evaluates their SHA-256 reproducibility.
python hiveframe_m0.py run --prompt-id static-speaking-person

# 5. Run the ten canonical prompts only after both gates pass.
python hiveframe_m0.py run-suite
```

There are no separate cold and warm commands. `run` executes them consecutively
inside one process so model state and runtime caches are comparable. A hash
mismatch fails the reproducibility gate and blocks the canonical suite.

## Result collection

With `HIVEFRAME_M0_REPORT_DIR=/mnt/results/hiveframe-m0`, collect:

```text
/mnt/results/hiveframe-m0/
├── preflight.json
├── gates.json
└── runs/
    ├── *.receipt.json
    ├── *.instrumentation.json
    ├── *.stdout.log
    ├── *.stderr.log
    ├── *.cold.mp4
    ├── *.warm.mp4
    └── suite.summary.json
```

Copy the entire report root, not only the videos. The receipts refer to the
instrumentation, logs, hashes, environment fingerprint, and gate state needed
to audit M0.

## Official compatibility references

- [Pinned Wan 2.1 README](https://github.com/Wan-Video/Wan2.1/blob/9737cba9c1c3c4d04b33fcad41c111989865d315/README.md)
- [PyTorch 2.4 installation matrix](https://docs.pytorch.org/get-started/previous-versions/#v241)
- [CUDA 12.4 toolkit and driver requirements](https://docs.nvidia.com/cuda/archive/12.4.0/cuda-toolkit-release-notes/index.html)
- [FlashAttention requirements](https://github.com/Dao-AILab/flash-attention#installation-and-features)

## Stop conditions

Stop before model execution if any of the following is true:

- the HIVEFRAME or Wan Git revision differs from the approved commit;
- `torch.cuda.is_available()` is false;
- the CUDA, PyTorch, TorchVision, or FlashAttention combination fails import;
- `download-plan` prints an unexpected repository, revision, size, or path;
- `verify-model --full` reports a size or SHA-256 mismatch;
- preflight reports any blocker after the approved checkpoint is installed.
