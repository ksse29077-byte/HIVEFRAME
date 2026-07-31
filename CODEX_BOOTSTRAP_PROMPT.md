# Codex Bootstrap Prompt — HIVEFRAME

Copy the prompt below into a new Codex task when this work must be resumed.

```text
Continue the existing HIVEFRAME repository. Do not create or replace the
repository, discard Git history, or rewrite completed M0 evidence.

First read AGENTS.md, README_FIRST.md, TASKS.md, docs/WORKLOG.md,
HIVEFRAME_MASTER_WORK_ORDER.md, ARCHITECTURE.md, and the document relevant to
the requested milestone.

Before changing files, report:
- repository path;
- branch and full HEAD;
- worktree status;
- local/remote divergence;
- applicable task and gate;
- whether the requested work may load a model, use CUDA, download data, or
  change external GitHub state.

Preserve:
- Wan M0 runner, adapters, environment and license records;
- Smoke, cold/warm, reproducibility, memory-admission, receipts, and artifacts;
- RunReceipt schema compatibility and timing semantics;
- pre-compound-eye-v1 and the legacy patch-centric design;
- unrelated user changes.

Compound-eye architecture remains a falsifiable research hypothesis. Never
report a ComputePlan as actual sparse execution. Include observation, fusion,
planning, generation, boundary, audit, repair, fallback, and output costs in
any future speed claim. Unsupported metrics must be null with status, reason,
and measurement method.

Use model-free validation unless the user explicitly authorizes GPU work:
PYTHONPATH=python python -m compileall -q python
PYTHONPATH=python python -m unittest discover -s python/tests
cargo check --workspace --locked
git diff --check

Update TASKS.md and docs/WORKLOG.md with verified results, blockers, exact
commands, commit IDs, and links. Do not push or create GitHub state without
explicit approval for the exact repository.
```
