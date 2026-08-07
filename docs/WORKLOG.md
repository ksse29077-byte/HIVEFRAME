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

## 2026-07-31 — Compound I/O RFC merged into main

### Verified state

- Compound I/O RFC PR
  [`#33`](https://github.com/ksse29077-byte/HIVEFRAME/pull/33) was merged into
  `main`.
- Merge commit:
  `237c298899ae9a5d46470d18255f7ff6a704bb65`.
- Merged at: `2026-07-31T07:33:59Z`.
- RFC Issue
  [`#32`](https://github.com/ksse29077-byte/HIVEFRAME/issues/32) was closed
  through merged PR #33.
- The official architecture and roadmap on `main` now use the Compound I/O
  definition.
- The next research milestone is **M1 — Eye Topology Ground Truth Lab**.

### Verification

- Python compile: passed.
- Python unittest: 59 passed.
- Rust `cargo check --workspace --locked`: passed.
- `git diff --check`: passed.
- Model load: 0.
- CUDA execution: 0.

---

## 2026-07-31 — Rust I/O admission evidence

### Purpose

Measure whether the model-free Compound I/O control-plane candidate preserves
Python semantics and merits a bounded Rust integration follow-up.

### Verified evidence

- 15 Python/Rust profile-topology cases achieved exact semantic SHA-256
  parity with integer-exact and `1e-9` float comparison.
- Five warm-ups and 30 measured repetitions were used per case.
- Rust p50 core latency was lower by 18.91–38.47%.
- Dominant temporary-buffer accounting was lower by 87.50–93.75%.
- Explicit pixel-buffer copies were zero in both paths.
- Decision: `CONDITIONAL_ADMIT`.

### Meaning limits

This is a model-free orchestration result, not a Wan, GPU, quality, product, or
commercial speedup claim. PyO3/FFI, DLPack, shared buffers, backend execution,
and attributable M0 end-to-end impact remain unmeasured.

Detailed methods and results are in
[`RUST_IO_ADMISSION_PROBE.md`](RUST_IO_ADMISSION_PROBE.md) and
[`reports/rust_io_admission`](../reports/rust_io_admission/).
Review is tracked in Issue
[`#35`](https://github.com/ksse29077-byte/HIVEFRAME/issues/35) and Draft PR
[`#36`](https://github.com/ksse29077-byte/HIVEFRAME/pull/36).

PR #36 was later merged at `2026-07-31T08:45:53Z` with merge commit
`a71eea742f5a804c30f6f095c1a256ee2d2561a6`; Issue #35 closed.

### Verification

Python compile passed; all 70 Python tests passed; Rust format, locked
workspace check, and workspace tests passed; JSON parsing and
`git diff --check` passed. Model loads: 0. CUDA runs: 0.

---

## 2026-07-31 — M1-P0 Analytical pre-gate hold

Analytical Topology Pruning is classified as `M1-P0`, not full M1 entry or
completion. M0 remains `in_progress`.

At the time of this hold, Rust I/O evidence was `CONDITIONAL_ADMIT` on Draft
PR #36 and was not yet merged into `main`. Final Analytical measurements,
fixed Amdahl inputs, Gate classification, completion, branch push, and PR
creation were blocked until that merge. The later M1-P0 entry below records
the resolved hold and resumed work.

No Analytical branch or implementation was visible in this checkout or its
known local/remote refs, so this correction created or modified no Analytical
code. Detailed hold conditions are recorded in
[`worklogs/2026-07-31-analytical-topology-pre-gate-wip.md`](worklogs/2026-07-31-analytical-topology-pre-gate-wip.md).

Model loads: 0. CUDA runs: 0. Analytical benchmark runs: 0.

---

## 2026-07-31 — M1-P0 Analytical Topology Pre-Gate

### Purpose

Eliminate structurally uneconomic T0/T1/T2 combinations before the
rights-cleared M1 Cost Surface and measure only the retained model-free
combinations.

### Verified result

- base main and Rust merge:
  `a71eea742f5a804c30f6f095c1a256ee2d2561a6`;
- no existing Analytical implementation was found;
- Issue:
  [`#37`](https://github.com/ksse29077-byte/HIVEFRAME/issues/37);
- implementation commit:
  `30ebdf0b3937c4e7a16dc4f72c7750437ff7dc53`;
- Draft PR:
  [`#38`](https://github.com/ksse29077-byte/HIVEFRAME/pull/38), open for
  review and not merged;
- analytical combinations: 9;
- pruned: Case A T1/T2 and Case C T1/T2;
- measured: five combinations, each with 5 warm-ups and 20 repetitions;
- Case B predicted/measured ranking: `T0 < T1 < T2`;
- dirty recall: 1.0;
- maximum false-stable: 0.0;
- Amdahl status: `partially_available`; M0 optimized fraction and end-to-end
  upper bound remain unavailable.

### Decision

`REFINE_COST_MODEL`.

Absolute p50 prediction exceeded the 35% threshold for Case A T0 and Case B
T2. Keep the same five measured combinations; normalize prediction to a
same-run Mono anchor and improve missing stage attribution before expanding
the corpus.

### Failure and correction

An initial analytical assumption incorrectly treated local T1/T2 as
full-canvas generate. A model-free integration test disproved it. Generation
scope geometry was corrected, Case B T1/T2 were retained, and superseded
development reports were excluded from evidence.

Detailed design, measurements, and limitations are in
[`M1_ANALYTICAL_TOPOLOGY_PRUNING.md`](M1_ANALYTICAL_TOPOLOGY_PRUNING.md) and
[`worklogs/2026-07-31-m1-p0-analytical-topology-pruning.md`](worklogs/2026-07-31-m1-p0-analytical-topology-pruning.md).

### Verification

- Python compile: passed.
- Python unittest: 88 passed.
- Rust format, locked workspace check, and workspace tests: passed.
- Schema, config, and result JSON parsing: passed.
- `git diff --check`: passed.

Model loads: 0. CUDA runs: 0.

---

## 2026-07-31 — Product backend target policy

### Decision

- MiniMax H3 is the highest-priority product backend target.
- H3 remains a pending black-box API admission; a future open-weight path is
  blocked until official source, weights, license, digest, and runtime are
  verified.
- Wan 2.1 T2V 1.3B is the frozen legacy comparator. Existing M0 code, pins,
  receipts, reproducibility evidence, fingerprints, and reports are immutable.
- LTX is inactive and removed from active development scope. Historical code
  and Git history remain intact.

### Verified source state

The official MiniMax V2 documentation reviewed on 2026-07-31 names model
`MiniMax-H3` and endpoint `POST /v2/video_generation`. Documentation
availability is not HIVEFRAME support. H3 price/billing, H3-specific data
handling, commercial fitness, runtime behavior, provenance, and receipt
integration remain unadmitted. No official H3 source, checkpoint, license, and
digest set was jointly verified for a white-box path.

Official API documentation is the technical source of truth. Secondary press
coverage was recorded only as launch context and supplied no admission facts.
Follow-up admission is tracked in Issue
[`#39`](https://github.com/ksse29077-byte/HIVEFRAME/issues/39).

### M1-P0 boundary

M1-P0 remains the same backend-neutral model-free analysis. No H3 value was
inserted into its cost model, and its `REFINE_COST_MODEL` decision is
unchanged. This is not H3 admission, H3 support, H3 speedup, M0 completion, or
M1 completion.

H3 API calls: 0. H3 model loads: 0. Paid API runs: 0. Model loads: 0. CUDA
runs: 0. Wan evidence changed: 0. Existing receipts deleted or rewritten: 0.

---

## 2026-08-01 — M1-P0-R1 same-run Mono normalization

### Verified result

- PR #38 merged at
  `ad091add498e5c8ec68b4cc5a03937c4d3d3cb62`; Issue #37 closed.
- R1 Issue [#40](https://github.com/ksse29077-byte/HIVEFRAME/issues/40) and
  Draft PR [#41](https://github.com/ksse29077-byte/HIVEFRAME/pull/41) are the
  review surfaces.
- The five v1 measured combinations and four analytical prunes were preserved.
- Five warm-up and twenty measured blocks produced 100 final model-free
  samples in one process.
- Same-block B/T1 and B/T2 paired errors were 61.83% and 56.60%; both exceed
  the unchanged 35% rule.
- Predicted and measured ranking matched (`T0 < T1 < T2`), dirty recall was
  1.0, false-stable was 0.0, and semantic hashes matched v1.
- Decision: `REFINE_COST_MODEL`.

The first attempt failed after measurement at result validation because an
Amdahl aggregate was mistaken for a leaf metric. Failure evidence is
preserved; the correction changed no formula, coefficient, order, threshold,
or Gate. Detailed evidence is in
[`worklogs/2026-08-01-m1-p0-r1-cost-model-refinement.md`](worklogs/2026-08-01-m1-p0-r1-cost-model-refinement.md).

Python compile and all 107 tests passed. Rust format, locked check, and locked
tests passed, including 8 runtime tests. JSON parsing and diff checks passed.
H3 API calls, API-key uses, paid runs, model downloads, model loads, and CUDA
runs were all 0. Wan evidence remained unchanged and LTX remained inactive.

---

## 2026-08-01 — M1-P0-R2 Python attribution and Rust compound runtime

### Verified result

- PR #41 merged at
  `e5bbaa751d7c449dd0c5a7ad3b7fff18bd661388`; Issue #40 closed.
- R2 Issue [#42](https://github.com/ksse29077-byte/HIVEFRAME/issues/42)
  and branch `agent/m1-p0-r2-rust-compound-runtime` are the review surfaces;
  [Draft PR #43](https://github.com/ksse29077-byte/HIVEFRAME/pull/43) is open
  and was not merged.
- Sixteen v1/R1 Git-blob hashes remained unchanged.
- Exact Case B T0/T1/T2 produced twenty paired Python records and twenty Rust
  samples per candidate without corpus or topology growth.
- Python paired p50 deltas were 8.5101 ms for T1 and 9.6737 ms for T2.
  Exclusive stage attribution was 100.0606% and 99.8828%; observation was the
  dominant delta, with an additional 2.1263 ms Eye-setup delta for T2.
- Rust boundary-inclusive p50 was 32.24% lower for T1 and 36.18% lower for T2
  under benchmark-suite amortization. This is not single-call product latency.
- Python, Rust, and R1 semantic hashes matched; deterministic and 2.0x copy
  gates passed.
- FFI remained `null/not_collected`; decision: `REFINE_RUST_BOUNDARY`.

Two ineligible attempts are preserved. Attempt 001 stopped before measured
blocks on a wrong input-profile identity. Attempt 002 was rejected after
measurement because its aggregate omitted Python wrapper time and failed to
evaluate one already-declared threshold. Corrective commits changed no stage
taxonomy, equation, numeric threshold, transport, or decision outcome.

The detailed record is
[`worklogs/2026-08-01-m1-p0-r2-rust-compound-runtime.md`](worklogs/2026-08-01-m1-p0-r2-rust-compound-runtime.md).

Python compile and all 119 tests passed. Rust format, locked check, and locked
tests passed, including 9 runtime tests. All 34 repository JSON files parsed,
the sixteen immutable Git-blob checks passed, and `git diff --check` passed.

H3 API calls, API-key uses, paid runs, model downloads, model loads, and CUDA
runs were all 0. Wan and R1 evidence remained unchanged; LTX stayed inactive.

---

## 2026-08-02 — M1-P0-R3 in-process shared-buffer admission

PR #43 is merged at `77cd34d3958bef28bfa6e3b8da1b03df2e44c503`
and Issue #42 is closed. R2 remains immutable with Gate
`REFINE_RUST_BOUNDARY`; Compound Perception First and the Mono
comparator/safety-fallback policy are preserved.

R3 Issue [#44](https://github.com/ksse29077-byte/HIVEFRAME/issues/44) and
branch `agent/m1-p0-r3-inprocess-shared-buffer` use one Python 3.12,
PyO3 0.29.0 shared-buffer call per Case B T0/T1/T2 candidate. The input is
borrowed read-only with zero input copies, subprocesses, temporary files, and
per-Eye FFI calls. Five warm-ups, thirty paired blocks, all timing/copy spans,
and the four Gate outcomes were frozen at premeasurement commit `3abbbea...`.

The single measurement produced 90 pairs. Rust boundary p50 was 20.80% lower
for T0, 31.21% lower for T1, and 35.98% lower for T2; all p95 values were
lower. Semantic parity was 100%, hashes were deterministic, and FFI+buffer+
marshal p50 remained below 0.2%. A 1,348-assertion independent audit passed.
Decision: `RUST_CONTROL_PLANE_ADMITTED`. M1-P0 is closable; the next research
surface is the separately approved, rights-cleared real-video M1 lab.

Python compile and all 140 tests passed. The Python 3.12 extension imported
and all 14 R3 tests passed. Rust format, locked workspace check, and locked
tests passed with 10 runtime tests. All 40 JSON files parsed; immutable
evidence, path/credential/address, semantic deduplication, and diff checks
passed.

Detailed record:
[`worklogs/2026-08-02-m1-p0-r3-inprocess-shared-buffer.md`](worklogs/2026-08-02-m1-p0-r3-inprocess-shared-buffer.md).

H3/API-key/paid/customer-data/model/CUDA/Wan/LTX counts were all 0. R3 is not
an official product or model-speedup claim.

PR #45 subsequently merged into `main` at
`156d955fa8edfbcb6157ef6e130454da0b165daf`, and Issue #44 closed. The admitted
R3 boundary completes M1-P0; no R4 is authorized. M0 remains independently
`in_progress`. The next separately approved stage is M1-A corpus and oracle
admission, not topology performance execution.

---

## 2026-08-02 — M1-A corpus and oracle protocol predeclared

The branch `agent/m1-a-real-video-corpus-oracle-protocol` starts from the PR
#45 merge commit. Duplicate repository, Issue, PR, and branch searches found no
existing M1-A implementation.

The metadata-only predeclaration fixes rights and consent admission, a
deterministic derivative, human-reviewed dirty/stable/uncertain/preserve and
scene-cut semantics, compact annotation references, T0–T7 contracts, complete
cost metrics, provisional safety thresholds, validators, and negative tests.
No actual clip is eligible at this checkpoint, no binary is tracked, and no
topology or backend is executed.

The available GitHub write integration rejected the initial Issue create
request, so no remote object changed at that attempt. After GitHub CLI
authentication was restored, [Issue #46](https://github.com/ksse29077-byte/HIVEFRAME/issues/46)
and the dedicated remote branch were published through the normal GitHub and
Git transport paths. Draft PR
[#47](https://github.com/ksse29077-byte/HIVEFRAME/pull/47) is open for review;
it was not marked ready or merged.

Predeclaration commit `d60fd7650d2a0a7d2fedf19d43d4638895f0e682`
fixed the contract before any admission. The allowed post-commit asset review
found no actual task-scoped clip. Eligible, pending, rejected, and investigated
actual-clip counts are all 0; all twelve scene classes are missing. The single
Gate is **`CORPUS_ACQUISITION_REQUIRED`**. No absent clip was given a synthetic
status, and no network video was downloaded. M1 topology measurement remains
blocked pending a separately reviewed acquisition pass.

Python compile and all 156 tests passed. Rust format, locked check, and locked
tests passed, including 10 runtime tests. Fifty-two repository/generated JSON
files parsed; the M1 Draft 2020-12 identifiers, validators, public sanitation,
duplicate checks, tracked-binary check, legacy evidence immutability, and diff
check passed. The optional `jsonschema` package was unavailable and was not
installed; dependency-free instance validators and positive/negative tests
were used.

Model downloads, model loads, CUDA runs, paid external calls, external
customer/personal-data transfers, backend integrations, and topology
performance runs: 0 each.

---

## 2026-08-02 — PR #43 final merge-readiness review

PR #43 remains draft and was not merged or marked ready. The predeclared Case
B scope, eighteen-stage taxonomy, attribution equation, Rust boundary,
thresholds, paired arithmetic, semantic parity, 78-execution amortization,
copy accounting, Compound Perception First direction, sixteen immutable Git
blobs, and failed-attempt separation all passed review. The arithmetic audit
ran 350 assertions with zero failures; 119 Python tests, Rust format/check/test
including nine runtime tests, 34 JSON parses, and `git diff --check` passed.
GitHub reported zero unresolved review threads and no merge conflict.

Decision: **`NOT_MERGE_READY`**. Two public-artifact blockers remain:

- the success and attempt-002 Rust result JSON files contain user-specific
  local executable and temporary absolute paths;
- each success/attempt-002 Python attribution JSON repeats each of three
  invariant semantic payloads twenty times, producing at least 433,998 compact
  bytes of avoidable duplicate semantic data across the two files.

No evidence value was rewritten during this review. Required remediation and
the full audit are recorded in
[`worklogs/2026-08-01-m1-p0-r2-rust-compound-runtime.md`](worklogs/2026-08-01-m1-p0-r2-rust-compound-runtime.md).

Model loads: 0. CUDA runs: 0. H3 API calls: 0. API-key uses: 0.

---

## 2026-08-02 — R2 public-evidence history rewrite

The superseded final premeasurement commit first introduced both PR #43
merge blockers, so retaining that SHA was incompatible with removing the
problem blobs from reachable history. Its unchanged parent remains the rewrite
boundary; that commit and its descendants were rebuilt without remeasurement.

Rust provenance now uses public path placeholders and a sanitized command
template. Python stores each T0/T1/T2 semantic payload once and uses sample
references. The final and ineligible attempt-002 structures are consistent;
attempt 001/002 remain `results_eligible=false`.

The full before/after logical evidence digest is
`3fce04dae5f822a2000eb89b25920ab09df8f7fc968a5bf429fc796af83fc3ec`
on both sides. The rewrite removes 842,966 Git-blob bytes while preserving all
measurement values, semantic hashes, failure reasons, and the
`REFINE_RUST_BOUNDARY` Gate. A local-only safety ref is retained and will not
be published. Remote update requires `--force-with-lease`; GitHub object
retention is not interpreted as immediate physical deletion.

Measurement reruns, H3 API calls, API-key uses, paid runs, model downloads,
model loads, and CUDA runs were all 0. Detailed mapping and verification are in
[`worklogs/2026-08-01-m1-p0-r2-rust-compound-runtime.md`](worklogs/2026-08-01-m1-p0-r2-rust-compound-runtime.md).

The PR branch rewrite was published from superseded head `140a49b...` to
verified head `e72cbe5...` using an explicit `--force-with-lease`. Plain
`--force` was not used; local and remote heads matched at the publication
checkpoint.

---

## 2026-08-02 — PR #47 M1-A admission-integrity remediation

The first PR #47 merge-readiness review returned `NOT_MERGE_READY`. Empty
corpus evidence did not expose that invalid rights could pass by count, oracle
source/derivative and related cross-document links were incomplete, and the
dependency-free validators did not enforce the schemas' whole declared range.

Counterexample commit `b7e74ff92c6824bc49c900747b4a5873540c6ed2`
reproduced seven failures before implementation. Correction commit
`deda6750d41028ff61932bc5c8432cf95c893067` connected rights validity to the
Gate, strengthened digest/permission/consent/orphan/duplicate/cut checks, added
status-specific schema rules, and introduced a bounded dependency-free schema
contract audit. No package was installed. A separately available Ubuntu
`jsonschema 4.10.3` Draft 2020-12 cross-check passed but is not a project
dependency; the isolated project environment reports that optional test as
skipped.

The tracked reports remained byte-equivalent: investigated, eligible, pending,
and rejected counts are all zero, coverage is 0/12, and the decision remains
`CORPUS_ACQUISITION_REQUIRED`. Python compile passed; 171 tests ran with 170
passes and one explicit optional skip. A separate 31-test M1-A run with the
external Draft engine passed. Rust format/check/test passed with 10 runtime tests, 52 JSON
files parsed, tracked video binaries and public sensitive-data findings were
zero, v1/R1/R2/R3 evidence changes were zero, and `git diff --check` passed.

Actual video acquisition, model download/load, CUDA, paid external calls,
external personal-data transfer, backend integration, and topology performance
runs remained zero. Details are in
[`worklogs/2026-08-02-m1-real-video-corpus-oracle-protocol.md`](worklogs/2026-08-02-m1-real-video-corpus-oracle-protocol.md).

PR #47 remains Draft and is neither marked ready nor merged.

---

## 2026-08-03 — M1-A2 derivative and human review gate

PR #47 is merged at `b50051b57de819e1481bd0ff71634fa631cca345`
and Issue #46 is closed. M1-A2 Issue
[#48](https://github.com/ksse29077-byte/HIVEFRAME/issues/48) tracks a bounded
approved-asset pass on branch `agent/m1-a2-corpus-derivative-review`.

Only the approved M1-A2 bundle was inspected. Twelve distinct immutable
C01-C12 originals, the capture record, rights declaration, and designated C01
consent were inventoried. The designated consent SHA-256 is
`f1187f598036db3b23af869bab64e19712dce6459667721b375dbf3be72963d2`;
the legacy similarly named file was not used.

FFmpeg/FFprobe 7.1.1 was installed only in the approved asset bundle from the
recorded Gyan archive linked by the FFmpeg Windows download page. Archive,
binary, and license hashes are stored in
`data_ledger/m1-a2/ffmpeg-install-record.json`; PATH and administrator state
were unchanged.

Twelve 832x480, 16 FPS, audio-free FFV1 derivatives were created. Every
independent repeat matched the final binary SHA-256 and every derivative fully
decoded. Originals were rehashed unchanged. Three ineligible attempts record
bitexact option placement, declared rotation admission, and timestamp parsing
failures; they are not mixed with final evidence.

The oracle scaffold contains twelve `pending_review` records and zero verified
records. Corpus, rights, oracle, and cross-document structures validate, but
human rights, scene, privacy, derivative, transition, C07 hard-cut, blind
re-review, disagreement, and adjudication checks remain open. Decision:
**`RIGHTS_REVIEW_BLOCKED`**. Eligible clips and eligible scene coverage are
0/12; topology results remain ineligible.

Detailed evidence and review steps are in
[`M1_A2_REAL_VIDEO_DERIVATIVE_REVIEW.md`](M1_A2_REAL_VIDEO_DERIVATIVE_REVIEW.md)
and
[`worklogs/2026-08-03-m1-a2-real-video-derivative-review.md`](worklogs/2026-08-03-m1-a2-real-video-derivative-review.md).

Model downloads, model loads, CUDA runs, paid external calls, external
personal-data transfers, backend integrations, and topology performance runs:
0 each. No media or tool binary is tracked.

Python compile and all 179 tests passed with one optional external-Schema skip
in the recorded HIVEFRAME environment. Eight focused M1-A2 tests passed. Rust
format, locked check, and locked tests passed with 10 runtime tests. Sixty-two
JSON files parsed; public path, credential, binary, legacy-evidence, and diff
checks passed. The task-specific worklog records the non-installing recovery
from a missing-NumPy system interpreter and a Windows CRLF checkout mismatch.

### Phase-one human review and Oracle UI update

The returned checklist was validated as exactly C01-C12 with the frozen scene
classes. Its SHA-256 is
`1ca2309aa6996416c662387f62e967a15f66c969743c8157e55af3ea3a23f216`.
All twelve `rights_review`, `scene_content_review`, and `privacy_review` fields
are `yes`. All twelve `oracle_initial_pass`, `blind_re_review`, `adjudication`,
and `final_status` fields remain `pending_review`. The corpus manifest, rights
receipt, admission report, and the new public-safe phase-one receipt record
this bounded progress without promoting aggregate eligibility.

A local-only browser review package now provides twelve fully decoded H.264
review proxies, frame stepping and A/B capture, frame-range and drawn-region
input, dirty/stable/uncertain classification, camera/occlusion/lighting/cut
fields, explicit C07 hard-cut guidance, browser-local drafts, and CSV/JSON
export. It requires no direct JSON or coordinate editing. Automated annotation
was not collected, and every export remains `pending_review`.

The Gate remains **`RIGHTS_REVIEW_BLOCKED`**: pending 12, eligible 0, verified
Oracle 0, rejected 0, and eligible scene coverage 0/12. Initial Oracle review,
time-separated blind re-review, adjudication, and final status are still human
work. Model downloads, model loads, CUDA runs, backend integrations, paid
external calls, personal-data transfers, and topology performance runs remain
0 each.

The update passed 11 focused tests and the complete 190-test Python suite with
one optional external-Schema skip. Rust formatting, locked workspace check,
and locked tests passed, including 10 runtime tests. All 65 repository JSON
files parsed; public path/personal-identifier, credential, tracked-binary,
legacy-evidence, and diff checks passed. The detailed worklog records the
test-only handling of the known Windows CRLF checkout difference for the
unchanged R3 raw-byte assertion.

### Guided Oracle review usability replacement

Actual Oracle entry with the first browser form was stopped before any row or
export because it still required a general reviewer to discover every frame
range and draw every region from scratch. The v1 package remains preserved and
marked superseded as usability-history evidence. The reviewer-completed
phase-one checklist remains unchanged: all twelve rights, scene-content, and
privacy fields are `yes`, while all Oracle stages remain `pending_review`.

The guided v2 package uses model-free adjacent-frame grayscale differences,
thresholded tiles, connected components, and merged boxes to propose 110
gap-free intervals with 106 dirty and 17 uncertain boxes. Stable coverage is
the validated full-canvas complement rather than a hand-drawn label. C04-C06
and C12 receive camera-motion prompts, C08 occlusion/disocclusion prompts, C11
a lighting prompt, and C07 eight ranked cut candidates. All are suggestions:
the public receipt states `automatic_proposals_are_truth=false`, eligible 0,
verified Oracle 0, and Gate `RIGHTS_REVIEW_BLOCKED`.

The Korean UI centers on `제안이 맞음`, `수정 필요`, and `판단 어려움`; supports
move/resize/delete/add box editing without coordinate entry; tracks each clip;
derives stable partitions; and blocks completion on gaps, overlaps, incomplete
coverage, unresolved candidates, or an invalid C07 hard cut. Browser checks
confirmed C01 accept-and-advance plus reset, C07 candidate presentation, and
zero console errors. The package and proposal payload remain outside Git; the
method receipt and deterministic tests are public. Model download/load, CUDA,
backend, topology, paid external call, and personal-data transfer counts remain
0 each.

Final verification passed 9 focused guided-review tests and the full 199-test
Python suite with one optional external-Schema skip. Python compile, Rust
format, locked workspace check, locked tests (10 runtime tests), 66 JSON parses,
110 temporal-coverage checks, 110 stable-complement checks, protected-evidence,
public-path/credential, tracked-binary, and diff checks passed. The package
still contains 110/110 `unreviewed` human decisions; eligible and verified
counts remain zero.

---

## 2026-08-03 — M1-A2 selective-recompute protocol correction

HIVEFRAME's official product objective was narrowed to lower accepted-result
cost for pretrained video generation and editing through safe state reuse and
selective recomputation. Compound observation remains an evidence mechanism,
not the objective. Pixel change and human movement boxes have no backend skip
authority.

The returned Guided Oracle JSON/CSV cover C01-C12 and 110 intervals, but are
classified only as auxiliary observed-change evidence. The JSON contains the
exact C07 hard-cut override while the CSV records its containing proposal, so
full cross-format semantic equivalence is not claimed. No coordinate or
decision payload was copied into Git. Safe-skip truth, verified
compute-relevance Oracles, and eligible backend selective-compute results all
remain zero.

Counterexample-first commit `2f7d534` reproduced the unsafe reference path as
five failures and five errors before implementation. The corrected contract
separates observation candidates, backend capability admission, execution
topology, and complete selective-compute receipts. Uncertainty and global
invalidation promote to full compute. The roadmap now uses M0 Full Compute
Cost Truth, M1-A observation corpus, M1-B0/B1/B2/B3 opportunity/admission/probe/
scaling, and M2-M5 planner/freeze/compiler/net-gain gates while preserving the
earlier roadmap as history.

The prior `RIGHTS_REVIEW_BLOCKED` report remains unchanged chronological
evidence. The current Gate is **`ORACLE_PROTOCOL_REVISE`**. Blind re-review,
adjudication, and final verified-Oracle promotion under the superseded
pixel-change protocol are stopped. Model downloads, model loads, CUDA,
backend, topology-performance, paid-service, and external personal-data
transfer counts are all zero.

Final model-free verification passed Python compile and ran 213 Python tests:
211 passed and two explicit optional-dependency tests skipped. Cargo formatting/check/tests ran
ten Rust tests, 73 JSON parses, custom schema positive/negative checks,
protected-evidence comparison, binary/path/secret scans, and diff checking.
Three earlier Python suite launches were retained as ineligible environment
attempts: temporary-directory ACL denial and the already documented Windows
CRLF-versus-LF R3 raw-byte fixture difference. The final run used the existing
test-only LF normalization with byte restoration and a permitted temporary
execution context. No product, model, backend, topology, or CUDA path ran.

Detailed evidence is in
[`worklogs/2026-08-03-m1-a2-real-video-derivative-review.md`](worklogs/2026-08-03-m1-a2-real-video-derivative-review.md)
and
[`HIVEFRAME_SELECTIVE_RECOMPUTE_RUNTIME_DIRECTION.md`](HIVEFRAME_SELECTIVE_RECOMPUTE_RUNTIME_DIRECTION.md).

---

## 2026-08-03 — PR #49 final consistency and merge-readiness audit

The audit began from clean branch head
`8115c660055749321da637be708a30a546a396af`, matching the remote branch, with
`origin/main` at `b50051b57de819e1481bd0ff71634fa631cca345` and no divergence.
PR #49 remained Draft/Open, based on `main`, mergeable, conflict-free, and
unmerged. No CI status checks or unresolved review threads existed. Issue #48
remained Open.

The PR title was corrected to **“M1-A2: Preserve real-video evidence and revise
selective-recompute protocol”**. One non-duplicated top-level Issue #48 comment
records the continuation correction: phase-one review 12/12, twelve
deterministic FFV1 derivatives, the Guided export's auxiliary classification,
zero compute-relevance/safe-skip/backend-result evidence, current Gate
`ORACLE_PROTOCOL_REVISE`, and separate-approval requirements for M1-B0. The
historical Issue body was not rewritten.

The claim audit corrected stale R1-era/current-direction wording in contributor,
charter, architecture, work-order, task, README, and M1-A protocol documents.
The product objective is complete accepted-result cost reduction through safe
state reuse and backend-admitted selective recomputation. Compound observation
is an evidence mechanism, not the product objective. Historical Gates remain
chronological evidence; the current Gate is `ORACLE_PROTOCOL_REVISE`.

Two contract gaps were closed without adding a backend feature. Unmeasured
ExecutionTopology numeric fields now use `value=null`, `status=unavailable`, a
reason, and method `not measured` instead of fake zero. A protocol-only
SelectiveComputeReceipt with `results_present=false` now rejects measured
cost, resource, fraction, quality, temporal, work-reduction, speedup, and GPU
saving values. The protocol config also fixes model, CUDA, backend integration,
topology performance, paid-service, and external-personal-data-transfer counts
at zero. Five additional counterexample tests preserve these rules.

The approved external Guided export was rechecked read-only. The JSON is
222,461 bytes with SHA-256
`c1306acab8e8a34a89d2d13d3c25b8def0031e9f8ac113dc867ff9eb090e534d`;
the CSV is 63,545 bytes with SHA-256
`9c0efafc343db8e907aef233900a39153dc1869ad21b29691f9f7d3623826746`.
Both retain C01-C12 and 110 intervals. The JSON retains the exact C07 hard-cut
override; the CSV retains its containing proposal, so complete semantic
equivalence is not claimed. No reviewer coordinate or decision payload was
copied into Git.

Verification passed Python compile and 218 Python tests: 216 passed and two
optional-dependency checks were explicitly skipped. The focused protocol suite
ran 19 tests, with 18 passed and the optional external-`jsonschema` check
skipped. Cargo format, locked workspace check, and locked tests passed with ten
Rust tests. All 73 tracked JSON files parsed. `git diff --check`, public-path,
credential, changed-binary, protected M0/M1-P0, and protected M1-A2 evidence
checks passed with zero findings.

Model downloads 0, model loads 0, CUDA runs 0, backend integrations 0, topology
performance runs 0, paid external calls 0, and external personal-data transfers
0. The audit did not transition PR #49 to Ready, merge it, close Issue #48, or
start M1-B0. M1-B0 remains a separate Issue/branch/Draft PR task requiring
explicit user approval.

---

## 2026-08-03 — M1-A2 protocol correction published and closed

### Verified publication state

- [PR #49](https://github.com/ksse29077-byte/HIVEFRAME/pull/49) was marked
  Ready after its final manual audit and merged with the repository's normal
  merge-commit strategy.
- PR head:
  `028bfdffb302d12074429e876b77425fa644934c`.
- Merge commit:
  `e00145ae2e0e9c2dbc85b432bee121bd12dca103`.
- Merged at: `2026-08-03T13:38:13Z`.
- [Issue #48](https://github.com/ksse29077-byte/HIVEFRAME/issues/48) received
  a merge-completion record and closed as `COMPLETED`.
- The source branch `agent/m1-a2-corpus-derivative-review` remains available;
  it was not deleted.
- The merge commit is the verified `origin/main` head at this publication
  checkpoint, contains the approved PR head, and the local `main` was
  fast-forwarded to the same SHA.

The M1-A2 contracts, selective-recompute direction correction, protected
evidence, and audit record are now **published** on `main`. `Published` means
the reviewed Git objects are remotely available. It does not mean selective
recompute performance is **verified**. The final decision remains
**`ORACLE_PROTOCOL_REVISE`**.

### Claim boundary

- Guided Oracle classification: auxiliary observed-change evidence;
- safe-skip truth: 0;
- verified compute-relevance Oracles: 0;
- eligible backend selective-compute results: 0;
- M1-A2 actual speedup results: 0;
- M1-A2 actual GPU-work reduction results: 0;
- M1-A2 actual VRAM-reduction results: 0;
- model, CUDA, backend-integration, and topology-performance runs during this
  publication sync: 0.

In exact scope terms: **M1-A2 protocol correction and evidence preservation
were merged. Actual locality, backend capability, selective compute, VRAM, and
end-to-end speed remain unmeasured.**

M1-B0 remains planned and requires a separately approved Issue, branch, and
Draft PR. A HIVEFRAME 2.0 RFC is also planned/protocol-only and requires its
own approval and review surface; it cannot bypass M1-B0 or backend evidence.

### Merge controls and follow-up

Before merge, PR #49 had zero conflicts and zero unresolved review threads.
GitHub exposed no registered CI/status checks, so the merge relied on the
recorded manual model-free verification rather than an absent CI signal. No
force-push, rebase, history rewrite, or branch deletion was performed.

This docs-only follow-up exists because the preceding audit entry was
historically correct when it said the PR was Draft and unmerged. Repository
rules require the later verified publication state to be appended rather than
rewriting that chronological evidence.

### Docs-only sync verification

Branch `agent/m1-a2-merge-publication-sync` started from merge commit
`e00145ae2e0e9c2dbc85b432bee121bd12dca103`. No duplicate branch, Issue, or PR
for this publication sync existed, so no tracking Issue was created. The diff
contains four Markdown files: the three required logs/task files plus one
directly conflicting “current merge-readiness scope” sentence in the master
work order.

- Python compile: passed;
- full Python suite: 218 run, 216 passed, two optional-dependency checks
  explicitly skipped;
- `cargo fmt --all -- --check`: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 10 Rust tests;
- changed Markdown relative links: valid, zero broken;
- public absolute-path and credential/private-key findings: 0;
- changed binary findings: 0;
- M0, M1-P0, and M1-A2 code/config/schema/report/ledger evidence changes: 0;
- `git diff --check`: passed.

Model loads, CUDA runs, backend integrations, topology or performance runs,
M1-B0 executions, and HIVEFRAME 2.0 RFC executions were all 0.

---

## 2026-08-05 — M1-B0 model-free locality opportunity

### Purpose and scope

Issue [#51](https://github.com/ksse29077-byte/HIVEFRAME/issues/51) and branch
`agent/m1-b0-model-free-locality` isolate the approved experiment from `main`.
The branch started at PR #50 merge commit
`5e93745b8280159ff79ea7ef75343790c0a78e48`. No duplicate Issue, branch, PR,
or implementation was found and the starting worktree was clean.

M1-B0 measures adjacent-frame pixel/tile locality and model-free detector cost
on the twelve approved M1-A2 FFV1 derivatives. Guided Oracle boxes were not
used as truth or for threshold selection. The result is not safe-skip truth,
backend capability, selective compute, GPU work, VRAM reduction, or product
speedup.

### Predeclaration, implementation, and failures

Commit `7288790eb4cb6404689941251bf8baed73557ec0` preserved twenty failing
counterexamples before implementation. The first test attempt used the wrong
unittest module path. The second established that the isolated embedded Python
does not honor relative `PYTHONPATH`. The corrected harness collected the
tests and failed on the intentionally missing implementation. Those failures
are setup and preimplementation evidence, not successful measurements.

Commit `3d05409` implemented the fixed `m1-b0-v1` config, Schema, vectorized
NumPy reference, deterministic Rust detector/CLI, partial tiles, halo,
temporal runs, global translation, parity gate, collision-safe phased runner,
and cost profiles. Commit `9d11308` completed dependency-free receipt
invariants and regression tests. No threshold, tile, halo, translation, repeat,
or Gate rule changed after results were visible.

The first full Python run found two pre-existing R3 byte-hash failures caused
by global `core.autocrlf=true`, not by changed R3 evidence. The R3 Git blob
already matched its recorded SHA-256. A scoped `.gitattributes` LF rule makes
that one byte-hashed config materialize identically on Windows; R3 content and
Git blob remain unchanged. The rerun passed all 237 Python tests with two
declared optional-dependency skips. Cargo format/check and all 14 Rust tests
also passed.

### Input, parity, and measurement result

All C01-C12 derivatives passed FFV1, 832x480, 16 FPS, frame-count, byte-size,
and SHA-256 validation. There are 1,677 frames and 1,665 frame pairs. NumPy and
Rust parity passed 24/24 gray8/RGB24 clip-format comparisons with zero
mismatches.

Across all clips, raw gray changed-pixel ratios were 55.2251%, 36.7986%,
27.9859%, 20.6741%, 14.5320%, and 9.4529% at thresholds 0, 1, 2, 4, 8, and
16. Translation-compensated ratios were 54.5530%, 35.4699%, 26.4276%,
19.0551%, 13.0553%, and 8.3058%. Both complete surfaces are retained.

At one disclosed anchor (threshold 4, 16x16, 5% activation), zero-halo active
ratio was 44.5519%; one-tile halo raised it to 60.4169%, and two-tile halo to
68.3729%. This is an illustration of closure cost, not a recommended
configuration. Every predeclared configuration remains in the reports.

Decode-only, resident-warm, and streaming decode+pipe+compare are separate
scopes. Summed per-clip p50 values were 2.4770, 22.5681, and 24.8273 seconds.
One-worker suite wall was 23.4902 seconds. Required CPU worker speedups for
2/3/4/6 workers were 1.788x/2.452x/3.010x/4.018x; parallel efficiencies were
0.894/0.817/0.752/0.670. Eight and twelve workers are separately labeled
oversubscription diagnostics, never GPU streams. OS caches were not flushed,
so no cold-disk result is recorded.

Scheduling overhead, process-tree peak RSS, and CPU utilization remain null
with reasons because validated samplers were not enabled. All backend-memory
and VRAM projections are also null/unavailable; pixel fractions were not
converted to tensor, cache, activation, or VRAM savings.

### Evidence and Gate

The local logical bundle inventory is 2,797,139,675 bytes with SHA-256
`aee19615de605e9ff0fc3d190a0213d99a207c9622bd536e8d091354347cece0`.
Only its logical asset ID, size, digest, and small aggregate reports are public.
No local absolute path or media/raw/tool binary is tracked. Aggregate summary
digest is `2cc1094d40b0f85424ca67cdff32a9b0a242b45ed50934ef6d4980d46bf73e3a`.

The bounded decision is **`M1_B0_LOCALITY_SURFACE_MEASURED`**. It states that
the fixed observation surface, parity, cost scopes, and worker sweep are
available for Draft review. M1-B1 remains separate and unstarted.

The branch was pushed normally and [Draft PR #52](https://github.com/ksse29077-byte/HIVEFRAME/pull/52)
was opened against `main`. At its first publication checkpoint, local and
remote heads matched at `c8c1c9fb23f959ee07de7afa5e39ecea2a869981`; GitHub
reported the Draft as open, mergeable, and clean. It was not transitioned to
Ready and was not merged.

Model downloads 0, model loads 0, model runs 0, CUDA runs 0, GPU runs 0,
backend integrations 0, selective-compute runs 0, VRAM measurements 0,
product-speedup results 0, safe-skip truths 0, verified compute-relevance
Oracles 0, paid API calls 0, and external personal-data transfers 0.

Detailed protocol and evidence are in
[`M1_B0_MODEL_FREE_LOCALITY_PROTOCOL.md`](M1_B0_MODEL_FREE_LOCALITY_PROTOCOL.md)
and
[`2026-08-05-m1-b0-model-free-locality-opportunity.md`](worklogs/2026-08-05-m1-b0-model-free-locality-opportunity.md).

## 2026-08-05 — P0-LR local-model-ready H3 product correction

Issue [#53](https://github.com/ksse29077-byte/HIVEFRAME/issues/53), branch
`product/p0-h3-vertical-slice`, and Draft PR #54 were reused. The original
API-shaped contract shell was corrected in place into a local-model-ready
product boundary: an official H3-shaped `H3GenerationRequest`, asset-ID media,
deterministic `MockH3Backend`, `MiniMaxH3LocalBackend`, lazy injectable
`LocalPipelineFactory`, external artifacts, and an explicit default
`artifact_pending` state. API-key checks, provider IDs/polling, API costs, and
mandatory transfer consent are no longer part of the active product path.

Local H3 never automatically falls back to a Mock success. The UI explicitly
offers Mock H3 while Local H3 says `Waiting for official model files`. No source
means prepare returns `artifact_pending`, load raises
`model_source_not_configured`, and generation fails
`local_backend_unavailable`. Local-files-only resolution accepts only an
existing local directory or revision-pinned cache snapshot; it performs no
automatic download. Sensitive source/revision/root values are reduced to
configured/not-configured/valid/invalid status in public state and receipts.

Bounded correction produced five materially changed-code checkpoints: 13
focused tests passed in 1.205 seconds, then 1.612 seconds after the exact
contract-name correction, and finally 1.574 seconds after error/output-candidate
semantics changed, 1.458 seconds after readiness-state preservation changed,
and 1.447 seconds after the non-offline loader path was made fail-closed. No
unchanged-code rerun occurred. Full Python/Rust and
unchanged M0/M1 suites were skipped. Model downloads, `from_pretrained` calls,
model loads, GPU generations, CUDA, API calls, paid calls, external personal-
data transfers, and selective-compute runs were all zero.

The bounded decision is `P0_LOCAL_READY_WAITING_FOR_ARTIFACT`. P1-L requires an
official model source/revision, model card and execution docs, reported size and
location, explicit download approval, and one bounded local generation. It is
not a mandatory live-API stage. Full contract, verification, limitations, and
future inputs are recorded in
[`2026-08-05-p0-h3-product-vertical-slice.md`](worklogs/2026-08-05-p0-h3-product-vertical-slice.md).

## 2026-08-05 — P0 Local H3 through loopback ComfyUI

Issue #53, `product/p0-h3-vertical-slice`, and Draft PR #54 were reused after
an approved external H3 asset root became available. A new loopback-only
`MiniMaxH3ComfyUIBackend` connects the existing product Job, UI, result,
download, cancellation, and feedback contracts to one sanitized API copy of
the supplied text-to-video workflow. The original workflow and four model
components remained unchanged and outside Git.

Exactly one workflow submission ran on ComfyUI 0.30.2 and RTX 3060. HIVEFRAME
observed `queued → running → succeeded`; there was no OOM or retry. The
effective workflow profile was 864x480, 124 frames, 24 FPS, 20 steps, fixed
seed 101, and native audio. Submit-to-terminal time was 587.513159 seconds;
system sampling observed 12,457,195,444 peak used VRAM bytes and
60,520,648,704 peak system-wide used RAM bytes. Model-load time remains
`null/not_collected`, not zero.

The 262,579-byte H.264 MP4 has SHA-256 `ec4ddbac...641c4`; all 124 frames
decoded successfully. The video, full receipt, prompt, database, and complete
runtime log remain outside the repository. External API calls, API keys, paid
calls, model downloads, original-asset changes, and tracked binaries were all
zero. Focused changed-surface validation passed 18 tests in 2.329 seconds; full
unchanged suites and repeated generation were intentionally skipped.

Knowledge Flywheel entries preserve the prior artifact-pending history, record
the actual run as `verified_once`, and mark only previously established safety
rules as `reused_successfully`. No rule was automatically promoted. A nonfatal
parallel-ComfyUI database-lock warning becomes a P1 launcher candidate, not a
silent product default. The bounded decision is
`P0_LOCAL_H3_COMFYUI_READY`; it is a one-run product-path result, not a quality,
speed, cost, cache, or selective-compute claim. See the detailed
[`P0 worklog`](worklogs/2026-08-05-p0-h3-product-vertical-slice.md).

## 2026-08-05 — F0 Local H3 SageAttention KJ paired validation

Issue #55 and branch `accel/f0-h3-sageattention` isolate one external
attention-kernel experiment after P0 shipped. The original H3 workflow and
model assets remained unchanged and outside Git. A fixed KJNodes checkout at
`6edfa765...`, a checksum-verified SageAttention 2.2.0 Windows ABI3 package,
and Triton Windows 3.7.1 post27 were added without changing Python 3.13.12,
PyTorch 2.12.1+cu130, CUDA 13.0, ComfyUI 0.30.2, or the driver. A model-free
BF16 Sage kernel call passed on RTX 3060 Compute Capability 8.6.

The Standard API copy retained zero Sage nodes. The Sage copy added exactly
one `PathchSageAttentionKJ` node in `auto` mode between the loaded MODEL and
both `BasicScheduler` and `BasicGuider`. Each variant ran once in a separate
owned loopback ComfyUI process with the same private P0 prompt/hash, seed 101,
864x480, 124 frames, 24 FPS, 20 steps, `simple`, `res_multistep`, denoise 1.0,
and native audio.

Standard submit-to-terminal was 586.972500 seconds; Sage was 486.247216
seconds. The paired speedup is 1.207148× and the reduction is 17.160137%,
below the fixed 1.3× Fast-candidate threshold. Both outputs decoded 124/124
H.264 frames, contained audio, and had zero black or corrupted frames; OOM and
retry were zero. Denoising-only speedup remains `null/not_collected` because
ComfyUI did not expose that span. System-sampled peak VRAM was the same
12,460,611,508 bytes for both runs.

The bounded decision is **`F0_SAGE_NO_GAIN`**. This is external F0 evidence,
not HIVEFRAME Core acceleration. Sage was not promoted, Standard full compute
remains unchanged, and `VISUAL_QUALITY_REVIEW_REQUIRED` remains explicit.
Thirteen focused model-free tests passed; full Python/Rust and all repeat,
profile, seed, mode, and accelerator sweeps were omitted. Actual H3 generation
count was exactly two. See the detailed
[`F0-SAGE worklog`](worklogs/2026-08-05-f0-h3-sageattention.md).

PR #56 was subsequently moved from Draft and merged to main as normal merge
commit `2faa8a7040f0a3d7c855d0bea5d1db1495de6564`; Issue #55 was completed and
the source branch was preserved. This publication keeps the product decision
`DROP_AS_PRODUCT_ACCELERATOR` and repository evidence decision
`KEEP_AS_OPTIONAL_EVIDENCE`; it does not promote SageAttention.

## 2026-08-06 — C0 Local H3 execution phase and Runtime Hook Map

After F0 publication, Issue #57 and branch
`core/c0-h3-execution-phase-map` isolated one C0 measurement and design pass.
Model-free WebSocket, progress, phase-union, resource-context, sanitizer,
unsupported-value, and collision fixtures were implemented before GPU work.
The initial nine code-only focused tests passed, and the final suite including
public YAML contract validation passed 10/10. A separate unchanged backend-suite invocation
hit one Windows/Python 3.13 SQLite handle-cleanup error after its product
assertions; that environmental cleanup result was retained rather than
reported as a pass.

Exactly one unchanged Standard H3 workflow ran with zero Sage nodes and zero
retry. The 864x480 H.264 result decoded 124/124 frames at 24 FPS with native
audio. Submit-to-terminal was 586.986496 seconds, only +0.002385% from the
historical 586.972500-second Standard sample. Runner entry-to-stop was
599.298147 seconds.

The sampler node occupied 486.603692 seconds (81.196% of runner time), video
VAE decode 63.162271 seconds (10.539%), and prompt/AV conditioning 33.672949
seconds (5.619%). Twenty client-observed progress intervals had a
22.353163-second median. They are not exact GPU step durations. Lazy model
materialization overlapped the sampler span, and exact GPU-kernel duration and
PyTorch allocator peaks remain null with explicit unsupported reasons.

The public phase map and hook map select exactly one future Rust target: a
coarse, metadata-only sampler progress/callback policy boundary. The first
handoff must return full-compute directives, move zero tensors across FFI, and
fail open to the unchanged Standard workflow. Rust code, Compound Eye runtime,
selective compute, cache reuse, Fast Mode, and model training remain zero.
The bounded result is `C0_H3_PHASE_MAP_READY`; see the detailed
[`C0-H3 worklog`](worklogs/2026-08-06-c0-h3-execution-phase-map.md).

PR #58 was subsequently merged by normal merge commit
`3d6728d3c1826c4171130816c382c5ecec444f43` at
`2026-08-06T02:40:41Z`; Issue #57 was completed and the source branch was
preserved. The three pre-merge corrections were whitespace-only and retained
all C0 measurements and claims.

## 2026-08-06 — C1 Rust sampler step policy bridge

Issue #59, branch `core/c1-rust-sampler-policy-bridge`, and Draft PR #60
isolate a metadata-only PyO3 policy boundary at `sampler.progress_callback`.
The existing Cargo workspace and `hive-retina-runtime` /
`hive-retina-python` crates are reused. ABI version 1 defines a 184-byte
`StepObservation` and 76-byte `StepDirective`; the only decisions are
`FULL_COMPUTE` and `ESCALATE_FULL_COMPUTE`. Tensors, prompts, paths, model
state, CUDA addresses, skip/reuse directives, and partial compute are excluded.

Model-free evidence includes 13 focused Python tests, three focused Rust
tests, a real ABI roundtrip, contained panic probe, ComfyUI 0.30.2 custom-node
registration, and original-callback delegation. One approved Standard H3
workflow was then submitted with the fixed 864x480, 124-frame, 20-step,
native-audio profile. It failed at repository wrapper entry before callback 1
because ComfyUI's locked V3 class rejected mutation of a class-level guard.
Retry, OOM, output, callback, and Rust-call counts were 0 except for the one
workflow submission. The failed diagnostic submit span was 34.443671 seconds
and is not performance evidence.

The guard was moved to module-local state and the corrected path passed a
model-free direct-call check with one delegated callback and one Rust call.
The user then approved exactly one regression generation. It completed with
20 callbacks, 20 Rust calls, 20 `FULL_COMPUTE` directives, and zero fallback,
escalation, skipped work, cache reuse, partial compute, or tensor transfer.
Boundary p95 was 38.1 microseconds, the conservative cumulative policy span
was 2.592 milliseconds, and submit-to-terminal was 556.433128 seconds. The
H.264 output decoded all 124 frames at 864x480 and 24 FPS with one audio
stream; retry, OOM, black-frame, corrupted-frame, CUDA-error-signature, and
NaN-signature counts were zero under their recorded checks.

The bounded result is `C1_RUST_POLICY_BRIDGE_READY`, verified once and not
promoted to a product default. The single-run time difference is not a
speedup claim. Raw events, samples, full logs, private receipts, build log,
prompt, paths, and media remain outside Git. External API, model download,
Sage, selective compute, cache reuse, Fast Mode, and training counts remain
zero. `REVISE_ONCE` is consumed; the next separate approval would be C2
Compound Eye Shadow Policy with actual H3 computation still full compute. See
the detailed [C1 worklog](worklogs/2026-08-06-c1-rust-sampler-policy-bridge.md).

## 2026-08-06 — C2 Local H3 Compound Eye shadow policy

Issue #61, branch `core/c2-h3-compound-eye-shadow`, and Draft PR #62 isolate
the first real-H3 Compound Eye shadow attempt. PR #60 was first verified as
merged at main commit `4635f4750553a24037793e6ebbfa077f06d2474a`; C1's
full-compute ABI and evidence were reused without another run.

Before runtime work, C2 fixed one `overlap_2x2` topology (one global and four
overlapping regional eyes), one x0-only 4x4x3 sketch, int32 scale 4096, five
ppm thresholds, ABI v1, one-Rust-call maximum, next-callback validation, and
Full Compute fail-open. Seven focused Rust tests and 20 C2+C1 Python tests,
including a real PyO3 ABI roundtrip, passed. The first commit was
`cd4e5cd8a8016c599657bf5ab967a31d53086390`; thresholds were not changed after
the actual result.

Exactly one Standard H3 workflow then ran with zero Sage nodes and zero retry.
It generated a valid H.264 864x480 output with 124/124 frames, 24 FPS, one
audio stream, no black or corrupted frame, and SHA-256
`1ae93b511a7998a25f4984850192e6ae11ed1bafadcdfc1f2d4a6a8954227534`.
Submit-to-terminal was 585.362693 seconds, runner total 600.382758 seconds,
peak NVIDIA sampled VRAM 11,923,357,696 bytes, and peak process-tree RSS
46,995,505,152 bytes.

All 20 callbacks reported `x0_not_tensor`. C2 therefore made zero sketches,
zero host transfers, zero Rust calls, zero stable candidates, zero validated
stable candidates, and zero contradictions. The wrapper failed open and the
actual workflow remained Full Compute for all steps. It did not switch to
`x`, nested members, RGB, previews, QKV, or another source. Actual skip, cache
reuse, partial compute, raw tensor transfer, profiler, and repeat counts were
zero. Shape, dtype, device, Rust timing, and exact GPU kernel time remain
`null/not_collected` with reasons rather than fabricated zeros.

The bounded decision is `C2_SHADOW_SIGNAL_NOT_ADMITTED`; the exact C3
selection is `no_c3_admission`. No sampler gate or transformer wrapper is
authorized from this evidence, and no speedup or product-default claim exists.
Public evidence is aggregate-only; prompt, video, callbacks, logs, receipts,
machine paths, and build artifacts remain under the repository-external
logical root `C2_ARTIFACT_ROOT`. See the detailed
[C2 worklog](worklogs/2026-08-06-c2-h3-compound-eye-shadow.md) and
[C3 handoff](design/h3-c3-selective-compute-handoff.md).

C2-R1 then fixed only the source-proven `x0.tensors[0]` container path. The
adapter commit passed 14/14 focused model-free tests and was pushed before the
single approved regression. That one owned-runtime submission completed with
20 callbacks, 20 Rust calls, 20 `FULL_COMPUTE` directives, zero escalation or
fallback, and zero actual skip, cache reuse, partial compute, or raw-tensor
Rust transfer. The H.264 output decoded 124/124 frames at 864x480 and 24 FPS
with native audio; retry, OOM, CUDA-error, NaN, black-frame, and corrupted-frame
counts were zero under the recorded checks.

The observed container was `comfy.nested_tensor.NestedTensor`; its approved
video slot was `[1,24,37,30,54]` on CUDA. The actual dtype was
`torch.float32`, contradicting the committed BF16 admission check. The code
therefore allowed Rust evaluation through its structural adapter but the
post-run source gate rejected the signal. This is a wrapper/admission-contract
defect, not successful runtime admission. In addition, each 48-float host
transfer blocked for about 7.14 seconds: total-shadow p95 was 7.147004 seconds
and cumulative shadow span was 135.699001 seconds, both above fixed limits.

Counterfactual evidence remains useful but is not promoted: 76 eligible
regional eye-steps yielded 25 stable, 4 active, and 47 uncertain candidates;
all 25 stable candidates were validated by the next Full Compute callback,
with zero contradiction and zero unvalidated candidates. One global
invalidation and zero overlap conflicts were observed. Because the dtype and
overhead gates failed, the final bounded decision is `C2_SHADOW_REVISE_ONCE`.
The runtime's transformer-block candidate remains candidate-only; C3 admission
is `no_c3_admission`. No second generation or post-result code change was made.

## 2026-08-06 — C2-R2 async FP32 shadow admission

The final C2 `REVISE_ONCE` used the predeclared exact callback contract rather
than changing signal source after observation. Commit
`fccaa9f366c0c9a1210eef041a82f551e98d84a1` requires the exact
`x0.tensors[0]` float32 CUDA video tensor, keeps the paired audio tensor on the
same device, reduces only to a fixed 48-value sketch, and moves that sketch
through a bounded three-slot pinned-memory ring. The callback performs no
blocking host conversion or explicit synchronization, retains no source
tensor, and always delegates the original callback arguments unchanged.

Model-free verification passed 16 focused tests in the Local H3 runtime,
including the real PyO3 ABI roundtrip. One and only one approved fixed-profile
H3 generation then completed without retry. All 20 callbacks passed structural
and dtype admission; enqueue, consume, event-ready, Rust-call, and Full Compute
counts were each 20. There were zero dtype rejections, signal rejections,
not-ready events, ring overflows, drain timeouts, fallbacks, escalations,
callback synchronizations, skips, cache reuses, or partial-compute operations.

The lagged counterfactual contract used horizon 2: callback N enqueued sketch
N, callback N+1 consumed it, and the delta from N-1 to N predicted callback
N+2. Of 72 eligible regional eye-steps, 23 were stable, 4 active, and 45
uncertain. All 23 stable candidates were validated by later unchanged Full
Compute observations, with zero contradiction and zero unvalidated candidates.

Callback CPU p95 was 1.5082 ms and cumulative callback CPU time was 73.0815 ms.
CUDA sketch p95 was 0.217248 ms, Rust boundary p95 was 37.6 microseconds, and
the bounded drain took 0.1574 ms. The run completed in 588.09061 seconds from
submit to terminal and decoded all 124 H.264 frames at 864x480 and 24 FPS with
one audio stream. The output SHA-256 was
`0b1cf9f6d95808ce5eed3b4b77c4a94562173abe400e3dad6b41b6fa188531cb`.

Every fixed C2-R2 admission, overhead, readiness, integrity, and
counterfactual-validation Gate passed. The decision is therefore
`C2_COMPOUND_EYE_SHADOW_READY`, and `h3.transformer_block_wrapper` is the sole
candidate for a separately approved C3 design. This is shadow evidence only:
actual execution remained Full Compute, so speedup, safe skip, cache reuse,
partial compute, product promotion, and C3 implementation all remain zero.

## 2026-08-07 — C3 Transformer Block Selective Compute pre-gate

Issue #63 and branch `accel/c3-h3-transformer-block-selective-compute` isolate
the first proposed actual-compute-reduction experiment. Read-only inspection of
ComfyUI 0.30.2 established a structurally valid repository-owned replacement
hook for the 50 ordered H3 `DiTBlock` entries. The hook can either call the
original block or return the packed residual input unchanged, without editing
installed source, cloning a tensor, caching block output, or sending a tensor
to Rust.

The required opportunity check stopped the experiment before implementation.
The immutable C2-R2 receipt produced no G4 or G3 target. G2 produced raw target
steps 5, 6, 8, 13, 16, 17, 18, and 19; first/last anchors and the two-step
Full Compute cooldown reduced them to steps 5, 8, 13, and 16. Candidate block
indices 12 through 48 give 37 bypass calls per selected step, or 148 of 1,000
theoretical calls: 14.8 percent, below the fixed 18 percent floor.

The bounded decision is `C3_POLICY_OPPORTUNITY_TOO_LOW`. No C3 Rust ABI,
PyO3 bridge, Python runtime wrapper, CONTROL/SELECTIVE generation, model load,
CUDA execution, speedup claim, quality result, or product promotion was made.
The C1/C2 ABIs and all prior evidence remain unchanged. See the detailed
[C3 worklog](worklogs/2026-08-07-c3-h3-transformer-block-selective-compute.md).

## 2026-08-07 — C3-R1 Frozen Replay Selective Block Experiment

Issue #65, branch `accel/c3-r1-frozen-replay-block-selective`, and Draft PR
#66 isolate a separate frozen-replay mechanism test without rewriting the
prior C3 rejection. Before runtime work, commit `a1a369a...` fixed the six
steps 5/6/8/13/16/17, Full Compute anchors 0/1/18/19, candidate blocks 12..48,
the 18 percent actual-opportunity floor, a separate 208/80-byte metadata ABI,
and one-Rust-call-per-callback maximum. Focused pre-run validation passed four
Rust tests, nine Python tests, Python compilation, PyO3 build/roundtrip, format,
and diff checks. C1/C2 ABI sizes remained unchanged.

Exactly two fresh-process Local H3 generations were run: one CONTROL and one
SELECTIVE, each with one submission and zero retry under the unchanged private
prompt, seed 101, 864x480, 124-frame, 24 FPS, 20-step Standard profile. CONTROL
observed 1,000 original block calls and zero bypass. SELECTIVE observed 852
original calls and 148 bypasses, satisfying the exact identity
`1000 - 852 = 148`. Live safety admitted steps 5/6/13/17 and vetoed steps 8
and 16, so actual reduction was 14.8 percent rather than the 22.2 percent
frozen ceiling and remained below the fixed 18 percent Gate.

Sampler, submit-to-terminal, and runner ratios were 1.153991x, 1.125478x, and
1.126296x. The sampler and submit targets were 1.20x and 1.15x, so neither
passed and no speedup is claimed. Frame-aligned quality also failed: mean SSIM
0.805245, p05 SSIM 0.764500, low-SSIM rate 1.612903 percent, normalized MAE
0.055380, and motion-energy ratio 1.834976. Both outputs decoded 124/124 H.264
frames with native audio, and recorded OOM, retry, CUDA-error, NaN, black, and
corruption counts were zero.

C3 moved zero tensor bytes to Rust, made zero full-tensor host copies, and used
zero persistent GPU cache. Cache/reuse, residual cache, attention/token/latent
or whole-step skip, regional compute, partial repair, Fast Mode, SageAttention,
and training remained unused. There was no third generation or post-result
code change. The bounded decision is
`C3_R1_LIVE_VETO_OPPORTUNITY_TOO_LOW`; the experiment verifies actual block
omission once but does not admit a dynamic product policy, quality equivalence,
speedup, or product promotion. See the detailed
[C3-R1 worklog](worklogs/2026-08-07-c3-r1-frozen-block-bypass.md).

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
