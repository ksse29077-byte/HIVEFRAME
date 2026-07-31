# HIVEFRAME Worklog

This document records verified implementation, validation, publication, and
blocker history. Plans belong in `../TASKS.md`; detailed designs belong in
their architecture documents.

## Recording rules

- Separate verified facts from proposals and expectations.
- Do not mark a branch, tag, commit, Issue, PR, CI result, or performance value
  as published until it is verified remotely.
- Include the full cost scope with every performance record.
- Record failures, unsupported capabilities, fallback, repair, and partial
  evidence.
- For decisions, record what changed, why, evidence, and rollback path.

## Status labels

| Label | Meaning |
|---|---|
| `planned` | not executed |
| `implemented` | files exist but verification is incomplete |
| `verified` | declared checks passed |
| `published` | remote object was verified |
| `blocked` | an external requirement prevents progress |
| `unsupported` | the current environment or backend cannot provide it |

---

## 2026-07-31 — M0 evidence preserved

### Verified state

- Official Wan 2.1 T2V 1.3B model and code revisions were pinned.
- RTX 3060 WSL2 CUDA, BF16, and FlashAttention paths were validated.
- Smoke and regression Smoke completed.
- A 17-frame, 4-step cold/warm pair completed and identical-seed output hashes
  matched.
- Receipt schema 0.2.0 separated CUDA event span from GPU-kernel duration and
  separated generation/process/system memory scopes.
- A 49-frame, 1-step memory-admission probe completed without OOM.

### Meaning limits

- Memory admission is a safety test, not a quality or speed baseline.
- Kernel profiler was disabled in official wall-clock runs; GPU-kernel duration
  remains `null/not_collected`.
- Existing receipts and artifacts remain external to Git tracking and are not
  rewritten.

---

## 2026-07-31 — Compound-eye architecture RFC implemented locally

### Purpose

Reframe HIVEFRAME from an output-only patch-centric runtime into a compound-eye
input and selective-generation hypothesis while preserving M0 and legacy
assets.

### Change

- Preserved the pre-rebase snapshot with local tag
  `pre-compound-eye-v1` at
  `2bc35ff4a0d442dc5fa43924d719de942960762b`.
- Created branch `agent/compound-eye-architecture-v1`.
- Preserved the legacy design in
  `docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md`.
- Added four RFC documents and four JSON Schema drafts.
- Added model-free `hive_eyes`, `hive_fusion`, `hive_visual_state`, and
  `hive_probes` packages.
- Added deterministic synthetic global, fixed 2×2 regional,
  overlap-boundary, and frame-difference motion eyes.
- Added source/confidence-preserving fusion, dirty/stable/uncertain state, and
  candidate compute planning.

### Verification

- Python compile: passed.
- Python unittest: 59 passed.
- Reference CLI with warnings treated as errors: passed.
- JSON artifacts produced: 5.
- Rust `cargo check --workspace --locked`: passed.
- `git diff --check`: passed after removing two Markdown trailing spaces.
- Model load: 0.
- CUDA execution: 0.

### Commit

Local commit:

`041311bf6c3aad144f1a64980a36fd399c6c17d8`

### Unproven

- backend selector feasibility;
- lower CUDA kernel/token work;
- quality parity;
- end-to-end speedup;
- second-backend portability;
- commercial acceptance.

### Publication state

- branch push: `blocked`;
- tag push: `blocked`;
- RFC Issue: not created;
- draft PR: not created.

Reason: external publication requires explicit approval for the exact private
GitHub repository and an authenticated GitHub write path. Do not report remote
links until verified.

### Rollback

The architecture RFC commit can be reviewed independently. The complete
pre-rebase code and documents remain reachable from `pre-compound-eye-v1` and
the parent commit.

---

## 2026-07-31 — Repository operating log added

### Purpose

Add a durable handoff and task-log structure modeled on the user-provided
example.

### Files

- `AGENTS.md`
- `README_FIRST.md`
- `CODEX_BOOTSTRAP_PROMPT.md`
- `CODEX_RUNBOOK.md`
- `HIVEFRAME_MASTER_WORK_ORDER.md`
- `docs/HIVEFRAME_COMPOUND_EYE_RUNTIME_ADDENDUM.md`
- `TASKS.md`
- `docs/WORKLOG.md`

### Decision

The files distinguish current truth, planned tasks, operating commands,
architecture boundaries, and chronological evidence. Existing design and M0
documents remain their own sources of truth and are linked rather than copied
into one oversized log.

### Verification

- Python compile: passed.
- Python unittest: 59 passed.
- Rust `cargo check --workspace --locked`: passed.
- `git diff --check`: passed.
- Model load: 0.
- CUDA execution: 0.
- Publication state remains unchanged and blocked pending explicit approval.

---

## Entry template

```markdown
## YYYY-MM-DD — Title

### Purpose

### Change

### Decision and rationale

### Verification environment

### Results and evidence

### Failure, unverified, unsupported

### Cost receipt

### Next action
```
