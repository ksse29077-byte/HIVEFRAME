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

## Superseded v1 local visual Oracle package

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

The reviewer did not add any review row or export any result. Actual Oracle
input with this form was stopped because it still required a general reviewer
to identify every interval and create every region from scratch. The package,
code, and receipt are retained as usability-improvement evidence and marked
superseded; they are not accepted Oracle evidence.

All potential v1 exports would have retained `pending_review`. No frame
difference, optical flow, or automatic label was produced in that package; the receipt stores `value=null`,
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

## Guided human-review v2

### Usability problem and design decision

The v1 form reduced direct JSON editing, but it did not reduce the central
cognitive burden: a reviewer still had to discover frame ranges and author
dirty/stable/uncertain geometry from an empty canvas. That is unsuitable for a
general reviewer and creates avoidable annotation inconsistency. The user
therefore stopped the initial Oracle entry before adding any row or exporting
any file. The already-completed 12/12 phase-one rights, scene-content, and
privacy decisions and their checklist SHA-256 remain unchanged.

The replacement treats automation only as a proposal generator. FFmpeg decodes
each existing derivative on CPU to 208x120 grayscale. For each adjacent pair,
the implementation computes absolute differences, applies fixed pixel/tile
thresholds, extracts four-connected changed-tile components, expands their
boxes, and merges overlaps. Sixteen adjacent transitions are grouped into each
review interval so every transition is covered without presenting hundreds of
single-transition rows. The stable region is never hand-drawn: it is derived
as the exact full-canvas complement of non-overlapping dirty and uncertain
boxes.

Three internal tuning attempts occurred before any human review used v2:

1. the first package produced 398 intervals, five dirty boxes, and 313
   uncertain boxes; it was discarded as too burdensome;
2. fixed 16-transition grouping produced 110 intervals but zero dirty and 123
   uncertain boxes; it was discarded because merge state was overly
   conservative;
3. retaining the strongest merged score produced the final 110 intervals, 106
   dirty boxes, and 17 uncertain boxes.

Only the final package is offered for review. The two rejected local packages
were never reviewed, exported, committed, or used as evidence. No threshold
result is represented as truth.

### Proposal inventory and semantics

| Clip | Frames | Intervals | Dirty boxes | Uncertain boxes | Cut candidates |
|---|---:|---:|---:|---:|---:|
| C01 | 205 | 13 | 12 | 2 | 0 |
| C02 | 150 | 10 | 10 | 1 | 0 |
| C03 | 90 | 6 | 6 | 0 | 0 |
| C04 | 121 | 8 | 8 | 0 | 0 |
| C05 | 154 | 10 | 10 | 0 | 0 |
| C06 | 151 | 10 | 9 | 1 | 0 |
| C07 | 127 | 8 | 8 | 0 | 8 |
| C08 | 143 | 9 | 9 | 1 | 0 |
| C09 | 132 | 9 | 9 | 0 | 0 |
| C10 | 100 | 7 | 7 | 4 | 0 |
| C11 | 139 | 9 | 7 | 6 | 0 |
| C12 | 165 | 11 | 11 | 2 | 0 |

Camera-motion suggestions are seeded for C04, C05, C06, and C12;
occlusion/disocclusion for C08; lighting change for C11; and scene-cut
candidates for C07. These are scene-class-informed review prompts, not
semantic inference. C07 lists the eight largest adjacent-frame differences and
requires the reviewer to select exactly one transition. Selection creates a
full-canvas dirty, `scene_cut=true`, `full_reobserve=true` override, while its
status remains `pending_review` until later protocol stages.

The known limitations are compression noise, shadows, reflections, texture
false positives, missed small/low-contrast motion, and coarse low-resolution
boxes. Accordingly every proposal starts with `human_decision=unreviewed`,
`review_status=pending_review`, `eligible=false`, and the receipt states
`automatic_proposals_are_truth=false`.

### Human interaction and completion checks

