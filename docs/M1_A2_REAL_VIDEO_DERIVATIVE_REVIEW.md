# M1-A2 Real-video Derivative and Human Review Gate

Status: derivatives prepared; phase-one human rights, scene, and privacy
review complete; guided observed-change export retained as auxiliary evidence;
current Gate `ORACLE_PROTOCOL_REVISE`

Tracking: [Issue #48](https://github.com/ksse29077-byte/HIVEFRAME/issues/48),
branch `agent/m1-a2-corpus-derivative-review`

## Purpose and boundary

M1-A2 applies the merged M1-A corpus and oracle contract to twelve explicitly
approved, self-recorded source clips. It inventories immutable originals,
creates deterministic analysis derivatives, prepares conservative oracle
scaffolds, and stops at a human-review Gate.

This is not a topology experiment. The work performs no model download or
load, CUDA execution, paid external call, backend integration, personal-data
transfer, or topology performance run. No source, derivative, contact sheet,
tool executable, consent document, or other media binary is stored in Git.

## Approved evidence scope

Only the approved M1-A2 asset bundle was inspected. Public records use the
abstract prefix `approved-asset:m1-a2` instead of a host path. The bundle
contains twelve distinct originals mapped one-to-one to C01 through C12, a
capture log, a rights declaration, and the designated C01 consent record.

The designated C01 consent record has SHA-256
`f1187f598036db3b23af869bab64e19712dce6459667721b375dbf3be72963d2`.
Its structure includes the clip ID, consent date, permitted use scope,
explicit participant consent, and signer/confirmation markers. The legacy
file named `self_consent.txt` was not used as evidence.

The capture log and rights declaration hashes are respectively:

- `6ccb5dd7725633d0cc12aba03f7f89b34574e34995b4ec601c25268a2d8a5062`;
- `9f19d937ba8f2faba0eb1210ca9208d500f7c4a4667408a108f21195804a54e9`.

These structure checks do not replace the required human visual review.

## Human review phase one

The reviewer-completed checklist was parsed as a controlled input rather than
accepted as a free-form assertion. Its SHA-256 is
`1ca2309aa6996416c662387f62e967a15f66c969743c8157e55af3ea3a23f216`.
It contains exactly C01-C12 in the declared scene-class order. Every row has
`rights_review=yes`, `scene_content_review=yes`, and `privacy_review=yes`.
Every row also retains `oracle_initial_pass=pending_review`,
`blind_re_review=pending_review`, `adjudication=pending_review`, and
`final_status=pending_review`.

The rights receipt and corpus manifest record this bounded progress in the
optional `human_review_progress` object. Their aggregate admission fields
remain pending because phase-one review alone does not establish a verified
Oracle or final corpus eligibility. The public-safe source reference and a
normalized summary are stored in
`data_ledger/m1-a2/human-review-phase-1.json`; the original checklist remains
outside Git with the media review package.

## Tool admission

The FFmpeg project Windows download page links the Gyan Windows builds used by
this task. The exact archive was:

```text
https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip
```

The installed binaries were kept below `approved-asset:m1-a2/tools` and did
not modify system PATH or require administrator privileges.

| Item | Verified value |
|---|---|
| Archive bytes | 92,234,348 |
| Archive SHA-256 | `04861d3339c5ebe38b56c19a15cf2c0cc97f5de4fa8910e4d47e5e6404e4a2d4` |
| FFmpeg version | `7.1.1-essentials_build-www.gyan.dev` |
| FFmpeg SHA-256 | `b90225987bdd042cca09a1efb5e34e9848f2d1dbf5fbcd388753a44145522997` |
| FFprobe version | `7.1.1-essentials_build-www.gyan.dev` |
| FFprobe SHA-256 | `05e8fa639450f8191635192871ae37a3ec3e4638fa12f3b7d49c6522ba16a8ed` |
| Distribution license | GPL-3.0-or-later |
| License-file SHA-256 | `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` |

The complete public-safe installation record is
`data_ledger/m1-a2/ffmpeg-install-record.json`.

## Inventory and deterministic derivative

The original inventory contains twelve distinct SHA-256 values and no
duplicate. Every source was H.264 video in an MP4-family container at
1920x1080 with BT.709 color metadata. C11 carries declared container rotation
of -90 degrees; the derivative contract applies declared rotation and clears
the output rotation metadata.

The fixed derivative contract is:

- 832x480, 16 FPS, FFV1, yuv420p, BT.709, Matroska;
- audio removed;
- aspect-preserving Lanczos scale and black letterbox;
- single-thread encoder and output-side bitexact flag;
- explicit source timestamp/frame mapping;
- no overwrite;
- independent second encode with binary SHA-256 equality;
- full derivative decode validation.

All twelve derivatives passed metadata, full-decode, and deterministic-repeat
checks. Their aggregate size is 189,677,226 bytes. Exact source metadata,
frame counts, derivative byte counts, frame-map hashes, preview hashes, and
source/derivative SHA-256 values are recorded in:

- `data_ledger/m1-a2/original-inventory.json`;
- `data_ledger/m1-a2/derivative-receipts.json`.

Three ineligible preparation attempts are retained in
`data_ledger/m1-a2/failed-attempts.json`. They document an output bitexact flag
placement error, an overly strict declared-rotation check, and an FFprobe CSV
side-data parsing error. All are `results_eligible=false`; none is mixed with
the final derivative evidence.

## Oracle and Gate chronology

No automated signal was promoted to truth. Every adjacent-frame transition is
initially a full-canvas `uncertain` region with confidence 0.0 and review state
`pending`. There are twelve pending oracle records and zero verified records.

The manifest, rights, oracle, and cross-document validators report no
structural error. Admission nevertheless remains:

```text
RIGHTS_REVIEW_BLOCKED
```

Counts are investigated 12, pending 12, eligible 0, rejected 0. Phase-one
human rights, scene-content, and privacy review is complete for 12/12 clips;
Oracle initial pass, blind re-review, adjudication, and final status are
complete for 0/12. Eligible coverage therefore remains 0/12. Therefore
`results_eligible_for_topology_performance=false` and
`M1_CORPUS_AND_ORACLE_READY` is not issued.

After the Guided Oracle export was returned, the claim boundary was corrected.
Visible frame change is not backend compute relevance or safe-skip truth. The
current Gate is `ORACLE_PROTOCOL_REVISE`. The old `RIGHTS_REVIEW_BLOCKED`
report is retained unchanged as chronological evidence. Current safe-skip
truth, verified compute-relevance Oracle, and eligible backend
selective-compute result counts are all zero. The Guided Oracle export is
auxiliary observed-change evidence only. Blind re-review, adjudication, and
verified promotion under the superseded protocol are stopped.

## Guided Oracle initial-review package

The first local browser form is preserved as superseded usability-history
evidence. It required a general reviewer to discover every frame interval and
draw every dirty, stable, or uncertain region from scratch. The reviewer
stopped before adding a row or exporting a result. Therefore no v1 input was
accepted, and the completed 12/12 phase-one rights, scene, and privacy review
remains unchanged.

The replacement package is a model-free, guided human-review tool. It reuses
the twelve already decoded H.264 review proxies and produces proposals with:

- CPU-decoded 208x120 grayscale frames;
- adjacent-frame absolute differences with fixed pixel and tile thresholds;
- four-connected changed-tile components, padded bounding boxes, and overlap
  merging;
- fixed windows of 16 adjacent transitions, preserving full temporal
  coverage while bounding the review queue;
- the largest adjacent-frame differences as eight C07 hard-cut candidates;
- semantic review suggestions for C04/C05/C06/C12 camera motion, C08
  occlusion/disocclusion, C11 lighting change, and C07 scene cut.

Across C01-C12, the generated package contains 110 proposal intervals, 106
dirty boxes, 17 uncertain boxes, and eight C07 cut candidates. These numbers
are proposals only. Compression noise, shadows, reflections, texture,
low-contrast motion, and coarse low-resolution boxes can cause false positives
or misses. Nothing from this method is a model inference, verified Oracle, or
eligible performance evidence.

The screen displays previous and later frames, the suggested overlay, frame
range, flags, and progress. The primary actions are `제안이 맞음`, `수정 필요`,
and `판단 어려움`. A reviewer can move, resize, delete, or add dirty/uncertain
boxes without typing coordinates. The stable region is the computed
full-canvas complement. Completion rejects invalid ranges, temporal gaps,
overlapping boxes, incomplete spatial partitions, unreviewed suggestions, or
an invalid C07 hard cut. A confirmed C07 cut creates exactly one full-canvas
dirty, `scene_cut=true`, `full_reobserve=true` override, but still retains
`pending_review`.

The package stores work in browser local storage and exports CSV plus JSON only
after all twelve clips pass initial-input validation. Every export explicitly
records `automatic_proposals_are_truth=false`, `oracle_initial_pass`,
`blind_re_review`, `adjudication`, and `final_status` as `pending_review`, with
eligible and verified counts at zero. Media, per-frame proposals, local form
state, and reviewer exports remain outside Git. The public-safe method receipt
is `data_ledger/m1-a2/guided-oracle-proposal-method.json`.

## Superseded human-review instructions

The steps below are retained only to explain the previous package. Do not
continue them. A replacement compute-relevance and backend-capability protocol
requires separate approval.

For each C01-C12 clip, the reviewer must:

1. open the guided local tool, select the clip, replay the proposed interval,
   and compare its A/B frames and overlay;
2. click `제안이 맞음`, `수정 필요`, or `판단 어려움`; when needed, move,
   resize, delete, or add only the affected dirty/uncertain boxes and confirm
   the suggested semantic flags;
3. for C07, choose the exact hard-cut transition from the ranked candidates or
   the current playback transition;
4. click the per-clip completion button after the partition and coverage
   checks pass, then export the completed initial-pass CSV and JSON without
   changing their `pending_review` status;
5. historically, a later step would have performed a time-separated blind
   re-review, record disagreements, and record
   adjudication rather than silently overwriting the initial pass;
6. leave unresolved or questionable clips `pending` or mark them `rejected`.

The guided package contains first-screen Korean instructions, the browser form,
the existing review proxies by relative reference, proposals, and its package
receipt. It remains outside Git. A later, explicitly
approved protocol-revision task must first define compute-relevance and
backend capability truth. The existing observed-change export cannot be
converted to eligible/verified backend evidence and must not start topology or
backend performance measurement automatically.
