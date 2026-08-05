# P0-LR — MiniMax H3 local-model-ready product vertical slice

Date: 2026-08-05

Issue: [#53](https://github.com/ksse29077-byte/HIVEFRAME/issues/53)

Branch: `product/p0-h3-vertical-slice`

Draft PR: [#54](https://github.com/ksse29077-byte/HIVEFRAME/pull/54)

Source main: `4ddb6a5c7e47b776c9904d32e33c85a63b4ad526`

Starting branch head: `8f9ec538b94bcf09ec39b6ea8f4bcc4d017327f9`

Decision: `P0_LOCAL_READY_WAITING_FOR_ARTIFACT`

## Product question

Can HIVEFRAME remain useful while the official MiniMax H3 local artifact is
unpublished, then connect that artifact after an explicitly approved source,
revision, download, and execution contract are supplied?

P0-LR answers only the product-structure part. It provides one screen, a
functional H3-shaped request, persisted jobs and feedback, an offline Mock H3
path, and a local backend boundary whose default state is `artifact_pending`.
It does not download, load, infer with, benchmark, or claim support for an H3
model artifact.

## Preserved evidence and constitution check

The existing P0 UI/SQLite/feedback work and all merged M0/M1 evidence were
preserved. The correction stayed on Issue #53, the existing product branch,
and Draft PR #54. No new issue, branch, PR, RFC, R2, or R3 was created. The
Product-First Constitution was not duplicated or changed. The product question
was narrowed from an API-shaped future integration to the smallest safe local-
model-ready path; no constitution conflict was found.

## Functional contract represented

The public MiniMax product documentation is treated as a functional request
contract, not as proof of a local Diffusers implementation. P0-LR records:

- model contract `MiniMax-H3`;
- content types `text`, `image`, `video`, and `audio`;
- roles `first_frame`, `last_frame`, `reference_image`, `reference_video`, and
  `reference_audio`;
- at least one non-empty text item;
- mutual exclusion between the frame group and multimodal-reference group;
- rejection of reference audio without an image or video reference;
- resolutions `768P` and `2K`, integer durations 4–15 seconds, and the declared
  adaptive/concrete ratio set;
- concrete ratio for text-to-video and adaptive normalization for first/last-
  frame modes;
- asset IDs, never API URLs, for media content;
- an internal `aigc_watermark` field.

Only prompt, optional first-frame image, 768P, 4 seconds, 16:9, and the explicit
Mock/Local selector appear in P0 UI. Other contract fields remain internal.
The local pipeline class, loader arguments, dependencies, tensor format,
scheduler, output object, offload behavior, encoding path, and audio-module
layout remain unverified implementation details.

## Product implementation

- `H3ContentItem` and `H3GenerationRequest` validate and serialize the bounded
  functional contract; `schemas/h3_generation_request.schema.json` mirrors the
  JSON shape.
- SQLite stores the backend-neutral request JSON, backend job ID, backend state,
  and asset IDs. It does not require provider IDs, provider polling, API costs,
  API keys, or backend-transfer consent.
- `MockH3Backend` remains deterministic and explicitly emits a JSON Mock
  artifact saying that no real video or network call occurred.
- `MiniMaxH3LocalBackend` implements runtime/source inspection, prepare/load/
  unload, job creation/status, generation/cancellation, output normalization,
  errors, and receipts.
- `LocalPipelineFactory` is the single coarse future loader boundary. Torch and
  Diffusers are lazy imports; a missing source triggers no imports. A fake
  factory can be injected for tests. Pipeline objects are never stored in
  SQLite.
- local-files-only mode resolves only an existing local directory or an
  existing revision-pinned Hugging Face cache snapshot. It has no network
  fallback and no automatic download.
- unload drops the pipeline reference, runs garbage collection, and invokes an
  optional CUDA cache hook only if torch is already imported and CUDA is
  available. Unload does not import torch.
- the artifact root remains outside Git, reference filenames reject traversal,
  and assets are created exclusively without overwrite.
- UI shows `Local H3: Waiting for official model files` in the default state,
  disables Local generation, and leaves Mock H3 explicitly selectable. It never
  automatically converts a Local request into a Mock success.

## State and error semantics

Product jobs retain `queued`, `running`, `succeeded`, `failed`, and `cancelled`.
Local readiness is separate: `artifact_pending`, `artifact_configured`,
`artifact_ready`, runtime unavailable/incompatible, model loading/ready, and
generation running/succeeded/failed.

With no source configured:

- `prepare_model()` returns `artifact_pending`, zero downloads, and zero network
  calls;
- `load_model()` raises `model_source_not_configured`;
- a Local generation job fails as `local_backend_unavailable` and is never
  recorded as success.

Other declared local failures include artifact not found, runtime unavailable
or incompatible, unsupported dtype/device map, model-load failure, generation
failure/cancellation, missing output, unsupported output contract, and artifact
save failure. Rate-limit/provider fixtures remain Mock-only test semantics.
Maximum retry remains one and is manual.

## Environment contract and privacy

The future integration reads these environment variables without model-source
or revision defaults:

```text
HIVEFRAME_H3_MODEL_SOURCE
HIVEFRAME_H3_MODEL_REVISION
HIVEFRAME_H3_LOCAL_ENABLED=false
HIVEFRAME_H3_LOCAL_FILES_ONLY=true
HIVEFRAME_H3_DTYPE=bfloat16
HIVEFRAME_H3_DEVICE_MAP=auto
HIVEFRAME_H3_TRUST_REMOTE_CODE=false
HIVEFRAME_H3_MODEL_ROOT
```

Model source, revision, model-root path, URL, token, and user path values are
never emitted to public config, SQLite, receipts, logs, Git, or PR text. Only
`configured`, `not_configured`, `valid`, or `invalid` status is exposed for
those values. A model root or resolved model source inside the repository is
invalid.

The separately created H3 environment remains evidence only: Python 3.12.3,
pip 26.2.1, diffusers 0.39.0, transformers 5.14.1, accelerate 1.14.0, torch
2.13.0+cu130, CUDA build 13.0, and previously observed CUDA availability true.
No package, environment, requirement, or lock file was changed here. These
versions are not asserted as compatible with an unpublished H3 artifact.

## Output normalization boundary

The provisional normalizer recognizes `frames`, `videos`, `video`, `images`,
direct frame lists, and local video paths. It classifies them as
`provisional_video_frames`, `provisional_video_output`,
`provisional_image_output`, `unsupported_output_contract`, or
`output_missing`. A single image is not a video-generation success. These
names are compatibility placeholders to be replaced only after official local
execution code defines the real output object.

## Focused verification

Command:

```bash
PYTHONPATH=python python3 -m unittest python/tests/test_product_vertical_slice.py
```

The first changed-code checkpoint passed 13 tests in 1.205 seconds. A contract
audit then corrected field/state/classification names, the factory signature,
offline cache resolution, and unload behavior; that changed-code checkpoint
passed 13 tests in 1.612 seconds. A final focused run after exact error and
output-candidate semantics changed passed 13 tests in 1.574 seconds. A final
state-preservation fix prevented source inspection from overwriting
`model_ready`/generation state; its changed-code checkpoint passed 13 tests in
1.458 seconds. The release-blocking review then made `local_files_only=false`
fail closed instead of leaving a future network fallback; that final changed-
code checkpoint passed 13 tests in 1.447 seconds. These were bounded changed-
code checkpoints, not repeated verification against unchanged code.

The focused tests cover request/schema parsing, empty text and incompatible
roles, ratio rules, missing-source state, local-files-only zero-network
behavior, injected factory success/failure, provisional output handling, UI
wait state, one Mock end-to-end flow per changed-code checkpoint, sanitized
receipts/database, asset IDs, traversal defense, and repository-external
storage. `git diff --check` and separate secret/binary/path scans complete the
release-blocking surface before publication.

The Mock end-to-end test therefore ran once at each of five materially changed
product-code checkpoints. It was not rerun after documentation-only changes.

Full Python, Rust, M0, M1-A/A2/B0, model, CUDA, GPU, VRAM, and benchmark suites
were intentionally not run because those unchanged surfaces are outside this
bounded correction.

## Claim boundary and operation count

Actual H3 model downloads: 0. Automatic downloads: 0. `snapshot_download`
calls: 0. Actual `from_pretrained` calls: 0. Model loads: 0. GPU generations:
0. CUDA runs: 0. API calls: 0. API keys used: 0. Paid calls: 0. External
personal-data transfers: 0. Selective-compute runs: 0. M1-B1/B2 runs: 0.

No fake model binary or fake MP4 was created. The only generated product output
in focused tests was the pre-existing, explicit Mock JSON contract stored under
temporary external artifact roots. No model/media/tool binary is tracked.

## Known limitations and next approved input

- No official MiniMax H3 local checkpoint or immutable revision is known here.
- The provisional `DiffusionPipeline` call site is centralized but unexecuted;
  its exact class and arguments may change after official code is published.
- No real MP4, audio, quality, latency, memory, or product result exists.
- Policy UI copy remains structural placeholder text, not legal advice.
- SQLite remains a single-user local product store.

P1-L requires all of the following before any download or load:

1. `HIVEFRAME_H3_MODEL_SOURCE`;
2. `HIVEFRAME_H3_MODEL_REVISION`;
3. the official model card and execution documentation;
4. explicit download approval after size, location, and cache reporting;
5. required artifact size and a selected low-memory profile, if supported.

The next bounded action is one approved official artifact download, load, and
local generation—not an API prerequisite and not automatic. Until those inputs
exist, the correct decision is `P0_LOCAL_READY_WAITING_FOR_ARTIFACT`.
