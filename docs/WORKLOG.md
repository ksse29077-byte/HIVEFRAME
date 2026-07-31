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

## 2026-07-31 — Compound-eye architecture RFC implemented

### Purpose

Reframe HIVEFRAME from an output-only patch-centric runtime into a compound-eye
input and selective-generation hypothesis while preserving M0 and legacy
assets.

### Change

- Preserved the pre-rebase snapshot with annotated tag
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

Architecture commit:

`041311bf6c3aad144f1a64980a36fd399c6c17d8`

### Unproven

- backend selector feasibility;
- lower CUDA kernel/token work;
- quality parity;
- end-to-end speedup;
- second-backend portability;
- commercial acceptance.

### Publication state

- repository visibility: `PUBLIC`;
- branch push: `published`;
- annotated tag push: `published`;
- RFC Issue:
  [`#32`](https://github.com/ksse29077-byte/HIVEFRAME/issues/32);
- Draft PR:
  [`#33`](https://github.com/ksse29077-byte/HIVEFRAME/pull/33).

The RFC branch and tag were published with normal Git transport. Commit
`041311bf6c3aad144f1a64980a36fd399c6c17d8` remains an exact ancestor of the
remote branch. The tag resolves to the preserved pre-rebase commit. No GitHub
Contents API reconstruction was used, and `main` was not modified.

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
- Publication of the operating-log commit was verified later with the RFC
  branch; Issue and Draft PR remained pending.

---

## 2026-07-31 — Compound I/O roadmap reconciliation

### Purpose

Make the adaptive Compound I/O M0–M8 sequence the official roadmap while
preserving M0 evidence and the patch-centric comparison design.

### Change

- Replaced the milestone sequence in `ROADMAP.md`.
- Added normative `ROADMAP_EXECUTION_RULES.md`.
- Added a dated reconciliation record under `docs/worklogs/`.
- Aligned README, charter, architecture, tasks, and operating handoff.
- Corrected repository visibility to `PUBLIC`.

### Publication and review

The changes remain isolated on `agent/compound-eye-architecture-v1`. They are
not written directly to `main`. RFC Issue
[`#32`](https://github.com/ksse29077-byte/HIVEFRAME/issues/32) and Draft PR
[`#33`](https://github.com/ksse29077-byte/HIVEFRAME/pull/33) provide the review
surface.

### Verification

- Python compile: passed in the existing isolated environment.
- Python unittest: 59 passed.
- Rust `cargo check --workspace --locked`: passed.
- JSON Schema parsing: 6 files passed.
- `git diff --check`: passed.
- Model load: 0.
- CUDA execution: 0.

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
