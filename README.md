# HIVEFRAME

New contributors and Codex sessions should begin with
[`README_FIRST.md`](README_FIRST.md), then check [`TASKS.md`](TASKS.md) and
[`docs/WORKLOG.md`](docs/WORKLOG.md) before changing the repository.

HIVEFRAME is a research-first selective-recompute runtime for pretrained video
generation and editing. Its product objective is to reduce complete
accepted-result inference cost through safe state reuse and backend-admitted
selective recomputation. Compound observation is one candidate evidence
mechanism, not the product objective or backend execution authority.

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
The official selective-recompute sequence and preserved historical Compound
I/O expansion are both recorded in
[`ROADMAP.md`](ROADMAP.md); its evidence and advancement rules are normative in
[`docs/ROADMAP_EXECUTION_RULES.md`](docs/ROADMAP_EXECUTION_RULES.md).

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

- Primary product backend target: MiniMax H3. P0 has verified one local
  text-to-video product path through loopback ComfyUI on the supplied approved
  workflow and assets. This is a single `verified_once` smoke, not a quality,
  speed, cost, selective-compute, or production-default admission.
- Optional H3 API admission remains separate in Issue #39; the local product
  path does not call an external MiniMax API or require an API key.
- The next product step is a separately approved P1 one-click Local H3
  launcher. Public knowledge stores logical IDs and non-sensitive capability
  evidence; models, outputs, prompts, full receipts, and runtime logs stay
  outside Git.
- Frozen legacy comparator: Wan 2.1 T2V 1.3B. Existing M0 code, receipts,
  fingerprints, and reports remain immutable evidence; no new Wan feature work
  is implied.
- Inactive backend: LTX-2. Historical code and documents remain preserved, but
  it is removed from active development scope.

API availability is not HIVEFRAME support, and no H3 speedup is claimed.
Checkpoint licenses, model cards, API terms, and distribution terms must be
verified before use. See [MODEL_LICENSE_MATRIX.md](MODEL_LICENSE_MATRIX.md).

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
  --output-dir reports/compound-eye-v0
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

M0 Full Compute Cost Truth → M1-A Real-video Observation Corpus → M1-B0
Model-free Locality Opportunity → M1-B1 Backend Capability Admission → M1-B2
Controlled Selective Recompute Probe → M1-B3 Parallel Scaling Surface → M2–M4
planning, reuse, and compiler integration → M5 End-to-End Net Gain. The earlier
Compound I/O M0–M8 expansion remains preserved in the roadmap as historical
architecture context.

See [ROADMAP.md](ROADMAP.md) for milestone questions and exit gates, and
[Roadmap execution rules](docs/ROADMAP_EXECUTION_RULES.md) for the
same-condition, complete-cost, safety, evidence, and publication policy. The
earlier patch-centric milestones remain preserved as comparison and execution
assets; they were not deleted.

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
- [Roadmap execution rules](docs/ROADMAP_EXECUTION_RULES.md)
- [Evaluation and benchmark protocol](docs/EVALUATION.md)
- [Risk, pivot, and IP notes](docs/RISKS_AND_IP.md)
- [CLI goals](docs/CLI_GOALS.md)

## License

No project license has been selected yet. Until one is added, all repository content remains under the copyright holder's default rights. Model weights and datasets are governed separately and must pass the admission rules in the model/license matrix and data ledger.
