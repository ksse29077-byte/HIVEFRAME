# HIVEFRAME

HIVEFRAME is a research-first runtime for hierarchical visual swarm video generation and editing. It explores whether a shared-weight video diffusion backend can reduce real end-to-end work by scheduling logical visual workers over latent patches, exchanging bounded neighbor context, and reusing stable temporal state without sacrificing global quality or constraints.

> Status: pre-alpha research scaffold. The first implementation priority is **M0 — Reproducible Baseline**. Training and GUI work are intentionally deferred.

## Core thesis

HIVEFRAME treats patch execution as a runtime concern rather than a collection of independently replicated models:

- a central `SceneContract` expresses geometry, identity, depth, motion, and write permissions;
- deterministic compilation turns the contract into patch-local work and dependency closures;
- logical workers share base-model weights;
- a boundary bus exchanges compact halo and semantic packets;
- temporal cache decisions skip only work proven stable;
- every run emits a receipt covering time, memory, transferred bytes, cache behavior, quality, hashes, and environment.

The two decisive research questions are:

1. How much of an existing video DiT's global computation can be localized in practice?
2. Do skip, cache, and neighbor exchange save more work than orchestration costs?

## Project rules

- Reproduce and measure the baseline before optimization.
- Compare identical resolution, frame count, seed, scheduler, steps, precision, and decode scope.
- Count wall time, GPU time, VAE time, communication, scheduling, and repair.
- Never hide seam defects with blur or count evaluator misses as successes.
- Do not begin adapter training until structural savings, failure attribution, and measurable targets are demonstrated.
- Escalate or fail explicitly when local execution is unsafe; never silently corrupt the full result.

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
