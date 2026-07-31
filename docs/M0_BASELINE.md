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

For transferring M0 to a compatible NVIDIA host, including the recommended
driver/CUDA/Python/PyTorch anchor, short external paths, gated command order,
and result collection, see
[`M0_CUDA_HOST_HANDOFF.md`](M0_CUDA_HOST_HANDOFF.md).

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

The default Windows paths are not mandatory. Absolute TOML paths and the
`HIVEFRAME_MODEL_DIR`, `HIVEFRAME_HF_CACHE_DIR`, `HIVEFRAME_WAN_CODE_DIR`, and
`HIVEFRAME_M0_REPORT_DIR` environment variables can select short external
paths without editing the tracked configuration.

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
# 1. Plan one low-cost pipeline check without loading the model
python hiveframe_m0.py smoke --run-id SMOKE_RUN_ID --plan

# 2. Execute the unique Smoke ID only with its approved settings hash
python hiveframe_m0.py smoke --run-id SMOKE_RUN_ID `
  --expect-settings-hash SMOKE_SETTINGS_HASH_FROM_PLAN

# 3. Inspect the exact low-cost cold/warm settings without loading the model
python hiveframe_m0.py run --profile smoke-cold-warm `
  --prompt-id static-speaking-person --plan

# 4. Execute only with the settings hash copied from the approved plan
python hiveframe_m0.py run --profile smoke-cold-warm `
  --prompt-id static-speaking-person `
  --expect-settings-hash SETTINGS_HASH_FROM_PLAN

# 5. Only after smoke and hash reproducibility pass
python hiveframe_m0.py run-suite
```

The smoke gate is tied to the project Git commit, code revision, model revision, and configuration hash. A changed input invalidates the gate. The canonical ten-prompt suite is a separate stage and cannot start until both smoke and cold/warm reproducibility gates pass.

`run` has no implicit profile. The caller must choose one of:

- `smoke-cold-warm`: 832x480, 17 frames, 16 FPS, 4 steps, repeat 2;
- `baseline-reproducibility`: 832x480, 49 frames, 16 FPS, 50 steps,
  repeat 2.

Both profiles retain the pinned prompt inputs, guidance 6.0, UniPC, BF16,
CUDA device, model CPU offload, and T5 CPU placement. The baseline profile is
preserved and is never silently replaced by the smoke-cost profile.

Use the same model-free plan flow before a baseline-cost pair:

```powershell
python hiveframe_m0.py run --profile baseline-reproducibility `
  --prompt-id static-speaking-person --plan
```

The plan prints `execution_started: false`, the selected profile, prompt ID,
complete effective settings, model/code revisions, expected run kind, settings
hash, resolved output directory, expected artifact paths, and any existing
collisions. Execution requires the exact hash through
`--expect-settings-hash`; a missing or different hash is rejected before
preflight or the model child process starts.

The `smoke` command uses the same plan and approval-hash validation path with
profile `smoke`, expected run kind `single regression smoke`, and repeat 1.
`--run-id` is required. It accepts only ASCII letters, digits, `.`, `_`, and
`-`; any existing artifact beginning with `<run-id>.` blocks execution before
preflight so earlier receipts, logs, and videos cannot be overwritten.
The same no-overwrite rule applies to `run`; there is no override flag.

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

New runs emit receipt schema `0.2.0`. Existing `0.1.0` receipts remain immutable
and are accepted by the compatibility schema. They are not rewritten to look
like new measurements.

Every v0.2 measurement carries:

- value and unit;
- scope and aggregation;
- measurement method;
- support status and unsupported reason;
- parent span;
- run label and repeat index.

Missing or inapplicable values are `null`, never invented as zero.

### CUDA event span is not kernel time

`cuda_event_span_seconds` is elapsed time between two events recorded on a CUDA
stream. It may include GPU idle time, CPU/offload delays between event
submission, synchronization, and work queued inside the enclosing operation.
It is useful as an accelerator-timeline span but is not the sum of GPU kernel
durations.

`gpu_kernel_seconds` is reserved for a separate
`torch.profiler`/CUPTI collection. The official wall-clock path keeps the
profiler disabled and records:

```text
value: null
support_status: not_collected
measurement_method: torch.profiler/CUPTI (disabled)
unsupported_reason: profiler overhead is excluded from official wall-clock
```

A profiling run must use the same pinned inputs but is diagnostic only.
`torch.profiler` adds CPU, GPU, memory, and synchronization overhead, so its
wall-clock cannot replace the official unprofiled result.

### Wall-clock hierarchy

The receipt distinguishes:

1. exact CLI-process exit duration — not internally collectible after process
   exit, so a parent launcher is required;
2. CLI entry through receipt assembly;
3. parent runner from child start through observed exit;
4. instrumented Wan child lifetime;
5. model load;
6. each repeated run;
7. generation, prompt, denoising, VAE, and MP4 encode spans;
8. setup/finalization and unattributed remainders.

Parent/child relationships are explicit. Remainders subtract only
non-overlapping direct children and are clamped at zero. Windows shell startup
and WSL distribution startup are outside the internal runner and are never
reported as internal end-to-end latency.

### VRAM

The receipt keeps these scopes separate:

- per-generation allocated/reserved peak after resetting allocator peak stats;
- allocated/reserved current value immediately after generation;
- process peak across model load and every reset window;
- final process current value;
- 0.5-second NVIDIA system-wide sampled peak.

Allocated bytes describe tensor memory known to PyTorch. Reserved bytes describe
memory managed by the caching allocator and are not proof of simultaneous
physical residency. NVIDIA sampling covers the entire selected GPU, can include
other processes, and can miss short spikes. The allocator backend, both
`PYTORCH_ALLOC_CONF` names, device total memory, and supported pool statistics
are recorded with the run.

### Host RAM

Linux/WSL runs enumerate descendants through `/proc`, sample main-process RSS,
descendant RSS, and the aggregate process tree, and retain separate peaks.
Platforms without process-tree enumeration retain the main-process value and
mark descendant/tree measurements unsupported with a reason.

T2V has no input VAE encode stage, so that field is `null` with a
not-applicable reason. Scheduler-only overhead is not isolated by the
non-invasive hook; it remains `null` with a reason instead of being estimated.

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

Each explicit reproducibility profile loads the model once, then runs the same
prompt and seed twice:

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
