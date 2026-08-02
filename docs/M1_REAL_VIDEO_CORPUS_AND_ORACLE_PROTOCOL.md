# M1-A Rights-cleared Real-video Corpus and Oracle Protocol

Status: predeclared protocol; no topology performance results

## Purpose and claim boundary

M1-A asks whether HIVEFRAME can assemble a reproducible, rights-cleared set of
actual videos and a human-verified oracle framework for a later topology safety
and cost experiment. It does not run that experiment.

M1-P0 is complete with `RUST_CONTROL_PLANE_ADMITTED`. Compound Perception First
remains the project direction. T0 Mono remains a comparator and safety fallback,
not the default product direction. M0 remains independently `in_progress`.

M1-A cannot establish a topology advantage, generation quality, total accepted-
result cost, GPU savings, user-time savings, product speedup, or M1 completion.
It does not download or load a model, use CUDA or a paid service, upload customer
or personal data, or implement a backend.

## Admission unit and storage boundary

The corpus minimum is twelve distinct actual video clips. Synthetic tensors,
test fixtures, static image sequences, duplicate clips, and near-identical
fillers are not actual-video coverage. One clip may cover more than one required
scene class, but every eligible original must have a distinct SHA-256.

Git stores metadata only: manifest and rights receipts, hashes and byte counts,
decoder metadata, derivative and oracle hashes, abstract storage references,
validation outcomes, and coverage. It never stores original or derivative
video binaries. Allowed storage classes are:

- `local_approved_artifact_store`;
- `external_digest_store`;
- `repository_metadata_only`;
- `user_supplied_secure_storage`.

Public files must not contain local absolute paths, usernames, private URLs,
credentials, tokens, memory addresses, or concrete temporary paths.

## Rights and consent decision

Every investigated clip receives exactly one conservative classification:

- `eligible_self_recorded`;
- `eligible_public_domain`;
- `eligible_cc0`;
- `eligible_explicit_license`;
- `pending_rights_review`;
- `rejected`.

Eligibility requires verified rights holder or official source authority,
preserved license terms and digest, and explicit answers for research,
commercial use, copying, derivatives, redistribution, attribution, identifiable
people, consent, restrictions, and sensitive content. Rights are never inferred
from public accessibility or lack of a watermark. Pending and rejected material
is excluded from the eligible corpus and later measurements.

This engineering admission record is not legal advice. A later commercial
release may require additional legal review even when research admission passes.

## Deterministic analysis derivative

The original remains immutable. The derivative contract in
`configs/m1-real-video-corpus.json` pins decoder and version, orientation,
colorspace, bit depth, alpha, aspect ratio, crop, letterbox, resize, target
resolution and FPS, sampling, variable-frame-rate handling, audio, output
representation, frame mapping, and tool version.

The public command is a template, never a captured local command:

```text
<decoder> -i <original-input> -map 0:v:0 -an -vf <declared-filter-chain> -c:v ffv1 <analysis-output>
```

Each derivative records its SHA-256 and a mapping from derivative frame index
to source timestamp and source frame index. The contract cannot be tuned after
viewing topology results.

## Oracle semantics

For each adjacent-frame transition, the primary labels form a complete,
non-overlapping canvas partition:

- `dirty`: meaningful spatiotemporal change that is unsafe to ignore;
- `stable`: safely reusable only under the declared observation scope;
- `uncertain`: unresolved evidence that requires re-observation or fallback.

`preserve` is an orthogonal edit-policy label. It may overlap stable, but never
dirty or uncertain. The oracle distinguishes object and camera motion,
occlusion, disocclusion, scene cuts, lighting and shadows, reflections and
mirrors, hair, water, smoke, compression, noise, decoder artifacts, and
preserve-only changes. Pixel difference alone cannot establish the final label.

Automated tools may assist, but a human review is final. Multi-reviewer work
records disagreement and adjudication. If only one annotator is available, the
protocol requires an initial pass, a time-separated blind re-review, explicit
disagreement recording, adjudication, and limitations. Corrections increment
the annotation version; they do not overwrite prior evidence.

