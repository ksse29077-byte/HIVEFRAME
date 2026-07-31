# HIVEFRAME

HIVEFRAME is a research-first compound-eye visual runtime for video generation
and editing. It explores whether small, purpose-specific logical eyes can
observe change before generation, fuse that evidence into a shared visual
state, and selectively schedule backend work without sacrificing global
quality, constraints, or failure safety.

> Status: pre-alpha research scaffold. The first implementation priority is **M0 — Reproducible Baseline**. Training and GUI work are intentionally deferred.

## Core thesis

- `EyeContract` assigns spatial, temporal, resolution, and semantic receptive
  purposes without copying the full input for every eye.
- Each eye emits a small `EyeObservation`.
- Sensory Fusion creates a provenance-preserving `SharedVisualState`.
- A deterministic compiler produces a `ComputePlan` for patch, token, block,
  timestep, resolution, or cache candidates.
- Backend adapters translate only supported selectors and preserve shared
  model weights.
- Boundary, temporal-cache, evaluator, and repair mechanisms remain safety
  layers.
- Every real claim is measured against M0 Single-Eye Cost Truth with all
  observation and orchestration overhead included.

This is an architecture hypothesis, not a speedup claim. See
[`docs/COMPOUND_EYE_HYPOTHESIS.md`](docs/COMPOUND_EYE_HYPOTHESIS.md) and the
preserved
[`docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md`](docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md).

## Project rules

- Reproduce and measure the baseline before optimization.
- Compare identical resolution, frame count, seed, scheduler, steps, precision, and decode scope.
- Count wall time, GPU time, VAE time, communication, scheduling, and repair.
- Never hide seam defects with blur or count evaluator misses as successes.
- Do not begin adapter training until structural savings, failure attribution, and measurable targets are demonstrated.
- Escalate or fail explicitly when local execution is unsafe; never silently corrupt the full result.
- Record unsupported metrics as `null` with status and reason; never invent a
  zero.

## Initial backend strategy

- Primary commercial rendering candidate: Wan 2.1, starting with the 1.3B path for baseline work.
- Reference path: Wan 2.2 TI2V-5B.
- Optional control and audio-video research backend: LTX-2.
- Base weights remain shared and frozen in the initial architecture.

All checkpoint licenses, model cards, and distribution terms must be re-verified and pinned before downloading or using weights. See [MODEL_LICENSE_MATRIX.md](MODEL_LICENSE_MATRIX.md).

## Repository map

```text
hiveframe/
├─ README.md
├─ PROJECT_CHARTER.md
├─ ARCHITECTURE.md
├─ MODEL_LICENSE_MATRIX.md
├─ ROADMAP.md
├─ Cargo.toml
├─ crates/
│  ├─ hive-contracts/
│  ├─ hive-director/
│  ├─ hive-constraint-compiler/
│  ├─ hive-patch-scheduler/
│  ├─ hive-boundary-bus/
│  ├─ hive-temporal-cache/
│  ├─ hive-evaluator/
│  └─ hive-cli/
├─ python/
│  ├─ hive_backends/
│  ├─ hive_hooks/
│  ├─ hive_training/
│  └─ hive_benchmarks/
├─ schemas/
├─ configs/
├─ benchmarks/
│  ├─ prompts/
│  ├─ canonical_clips/
│  └─ evaluators/
├─ data_ledger/
├─ reports/
└─ docs/
```

Compound-eye reference packages live under:

- `python/hive_eyes`;
- `python/hive_fusion`;
- `python/hive_visual_state`;
- `python/hive_probes`.

The four v0 interchange schemas are in `schemas/`. The reference path uses
NumPy only and does not load Wan, Torch, CUDA, or model weights.

## Model-free compound-eye probe

```bash
PYTHONPATH=python python -m hive_probes.compound_eye_v0 \
  --seed 101 \
  --output-dir /tmp/hiveframe-eye-v0
```

