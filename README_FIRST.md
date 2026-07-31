# Read This First — HIVEFRAME

## Current repository state

As of 2026-07-31:

- official Compound I/O architecture and roadmap are merged into `main`;
- architecture RFC commit before this worklog addition:
  `041311bf6c3aad144f1a64980a36fd399c6c17d8`;
- preserved pre-rebase tag: `pre-compound-eye-v1` at
  `2bc35ff4a0d442dc5fa43924d719de942960762b`;
- M0 Smoke, regression Smoke, cold/warm, same-seed reproducibility, and
  49-frame memory admission have succeeded on the recorded RTX 3060 host;
- compound-eye schemas and NumPy reference simulation passed 59 model-free
  Python tests and the Rust workspace check;
- repository visibility is `PUBLIC`;
- the RFC branch and annotated preservation tag are published with exact Git
  history;
- RFC Issue
  [`#32`](https://github.com/ksse29077-byte/HIVEFRAME/issues/32) is closed and
  PR [`#33`](https://github.com/ksse29077-byte/HIVEFRAME/pull/33) is merged;
- the model-free Rust I/O admission result is `CONDITIONAL_ADMIT`, not a model
  or product speedup claim;
- Rust I/O PR #36 is merged at `a71eea7...`;
- M1-P0 is `REFINE_COST_MODEL`, not M1 entry or completion.

Always run `git status -sb` and `git rev-parse HEAD` before relying on this
snapshot.

## What HIVEFRAME is

HIVEFRAME is researching a compound-eye input and selective-generation runtime.
Logical eyes create small purpose-specific observations, Sensory Fusion builds
a provenance-preserving shared state, and a compiler proposes backend-neutral
compute selectors.

This is not yet evidence of sparse speedup. The product goal is to reduce
accepted-result wall time and GPU cost after including every new overhead.

## What M0 means

M0 is preserved as **Single-Eye Cost Truth**. It is the pinned Wan baseline
against which future selective execution must be compared. Do not delete,
bypass, weaken, or silently rerun it.

## Start in this order

1. Read `TASKS.md` for current work and blockers.
2. Read `docs/WORKLOG.md` for verified history.
3. Read `HIVEFRAME_MASTER_WORK_ORDER.md` for project boundaries.
4. Read `ARCHITECTURE.md` and
   `docs/HIVEFRAME_COMPOUND_EYE_RUNTIME_ADDENDUM.md`.
5. For M0 work, read `docs/M0_BASELINE.md`.
6. For compound-eye experiments, read:
   - `ROADMAP.md`
   - `docs/ROADMAP_EXECUTION_RULES.md`
   - `docs/COMPOUND_EYE_HYPOTHESIS.md`
   - `docs/COMPOUND_EYE_ARCHITECTURE.md`
   - `docs/EXPERIMENT_PROTOCOL_EYE_V0.md`
   - `docs/DECISION_GATES_COMPOUND_EYE.md`

## Immediate next action

Refine the M1-P0 absolute cost calibration on the same five measured
combinations before expanding to the rights-cleared M1 Topology Cost Surface.
Treat the Rust I/O result as supporting evidence only; a separate approved
shared-buffer or PyO3 probe must measure process/FFI cost before production
migration.

Do not modify Wan hooks or claim backend speedup from the model-free plan.