The self-contained Korean screen presents A/B frames, overlay, proposal range,
playback, semantic flags, and clip progress. A reviewer chooses `제안이 맞음`,
`수정 필요`, or `판단 어려움`. Boxes can be moved, resized, deleted, or added
as dirty/uncertain without coordinate entry. Status is one of `미검수`,
`검수 중`, `수정 필요`, or `1차 검수 완료`.

Per-clip completion verifies valid and gap-free frame ranges, complete
transition coverage, non-overlapping dirty/uncertain boxes, an exact
full-canvas partition after stable-complement derivation, no unresolved
proposal or candidate flag, and the C07 exact-cut rule. JSON/CSV export is
blocked until all twelve clips pass this initial-input validation. Exported
status fields nevertheless remain `pending_review`; initial completion is not
blind re-review, adjudication, verification, eligibility, or admission.

### Verification of the final local package

The final proposal document has SHA-256
`3a8b0942c12a98f34d5580d2c79372101cd9479470720e5f5966f3ba79e0b015`.
All 110 intervals cover every adjacent transition without a temporal gap. Each
generated spatial partition covers exactly 832x480 with no overlap. The final
package receipt matches the proposal digest, records eligible clips 0,
verified Oracles 0, Gate `RIGHTS_REVIEW_BLOCKED`, and all prohibited execution
counts as zero.

Browser verification exercised the final UI through a temporary loopback-only
static server. C01 initially showed 0/13 reviewed proposals; clicking
`제안이 맞음` recorded 1/13 and advanced from frames 0-16 to 16-32. Reset then
returned C01 to 0/13. C07 displayed its eight ranked candidate transitions and
the current-playback selection action. The browser console reported zero
errors. The temporary server and logs were stopped and removed after testing.

Public evidence consists of the implementation, tests, and
`data_ledger/m1-a2/guided-oracle-proposal-method.json`. Media, full proposals,
browser local storage, and later reviewer exports remain only in the approved
asset bundle. The v1 package contains a local superseded marker that points to
the guided sibling package.

### Guided v2 final verification

Final model-free verification after the C07 exact-cut auto-entry check passed:

- guided-review focused tests: 9 passed;
- Python compile: passed;
- full Python tests: 199 run, 198 passed, one optional external-Schema test
  explicitly skipped;
- `cargo fmt --all -- --check`: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 10 runtime tests;
- repository JSON parsing: 66 files passed;
- external proposal temporal coverage: 110/110 intervals passed;
- external spatial complement validation: 110/110 intervals passed;
- human decisions before review: 110/110 `unreviewed`;
- proposal/receipt SHA-256 link: passed;
- public absolute-path and credential findings in changed content: 0;
- newly tracked video, archive, or tool binaries: 0;
- M1-P0 v1/R1/R2/R3 evidence changes: 0;
- `git diff --check`: passed.

The unavailable Windows Python launcher and an embedded-Python import-path
omission caused two initial test-launch commands to exit before collecting any
test. The existing embedded environment was then invoked with the repository
module path explicitly. As in the preceding branch verification, the unchanged
R3 JSON Git blob was used with exact LF bytes only during the full suite and
the original Windows checkout bytes were restored afterward. No protected
evidence changed.

Model downloads 0, model loads 0, CUDA runs 0, paid external service calls 0,
external personal-data transfers 0, backend integration runs 0, and topology
performance runs 0. No Oracle proposal was promoted to verified truth or
eligible evidence.

## Remaining human review blocker

Phase-one rights, scene-content, and privacy inspection is complete. The
reviewer must now use the guided v2 local visual form to confirm or correct the
initial transition proposals for C01-C12 and identify the exact C07 hard cut.
The superseded v1 form must not be used. A later, separately
authorized, time-separated blind re-review must preserve the initial pass,
record disagreements, and adjudicate them explicitly. Until those human steps
are received and validated, all Oracle and final statuses stay
`pending_review`; no clip becomes eligible or verified. No later M1 topology
work may start without a separate approval after a fresh Gate result.
