# 2026-07-31 — Compound I/O Roadmap Reconciliation

Status: implemented on RFC branch; final review pending

## Purpose

Reconcile the original output-side patch-centric roadmap, completed M0 work,
the compound-eye architecture RFC, and the adaptive Compound I/O product
direction without deleting evidence or overstating performance.

## Verified repository state

- Repository: `ksse29077-byte/HIVEFRAME`
- Visibility: `PUBLIC`
- Default branch: `main`
- RFC branch: `agent/compound-eye-architecture-v1`
- Preserved architecture commit:
  `041311bf6c3aad144f1a64980a36fd399c6c17d8`
- Preservation tag: `pre-compound-eye-v1`
- Tag target:
  `2bc35ff4a0d442dc5fa43924d719de942960762b`

The RFC branch and annotated tag were published with normal Git transport.
The remote RFC branch contains `041311b...` as an exact ancestor. No GitHub
Contents API reconstruction was used and `main` was not modified.

## Preserved assets

- full repository history;
- M0 Wan runner, backend adapter, evaluator, configurations, environment and
  license ledgers;
- Smoke, regression Smoke, cold/warm, reproducibility, memory admission, and
  Receipt 0.2.0 evidence;
- immutable historical receipt meanings;
- patch scheduler, boundary, cache, repair, and evaluator design assets;
- `docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md`;
- tag `pre-compound-eye-v1`.

## Reconciliation decision

The official roadmap now treats HIVEFRAME as a Compound I/O runtime that may
choose a 1×1 Mono Eye or multiple purpose-specific eyes. Eye count is a
topology variable, not a success metric.

The milestone sequence is:

1. M0 Single-Eye Cost Truth;
2. M1 Eye Topology Ground Truth Lab;
3. M2 Scout Eye and Adaptive Topology Planner;
4. M3 Sensory Fusion and Dynamic Eye Activation;
5. M4 Perception-to-Compute Compiler;
6. M5 Compound I/O Net Gain;
7. M6 Closed-Loop Adaptive Retina;
8. M7 Temporal Eye Swarm and Backend Independence;
9. M8 Commercial Compound Visual Engine.

The old Directed Regional Repair, Patch Runtime Parity, BoundaryPacket,
Temporal Cache, and repair work remain inputs to M4–M7 rather than being
discarded.

## Evidence boundary

The current RFC proves only model-free contract behavior:

- deterministic logical eyes;
- receptive and write-scope validation;
- synthetic motion detection;
- provenance-preserving fusion;
- dirty/stable/uncertain state;
- backend-neutral candidate planning.

It does not prove backend selector feasibility, fewer kernels/tokens, quality
parity, end-to-end speedup, backend independence, or commercial value.

## Documentation changes

- replaced `ROADMAP.md` with the official Compound I/O M0–M8 roadmap;
- added `docs/ROADMAP_EXECUTION_RULES.md`;
- added this dated reconciliation record;
- aligned README, charter, and architecture references;
- corrected repository visibility from private/unknown to public;
- removed personal local absolute paths from public Markdown documentation.

## Validation

- Python compile: passed;
- existing Python suite: 59 passed;
- Cargo workspace check: passed;
- JSON Schema parsing: 6 files passed;
- `git diff --check`: passed;
- model loads: 0;
- CUDA runs: 0.

## Rollback and review

The Draft PR can be closed without changing `main`. The previous architecture
remains at the preservation tag, and every roadmap change is isolated on the
RFC branch for review.