This emits contracts, observations, shared state, compute plan, and an
observation receipt. It does not satisfy an M0 backend gate or support a sparse
speedup claim.

## First run target

The scaffold does not download model weights or claim a working generation backend. M0 first establishes a deterministic receipt format and ten-prompt canonical baseline:

```bash
hiveframe baseline run --suite canonical-v0 --backend wan21
```

Target configuration is in [`configs/research.example.yaml`](configs/research.example.yaml). CLI behavior is specified in [`docs/CLI_GOALS.md`](docs/CLI_GOALS.md).

The implemented M0 preflight and receipt wrapper is documented in
[`docs/M0_BASELINE.md`](docs/M0_BASELINE.md). It reports the exact model
download plan without downloading weights:

```bash
python hiveframe_m0.py download-plan
python hiveframe_m0.py preflight
```

After an approved model setup on a compatible NVIDIA CUDA host, M0 enforces:

```bash
python hiveframe_m0.py smoke --run-id SMOKE_RUN_ID --plan
python hiveframe_m0.py smoke --run-id SMOKE_RUN_ID \
  --expect-settings-hash SMOKE_SETTINGS_HASH_FROM_PLAN
python hiveframe_m0.py run --profile smoke-cold-warm \
  --prompt-id static-speaking-person --plan
python hiveframe_m0.py run --profile smoke-cold-warm \
  --prompt-id static-speaking-person \
  --expect-settings-hash SETTINGS_HASH_FROM_PLAN
python hiveframe_m0.py run-suite
```

Smoke execution requires a unique `--run-id`; any existing artifact with that
ID blocks execution before preflight. Its model-free plan fixes repeat to one
and prints the approval hash required by the execution command.

`run` requires an explicit profile. `smoke-cold-warm` selects the 17-frame,
4-step smoke cost with two in-process generations. The preserved
`baseline-reproducibility` profile selects the 49-frame, 50-step baseline.
`--plan` loads neither the model nor CUDA and prints the exact settings hash
that must be approved and passed to the execution command.

The ten-prompt suite cannot run before the smoke and same-seed cold/warm
reproducibility gates pass.

Use [`docs/M0_CUDA_HOST_HANDOFF.md`](docs/M0_CUDA_HOST_HANDOFF.md) to move this
runner to an NVIDIA host, configure short external model/result paths, verify
the approved revision, and collect the complete receipt bundle.

The complete current-state Korean handoff for moving the repository,
environment, pinned Wan code, and verified checkpoint to another PC is
[`docs/M0_OTHER_PC_HANDOFF_KO.md`](docs/M0_OTHER_PC_HANDOFF_KO.md).

## Milestones

M0 Reproducible Baseline → M1 Directed Regional Repair → M2 Patch Runtime Parity → M3 Neighbor-Sealed Patches → M4 Constraint-Compliant Generation → M5 Temporal Sparse Gain → M6 Closed-loop Local Repair → M7 Backend-Independent Runtime → M8 Creator MVP.

See [ROADMAP.md](ROADMAP.md) for exit criteria and Sprint A–E.

## Success threshold for the sparse MVP

- at least 1.5× end-to-end speedup against the same backend baseline;
- no more than 2% relative quality loss, or non-inferiority in blind review;
- no meaningful increase in seam defects;
- at least 50% mean interior skip on the static suite;
- false-skip rate at or below 0.5%;
- at least 95% central-constraint compliance;
- bounded non-target change during local repair;
- explicit escalation or failure instead of silent degradation.

## Documentation

- [Project charter](PROJECT_CHARTER.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Evaluation and benchmark protocol](docs/EVALUATION.md)
- [Risk, pivot, and IP notes](docs/RISKS_AND_IP.md)
- [CLI goals](docs/CLI_GOALS.md)

## License

No project license has been selected yet. Until one is added, all repository content remains under the copyright holder's default rights. Model weights and datasets are governed separately and must pass the admission rules in the model/license matrix and data ledger.
