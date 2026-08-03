# 2026-08-03 — M1-A2 Real-video Derivative Review Preparation

Status: evidence prepared; phase-one human rights, scene, and privacy review
complete; Oracle review pending; Gate `RIGHTS_REVIEW_BLOCKED`

## Predecessor and tracking state

- PR #47 is merged into `main` at
  `b50051b57de819e1481bd0ff71634fa631cca345`;
- Issue #46 is closed;
- M1-A protocol remains unchanged;
- Issue [#48](https://github.com/ksse29077-byte/HIVEFRAME/issues/48)
  tracks this bounded derivative and review-package pass;
- dedicated branch: `agent/m1-a2-corpus-derivative-review`.

M0, M1-P0 v1/R1/R2/R3, and the initial empty-corpus M1-A evidence were not
rewritten. This pass does not authorize or execute topology measurement.

## Approved scope and consent verification

Only the explicitly approved M1-A2 asset bundle and its descendants were
inspected. No user profile, personal media library, cloud-drive root, unrelated
drive, or network video source was searched. Public artifacts use
`approved-asset:m1-a2` references and contain no host absolute path.

The exact designated C01 consent record exists and has SHA-256
`f1187f598036db3b23af869bab64e19712dce6459667721b375dbf3be72963d2`.
It includes the required clip ID, date, permitted-use scope, explicit consent,
and signer/confirmation structure. The legacy `self_consent.txt` file was
excluded from the evidence set.

The capture log hash is
`6ccb5dd7725633d0cc12aba03f7f89b34574e34995b4ec601c25268a2d8a5062`;
the rights declaration hash is
`9f19d937ba8f2faba0eb1210ca9208d500f7c4a4667408a108f21195804a54e9`.

## Tool installation record

FFmpeg/FFprobe 7.1.1 was downloaded only into the approved asset bundle from
the exact Gyan release archive linked through the FFmpeg Windows download
page. The archive is 92,234,348 bytes with SHA-256
`04861d3339c5ebe38b56c19a15cf2c0cc97f5de4fa8910e4d47e5e6404e4a2d4`.

Verified executable hashes:

- FFmpeg: `b90225987bdd042cca09a1efb5e34e9848f2d1dbf5fbcd388753a44145522997`;
- FFprobe: `05e8fa639450f8191635192871ae37a3ec3e4638fa12f3b7d49c6522ba16a8ed`.

Both report `7.1.1-essentials_build-www.gyan.dev`. The recorded distribution
license is GPL-3.0-or-later; the included license file has SHA-256
`8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`.
System PATH was not modified, administrator privileges were not used, and no
tool binary was added to Git.

## Inventory and derivative evidence

Twelve distinct C01-C12 originals were found and matched their preflight
SHA-256 values. The original inventory records H.264/MP4-family, 1920x1080,
BT.709 sources and the declared rotation for C11. Original hashes and sizes
were rechecked after preparation; all twelve remained unchanged.

The fixed 832x480, 16 FPS, FFV1/yuv420p/BT.709 derivative was encoded twice per
clip. All twelve independent binary hashes matched and every final derivative
fully decoded. Audio was removed. The final derivatives total 189,677,226
bytes. Originals, derivatives, contact sheets, frame maps, and full pending
oracles remain outside Git; sanitized metadata and hashes are in
`data_ledger/m1-a2` and `reports/m1/corpus/a2`.

Three failed attempts were preserved as ineligible evidence:

1. output bitexact was initially placed in the input option group, so Matroska
   binary hashes differed even though decoded frames matched;
2. a valid C11 -90-degree declared rotation was rejected too early;
3. C11 display-matrix side data contaminated CSV timestamp parsing.

The corrections moved the flag to the output group, accepted declared
quarter/half turns while retaining contract checks, and parsed only
`best_effort_timestamp_time` from FFprobe JSON. The failed attempt records are
`results_eligible=false` and are not included in final counts.

## Oracle and Gate

The generated oracle is deliberately conservative: every transition starts as
full-canvas `uncertain`, confidence 0.0, `pending_review`. No frame difference,
optical flow, or other automated output was promoted to a verified label.

Final metadata counts:

- investigated originals: 12;
- deterministic derivatives: 12;
- pending rights records: 12;
- pending oracle records: 12;
- eligible clips: 0;
- verified oracles: 0;
- rejected clips: 0;
- topology performance runs: 0.

Corpus, rights, oracle, and cross-document validators report no structural
errors. The Gate is **`RIGHTS_REVIEW_BLOCKED`**, eligible coverage is 0/12,
and `results_eligible_for_topology_performance=false`. The apparent filename
and capture-record coverage of twelve required scene classes is not counted as
eligible coverage before human review. `M1_CORPUS_AND_ORACLE_READY` was not
issued.

## Human review phase-one reconciliation

The reviewer returned the original controlled checklist after directly
inspecting C01-C12 originals and derivatives. The file was read only from the
approved asset bundle. It is 1,347 bytes and has SHA-256
`1ca2309aa6996416c662387f62e967a15f66c969743c8157e55af3ea3a23f216`.
Validation required the exact nine-column header, one row for every clip in
C01-C12 order, and the expected scene-class mapping from the frozen corpus
config. There were no missing, duplicate, extra, or scene-class-mismatched
rows.

All twelve rows contain:

- `rights_review=yes`;
- `scene_content_review=yes`;
- `privacy_review=yes`;
- `oracle_initial_pass=pending_review`;
- `blind_re_review=pending_review`;
- `adjudication=pending_review`;
- `final_status=pending_review`.

The result is recorded as **human phase-one rights, scene, and privacy review
complete**, not as corpus admission. Optional `human_review_progress` records
were added consistently to the pending corpus manifest and rights receipt.
The aggregate clip `review_status`, source-rights admission, eligibility,
sensitive-content disposition, and Oracle fields remain pending. This avoids
misrepresenting three completed checklist columns as a verified Oracle or a
final rights-admission decision. Older evidence remains Schema-compatible
because the progress object is optional.

`data_ledger/m1-a2/human-review-phase-1.json` is the normalized, public-safe
receipt. It records the checklist digest and abstract storage reference but no
host path or media. The regenerated admission report records 12/12 phase-one
reviews, 0/12 initial Oracle passes, 0/12 blind re-reviews, 0/12 adjudications,
and 0/12 final statuses. The protected outcome remains pending clips 12,
eligible clips 0, verified Oracles 0, rejected clips 0, eligible coverage 0/12,
and Gate `RIGHTS_REVIEW_BLOCKED`.

## Local visual Oracle initial-review package

A separate offline package was generated below the approved review bundle. It
contains a self-contained HTML form, Korean instructions, a blank CSV export
template, a package receipt, and twelve H.264 browser-review proxies. The
proxies were CPU-transcoded from the immutable FFV1 derivatives at 832x480,
16 FPS, yuv420p, with audio and metadata removed. Each proxy was fully decoded
after creation. They exist only for local visual convenience, are explicitly
ineligible evidence, and are not tracked by Git.

The form provides:

- C01-C12 selection, playback, pause, and one-frame stepping;
- A/B comparison captures and frame-range start/end controls;
- mouse-drawn or full-frame regions classified as dirty, stable, or uncertain;
- camera motion, occlusion, disocclusion, lighting change, scene cut, and
  full-reobserve fields;
- row addition/deletion, reviewer notes, browser-local draft storage, and CSV
  plus JSON export;
- a C07-specific warning requiring the exact hard-cut transition, full-frame
  dirty region, and full re-observation.

The reviewer does not edit JSON or coordinates directly. All exported rows
retain `pending_review`. No frame difference, optical flow, or automatic label
was produced in this task; the receipt stores `value=null`,
`status=not_collected`, the method, and the reason. This is stricter than
silently treating an unavailable suggestion as zero or truth.

Static tests covered the UI contract and export semantics, and all twelve
proxies passed full decode. The in-app browser refused the local `file://`
URL under its navigation security policy; no local server or policy workaround
was introduced. The package is intended to be opened directly in a local Edge
or Chrome window.

## Derivative-preparation verification

Final repository-wide model-free verification passed:

- focused M1-A2 tests: 8 passed;
- Python compile: passed;
- full Python tests: 179 run, 178 passed, one optional external-Schema test
  explicitly skipped;
- `cargo fmt --all -- --check`: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 10 runtime tests;
- repository JSON parsing: 62 files passed;
- public absolute-path findings: 0;
- credential/private-key findings: 0;
- newly tracked media, archive, or tool binaries: 0;
- M1-P0 v1/R1/R2/R3 report changes: 0;
- `git diff --check`: passed.

The first full-test attempt used Ubuntu's system Python 3.12.3 and stopped at
six import errors because that interpreter does not provide NumPy. No package
was installed. The test was rerun with the already-recorded HIVEFRAME Python
3.10.20 environment and NumPy 1.26.4.

That rerun initially exposed two pre-existing R3 raw-byte hash failures because
the Windows checkout had smudged one LF JSON blob to CRLF. The Git blob and R3
evidence were unchanged. Restoring that clean working file to the exact indexed
LF bytes made its SHA-256 match the frozen predeclaration, after which all 179
tests completed successfully. No R3 source, report, receipt, threshold,
measurement, or commit was changed.

Model downloads, model loads, CUDA runs, paid external calls, external
personal-data transfers, backend integration runs, and topology performance
runs are all 0.

## Phase-one and Oracle-package verification

After applying the reviewer checklist and adding the visual tool, the complete
model-free verification was repeated:

- focused phase-one and Oracle-package tests: 11 passed;
- Python compile: passed;
- full Python tests: 190 run, 189 passed, one optional external-Schema test
  explicitly skipped;
- `cargo fmt --all -- --check`: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 10 runtime tests;
- repository JSON parsing: 65 files passed;
- public absolute-path and personal-identifier findings: 0;
- credential/private-key findings: 0;
- tracked media, archive, or tool binaries: 0;
- M1-P0 v1/R1/R2/R3 report changes: 0;
- `git diff --check`: passed;
- local Oracle package: 16 files, 21,346,627 bytes, 12/12 proxies fully
  decoded at creation.

The first full Python attempt in this update passed all new M1-A2 tests but
reproduced the two known R3 raw-byte assertions against the Windows CRLF
checkout of the frozen config. The file was restored immediately. The suite
was then run with the exact LF bytes from the unchanged Git blob and passed all
190 tests; the Windows checkout was restored afterward. This was a test-only
normalization, not an R3 evidence edit.

Model downloads, model loads, CUDA runs, paid external calls, external
personal-data transfers, backend integration runs, and topology performance
runs remained 0 throughout this update.

## Remaining human review blocker

Phase-one rights, scene-content, and privacy inspection is complete. The
reviewer must now use the local visual form to complete the initial transition
Oracle for C01-C12 and identify the exact C07 hard cut. A later, separately
authorized, time-separated blind re-review must preserve the initial pass,
record disagreements, and adjudicate them explicitly. Until those human steps
are received and validated, all Oracle and final statuses stay
`pending_review`; no clip becomes eligible or verified. No later M1 topology
work may start without a separate approval after a fresh Gate result.
