# HIVEFRAME Tasks

Status date: 2026-08-01

## Status legend

| Status | Meaning |
|---|---|
| `done` | verified evidence exists |
| `in_progress` | implementation exists but the task is not fully closed |
| `planned` | not started |
| `blocked` | external approval or state is required |
| `unsupported` | current environment/backend lacks the capability |

## R0 — Compound-eye architecture RFC

| Task | Status | Evidence or blocker |
|---|---|---|
| Verify repository visibility | `done` | GitHub reports `PUBLIC` |
| Preserve pre-rebase state | `published` | annotated tag `pre-compound-eye-v1` → `2bc35ff...` |
| Create RFC branch | `published` | `agent/compound-eye-architecture-v1` |
| Preserve patch-centric architecture | `done` | `docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md` |
| Add hypothesis, architecture, protocol, gates | `done` | four RFC documents |
| Add four JSON Schema drafts | `done` | `schemas/*eye*`, shared state, compute plan |
| Add model-free reference packages | `done` | `hive_eyes`, `hive_fusion`, `hive_visual_state`, `hive_probes` |
| Verify deterministic simulation | `done` | 59 Python tests at `041311b...` |
| Verify Rust workspace | `done` | `cargo check --workspace --locked` |
| Add operating worklog documents | `done` | operating documents; 59 Python tests and Rust check passed |
| Reconcile official Compound I/O roadmap | `verified` | RFC branch; 59 Python tests, Cargo, schemas, and diff check passed |
| Push RFC branch | `published` | exact local Git history verified remotely |
| Push preservation tag | `published` | annotated tag object and target verified remotely |
| Create RFC Issue | `published` | [Issue #32](https://github.com/ksse29077-byte/HIVEFRAME/issues/32) |
| Create Draft PR | `published` | [Draft PR #33](https://github.com/ksse29077-byte/HIVEFRAME/pull/33) |
| Confirm CI | `planned` | review checks on Draft PR #33 |

## M0 — Single-Eye Cost Truth

Overall milestone status: `in_progress`. Completed component rows below do not
close M0; the eligible canonical same-condition baseline and input-side cost
scopes remain outstanding.

| Task | Status |
|---|---|
| Pinned Wan code/checkpoint/license | `done` |
| RTX 3060 WSL CUDA/BF16/FlashAttention verification | `done` |
| Smoke and regression Smoke | `done` |
| Cold/warm and same-seed reproducibility | `done` |
| Receipt 0.2.0 measurement correction | `done` |
| 49-frame memory admission | `done` |
| Canonical same-condition official baseline | `planned` |
| Input-side cost extensions | `planned` |

## M1-P0 — Analytical Topology Pre-Gate

Overall pre-gate status: `verified`; decision `REFINE_COST_MODEL`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Search and preserve existing Analytical WIP | `verified` | no implementation found; new branch starts at post-PR36 main |
| Cost equations, synthetic cases, unavailable metrics, and pruning rules | `verified` | 9 analytical combinations |
| Use merged Rust I/O measurements | `verified` | local control-plane calibration only; Amdahl end-to-end remains unavailable |
| Minimal model-free probe | `verified` | 4 pruned, 5 measured at 5 warm-ups / 20 repetitions |
| M1-P0 decision | `verified` | `REFINE_COST_MODEL`; prediction error exceeded 35% twice |
| Publish Analytical branch and Draft PR | `published` | [Issue #37](https://github.com/ksse29077-byte/HIVEFRAME/issues/37), [Draft PR #38](https://github.com/ksse29077-byte/HIVEFRAME/pull/38) |

M1-P0 does not start or close M1 and does not close M0. Keep the same five
measured combinations and correct the cost model before another decision.

## M1-P0-R1 — Same-run Mono Cost Normalization

Overall refinement status: `verified`; decision `REFINE_COST_MODEL`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve v1 evidence and 35% threshold | `verified` | seven immutable v1 SHA-256 checks pass |
| Predeclare paired cost model and deterministic order | `verified` | config, design, runner, and 19 R1 tests |
| Keep the same five measured combinations | `verified` | 4 combinations remain analytically pruned; no corpus growth |
| Run 5 warm-up and 20 measured blocks | `verified` | 100 final measured samples in one process |
| Validate Case B paired deltas | `verified` | T1 error 61.83%; T2 error 56.60%; ranking matches |
| Preserve safety and deterministic semantics | `verified` | recall 1.0, false-stable 0.0, hashes match v1 |
| Publish and merge R1 | `published` | Issue #40 closed; [PR #41](https://github.com/ksse29077-byte/HIVEFRAME/pull/41) merged at `e5bbaa7...` |

Same-run pairing did not bring the Rust-derived incremental coefficients
within the unchanged 35% rule. Do not expand to the rights-cleared M1 Cost
Surface from this result. The next calibration change requires a separately
predeclared explanation of the missing Python topology-variable stages.

## M1-P0-R2 — Python Attribution and Rust Compound Runtime

Overall refinement status: `verified`; decision `REFINE_RUST_BOUNDARY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve v1 and R1 evidence | `verified` | sixteen merged Git-blob SHA-256 checks pass |
| Predeclare Python stage attribution | `verified` | inclusive/exclusive taxonomy, signed pairing, overhead calibration, fixed thresholds |
| Keep exact Case B T0/T1/T2 | `verified` | 20 paired blocks; no topology or corpus growth |
| Attribute Python Compound overhead | `verified` | T1 100.0606%, T2 99.8828%; every block equation holds |
| Add one coarse Rust batch boundary | `verified` | one packed input handoff, no per-Eye round trips |
| Verify semantic and copy safety | `verified` | R1/Python/Rust hashes equal; deterministic; exactly 2.0x input boundary copies |
| Decide R2 | `verified` | Rust T1/T2 core lower, but in-process FFI remains `null/not_collected` |
| Sanitize and normalize public R2 evidence | `verified` | Logical digest unchanged; private execution paths removed and semantic payloads stored once per candidate/hash |
| Publish R2 branch and Draft PR | `published` | [Issue #42](https://github.com/ksse29077-byte/HIVEFRAME/issues/42); [Draft PR #43](https://github.com/ksse29077-byte/HIVEFRAME/pull/43) |

Do not interpret the decision as `MONO_FIRST` or as rejection of Compound
Perception First. The next bounded runtime work is an in-process shared-buffer
boundary using the same Case B and semantic/copy contracts. H3 Issue #39
remains separate and no backend/model execution was performed.

## M1-P0-R3 — In-process Shared-buffer Boundary

Overall refinement status: `predeclared`; measurement pending.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve v1, R1, and R2 evidence | `verified` | immutable R2 Git objects are checked before plan or execution |
| Pin Python/Rust boundary | `verified` | Python 3.12, PyO3 0.29.0, `abi3-py312`, Rust MSRV 1.83 |
| Fix Case B T0/T1/T2 scope | `verified` | 5 warm-ups and 30 same-process paired blocks declared |
| Borrow one shared input buffer | `implemented` | read-only C-contiguous uint8 buffer; one Rust call per candidate; zero per-Eye calls |
| Predeclare thresholds and decisions | `verified` | config, contract receipt, tests, and Issue #44 |
| Execute R3 measurement | `pending` | permitted only from the immutable premeasurement commit and contract hash |
| Publish Draft PR | `pending` | do not mark ready or merge automatically |

R3 is a model-free control-plane experiment. It cannot close M0 or M1 and
cannot claim real-video, model, quality, or product speedup. Compound
Perception First remains the product direction; Mono remains the comparator
and safety fallback.

## Backend product target policy

| Task | Status | Evidence or blocker |
|---|---|---|
| Designate MiniMax H3 as primary product target | `verified` | policy only; no runtime or speedup claim |
| Review current official H3 API documentation | `verified` | V2 contract names `MiniMax-H3`; runtime admission remains pending |
| Admit official H3 API | `planned` | [Issue #39](https://github.com/ksse29077-byte/HIVEFRAME/issues/39); explicit approval required before API key or paid call |
| Admit future H3 open weights | `blocked` | official repository, checkpoint, source, license, digest, and runtime not jointly verified |
| Preserve Wan M0 comparator | `done` | frozen code, pins, receipts, fingerprints, and reports; no new feature development |
| Remove LTX from active scope | `done` | historical code and Git history retained; no cleanup in this change |
| Create backend capability matrix | `planned` | no standalone matrix exists; black-box/white-box evidence belongs to Issue #39 |

## M1 — Exact next experiment

Supporting evidence:

| Task | Status | Evidence |
|---|---|---|
| Model-free Rust I/O admission | `published` | merged through PR #36 at `a71eea7...` |
| Rust migration decision | `published` | `CONDITIONAL_ADMIT`; it is not an M0/M1 Gate decision |

1. Admit 12 small rights-cleared clips and record provenance.
2. Add oracle dirty masks and scene-cut labels.
3. Define candidate topologies including 1×1 Mono Eye.
4. Predeclare false-stable, recall, uncertainty, and cost thresholds.
5. Run model-free eyes against the oracle suite.
6. Record observation/fusion bytes, CPU wall time, and process-tree RAM.
7. Produce one observation receipt per clip and a suite summary.
8. Decide whether backend feasibility work may start.

Do not train a planner or modify Wan hooks before the M1 cost and safety map is
accepted.

## Maintenance checklist

- [ ] Update this file when task state changes.
- [ ] Add a dated entry to `docs/WORKLOG.md`.
- [ ] Link receipts, reports, commits, Issues, and PRs only after verification.
- [ ] Keep unsupported and unverified items explicit.
