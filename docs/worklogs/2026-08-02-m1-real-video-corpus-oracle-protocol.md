# 2026-08-02 — M1-A Real-video Corpus and Oracle Protocol

Status: verified locally; decision `CORPUS_ACQUISITION_REQUIRED`; publication pending

## Verified predecessor state

- base `origin/main`: `156d955fa8edfbcb6157ef6e130454da0b165daf`;
- PR #45: merged with that merge commit;
- Issue #44: closed;
- R3 Gate: `RUST_CONTROL_PLANE_ADMITTED`;
- M1-P0: completed; no R4 is authorized;
- Compound Perception First remains active;
- Mono remains comparator and safety fallback only;
- M0 remains `in_progress` and its evidence is unchanged.

The dedicated branch is
`agent/m1-a-real-video-corpus-oracle-protocol`. Repository, Issue, PR, and
branch searches found no duplicate M1-A implementation. The initial Issue
publication attempt was rejected by the available GitHub write integration;
no remote object was changed. Publication remains pending until an authorized
Git transport is available.

## Predeclared boundary

Before any actual clip can become eligible or any final annotation can be
accepted, this branch fixes:

- a twelve-distinct-clip minimum and twelve required real-video scene classes;
- conservative rights, commercial-use, derivative, redistribution,
  attribution, consent, and sensitive-content admission;
- immutable-original and deterministic analysis-derivative rules;
- dirty, stable, uncertain, preserve, scene-cut, object, compact-mask, review,
  disagreement, and versioning semantics;
- T0 through T7 candidate contracts without executing them;
- accuracy, complete-cost, unavailable-value, and provisional safety-Gate
  semantics;
- explicit validators, positive/negative tests, and four allowed M1-A Gate
  decisions.

The predeclaration contains no topology result. Thresholds and admission rules
must not be changed favorably after observing later corpus or topology results.

## Asset scope before admission

Only repository metadata and explicitly task-approved artifacts may be
inspected. Arbitrary personal folders, media libraries, network sources, and
random public video are outside scope. No video binary may be committed.

Predeclaration commit:
`d60fd7650d2a0a7d2fedf19d43d4638895f0e682`.

After that commit, the allowed asset search was repeated. Repository metadata
contains admission rules and artifact-store guidance but no actual video
reference with a rights and consent receipt. The supplied task attachment is a
work order, not video. No arbitrary personal folder, media library, network
source, or unrelated workspace was scanned.

Classification counts:

- eligible: 0;
- pending rights review: 0;
- rejected: 0;
- investigated actual clips: 0.

No status was fabricated for an absent clip. No public video was downloaded.

## Coverage and Gate

All twelve required classes remain missing: speaking person with static
background, hand motion with static background, local object motion with static
background, slow pan, zoom, handheld shake, hard cut, multi-object occlusion,
reflection or mirror, hair/water/smoke boundary, lighting change, and local
static content combined with global camera motion.

Decision: **`CORPUS_ACQUISITION_REQUIRED`**.

The protocol and validators are ready, but the minimum twelve distinct actual
eligible clips, rights and consent receipts, deterministic derivatives, oracle
annotations, review evidence, and coverage are absent. M1 topology measurement
is not allowed. The recording checklist is in
`docs/M1_REAL_VIDEO_CORPUS_AND_ORACLE_PROTOCOL.md`.

Generated metadata reports:

- `reports/m1/corpus/admission-report.json`;
- `reports/m1/corpus/rights-summary.json`;
- `reports/m1/corpus/coverage-summary.json`;
- `reports/m1/corpus/oracle-validation.json`;
- `reports/m1/corpus/decision-report.md`.

No original, derivative, or annotation binary is tracked.

## Execution boundary

- model downloads: 0;
- model loads: 0;
- CUDA runs: 0;
- paid external service calls: 0;
- customer or personal data external transfers: 0;
- backend integration runs: 0;
- topology performance runs: 0.

## Verification

The dedicated M1-A test module passed 16 tests before the predeclaration commit.
Final model-free validation then passed:

- Python compile: passed;
- full Python tests: 156 passed;
- Rust `cargo fmt --check`: passed;
- Rust `cargo check --workspace --locked`: passed;
- Rust `cargo test --workspace --locked`: passed, including 10 runtime tests;
- repository and generated JSON parsing: 52 files passed;
- M1 schemas identify Draft 2020-12: passed;
- M1-A validators and cross-document admission: passed;
- tracked video binaries: 0;
- M1 public absolute-path and credential hits: 0;
- duplicate eligible clip IDs and digests: 0;
- v1/R1/R2/R3 evidence changes: 0;
- `git diff --check`: passed.

The local Python environment does not include the optional third-party
`jsonschema` package. Schema files were parsed, their draft identifiers were
checked, and the repository's dependency-free contract validators and positive
and negative tests supplied instance validation. No package was installed.
