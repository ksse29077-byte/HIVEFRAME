# HIVEFRAME Tasks

Status date: 2026-07-31

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

Overall pre-gate status: `blocked`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve existing Analytical Topology Pruning work | `in_progress` | WIP must not be deleted or recreated |
| Draft cost equations, schemas, synthetic cases, unavailable-metric handling, and pre-rejection rules | `in_progress` | allowed before the dependency merges |
| Use Rust I/O measurements as fixed Amdahl inputs | `blocked` | [Rust I/O PR #36](https://github.com/ksse29077-byte/HIVEFRAME/pull/36) is Draft/Open and not merged into `main` |
| Run final benchmark or issue a topology Gate decision | `blocked` | requires the Rust probe report, commit, and measurement semantics from merged `main` |
| Publish an Analytical branch or PR | `blocked` | rebase onto post-merge `origin/main` first |

M1-P0 does not start or close M1, does not close M0, and cannot emit
`PROCEED_TO_COST_SURFACE` or another final Gate decision while PR #36 remains
unmerged.

## M1 — Exact next experiment

Supporting evidence:

| Task | Status | Evidence |
|---|---|---|
| Model-free Rust I/O admission | `published` | 15-case parity and benchmark are in Draft PR #36; not yet merged into `main` |
| Rust migration decision | `implemented` | `CONDITIONAL_ADMIT` is recorded on the probe branch; it is not an M0/M1 Gate decision |

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
