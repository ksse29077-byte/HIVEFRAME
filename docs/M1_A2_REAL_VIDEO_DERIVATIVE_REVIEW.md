# M1-A2 Real-video Derivative and Human Review Gate

Status: derivatives prepared; phase-one human rights, scene, and privacy
review complete; Oracle review pending

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

## Pending Oracle and Gate

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

## Oracle initial-review package

A local-only, browser-based review tool was generated beside the media. It
uses H.264 review proxies derived from the existing FFV1 analysis derivatives;
all twelve proxies passed complete decode. The tool does not edit JSON or
coordinates directly. It lets the reviewer play a clip, capture A/B frames,
select a frame range, draw a region, classify it as dirty/stable/uncertain,
and record camera motion, occlusion/disocclusion, lighting change, scene cut,
full re-observation, and notes. It explicitly warns that C07 requires the
exact hard-cut transition.

The tool stores work in browser local storage and exports a CSV plus JSON.
Every export remains `pending_review`. No frame-difference, optical-flow, or
other automated annotation was generated in this pass; the package receipt
records automated suggestion status as `not_collected` with a reason rather
than inventing a value. Media proxies, local form state, and reviewer exports
remain outside Git.

## Remaining human review

For each C01-C12 clip, the reviewer must:

1. open the local Oracle review tool and label every relevant derivative-frame
   interval as a complete,
   non-overlapping dirty/stable/uncertain partition and record preserve,
   object, camera, occlusion, reflection, fine-boundary, lighting, and decoder
   semantics where applicable;
2. for C07, mark the exact hard-cut transition, full-canvas dirty coverage,
   `full_reobserve=true`, and invalidated identities;
3. export the completed initial-pass CSV and JSON without changing their
   `pending_review` status;
4. in a later separately authorized step, perform a time-separated blind
   re-review, record disagreements, and record
   adjudication rather than silently overwriting the initial pass;
5. leave unresolved or questionable clips `pending` or mark them `rejected`.

The local review package contains Korean instructions, a browser form, review
proxies, a blank CSV template, the package receipt, contact sheets, frame maps,
and the complete pending Oracle. It remains outside Git. A later, explicitly
approved review-finalization task may convert only confirmed clips to
eligible/verified and rerun the admission Gate. It may not start topology
performance measurement automatically.
