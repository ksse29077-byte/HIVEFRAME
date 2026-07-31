# HIVEFRAME Agent Rules

This file defines repository-local operating rules for Codex and other
automation agents.

## Required reading order

Before changing the repository, read:

1. `README_FIRST.md`
2. `TASKS.md`
3. `docs/WORKLOG.md`
4. `HIVEFRAME_MASTER_WORK_ORDER.md`
5. the architecture or M0 document relevant to the requested task

Do not infer completion from plans. Verify the current Git state and the
evidence linked from the worklog.

## Assets that must be preserved

- the existing repository and full Git history;
- M0 Wan baseline code, configuration, environment records, receipts, videos,
  smoke gates, reproducibility evidence, and memory-admission evidence;
- `schemas/run_receipt.schema.json` compatibility and existing receipt
  meanings;
- backend adapters, evaluators, model/license records, and data ledger;
- the legacy patch-centric design and tag `pre-compound-eye-v1`;
- user changes and unrelated files in a dirty worktree.

Never rewrite historical receipts or reinterpret an admission run as an
official quality or performance baseline.

## Research truthfulness

- Compound-eye execution is a falsifiable hypothesis, not a proven speedup.
- A `ComputePlan` is not proof that backend computation was skipped.
- Count observation, fusion, planning, generation, boundary, audit, repair,
  fallback, and output costs.
- Keep CUDA event span separate from profiler GPU-kernel duration.
- Unsupported or uncollected metrics use `null`, status, reason, and method;
  never substitute zero.
- Use same-condition comparisons for checkpoint, resolution, frames, FPS,
  steps, scheduler, precision, seed policy, VAE scope, and hardware class.

## Change discipline

- Use the smallest change that satisfies the current milestone.
- Do not add model training, new checkpoints, model downloads, CUDA kernels,
  multi-GPU, or GUI work unless the user explicitly expands the scope.
- Do not load Wan or run GPU generation during model-free architecture work.
- Run model-free tests before committing.
- Stage only files belonging to the task.
- Do not amend or rewrite commits that predate the current task.
- Do not push, tag remotely, create an Issue, or create a PR without explicit
  authorization for the exact GitHub repository.

## Minimum model-free verification

From the repository root:

```bash
PYTHONPATH=python python -m compileall -q python
PYTHONPATH=python python -m unittest discover -s python/tests
cargo check --workspace --locked
git diff --check
```

If an expected tool is missing, record the limitation instead of reporting a
pass.

## Worklog update

Every intentional change must update `docs/WORKLOG.md` when it changes:

- verified state;
- architecture decisions;
- milestone or gate status;
- commands or test results;
- failures, blockers, unsupported capabilities, or reversibility.

Keep plans in `TASKS.md` and evidence in the worklog. Do not duplicate full
design documents in the log.
