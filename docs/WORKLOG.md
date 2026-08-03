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