Annotations use compact bounding boxes, polygons, or row-major RLE plus a
semantic reference and hash. The same full mask or semantic payload is not
repeated per sample.

## Scene-cut rule

A hard cut invalidates prior stable regions, object identities, topology, and
cache assumptions. Its transition must cover the full canvas as dirty, declare
`full_reobserve=true`, and record invalidated object IDs. Missing cuts, wrong
transition mapping, retained pre-cut stable state, and unjustified object IDs
are validator failures.

## Candidate topology contract

`configs/m1-topology-candidates.json` fixes T0 through T7:

- T0 Mono;
- T1 global-low plus fixed 2x2;
- T2 global-low plus fixed 4x4;
- T3 adaptive quadtree;
- T4 object-centered;
- T5 motion-centered;
- T6 multi-resolution;
- T7 mixed spatial-temporal.

Every candidate declares eye roles, receptive and write policies, overlap,
temporal window and stride, activation, global safety eye, uncertainty
promotion, scene-cut behavior, fallback, and unsupported behavior. M1-A does
not execute or rank these candidates.

## Measurement contract and provisional safety Gate

`configs/m1-measurement-contract.json` predeclares accuracy, cost, and combined
metrics but contains no result. Metrics declare units, clip/transition/topology
scope, aggregation, and unavailable semantics. Complete cost must include
decode, derivative preparation, eye setup, routing, coordinates, observation,
fusion, state, plan, FFI/buffer handoff, receipts, uncertainty promotion,
fallback, and failed attempts.

The premeasurement proposal carries forward the roadmap targets of dirty recall
at least 0.995 and false-stable at most 0.005. Cut misses and preserve violations
have zero allowance. Uncertainty always re-observes or falls back. M1-A records
no pass/fail result against these thresholds.

Unavailable or pending facts use this structure instead of zero, false, or an
empty string:

```json
{"value": null, "status": "unavailable", "reason": "...", "method": "..."}
```

## Validators

- `m1_rights_validator.py` checks source authority, rights, commercial and
  derivative permissions, attribution, consent, restrictions, and evidence.
- `m1_corpus_validator.py` checks metadata, hashes, distinct originals,
  derivative pins, storage references, coverage, and tracked binaries.
- `m1_oracle_validator.py` checks masks, bounds, polygons, RLE, transition
  coverage, cuts, object references, semantic references, and annotation hash.
- `m1_corpus_summary.py` checks cross-document admission and emits a single
  declared Gate without modifying input metadata.

Validators fail explicitly and never accept, repair, relabel, or fill missing
facts automatically.

## Required real-video coverage

The eligible corpus must collectively cover:

1. static background with a speaking person;
2. static background with hand motion;
3. static background with local object motion;
4. slow pan;
5. zoom in/out;
6. handheld shake;
7. hard cut;
8. multiple objects and occlusion;
9. reflection or mirror;
10. hair, water, or smoke complex boundary;
11. lighting change;
12. local static content combined with global camera motion.

## Recording and acquisition checklist

For every missing class, define the scene and oracle purpose before recording.
Use a short clip with a declared target duration, resolution, and FPS. Record:

- camera position and intended pan/zoom/shake or locked state;
- local motion, static background, objects, occlusion, and boundary stress;
- lighting state and any planned cut;
- privacy review, identifiable people, signed consent, sensitive content;
- visible logos, screens, artwork, music, and third-party property;
- capture device metadata and original container/codec/timestamps;
- neutral file naming, original byte count, and SHA-256;
- rights-holder and consent receipt identifiers;
- approved storage class and abstract reference.

Recording does not auto-admit a clip. Rights, consent, digest, derivative,
oracle, independent review, and validator checks still apply.

## M1-A decision

Exactly one result is allowed:

- `M1_CORPUS_AND_ORACLE_READY`;
- `CORPUS_ACQUISITION_REQUIRED`;
- `RIGHTS_REVIEW_BLOCKED`;
- `ORACLE_PROTOCOL_REVISE`.

Only the first permits a separately approved later topology measurement. None
closes M1, changes M0, authorizes backend integration, or proves speedup.
