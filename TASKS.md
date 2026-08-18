# HIVEFRAME Tasks

Status date: 2026-08-18

## Status legend

| Status | Meaning |
|---|---|
| `done` | verified evidence exists |
| `in_progress` | implementation exists but the task is not fully closed |
| `planned` | not started |
| `blocked` | external approval or state is required |
| `stopped` | explicitly discontinued without erasing prior evidence |
| `unsupported` | current environment/backend lacks the capability |

## Product launch track — highest priority

The detailed Product-First Constitution is maintained only in
[`AGENTS.md`](AGENTS.md). Research evidence remains preserved, but research
expansion does not block the launch track.

| Track | Status | Evidence or blocker |
|---|---|---|
| P1-F - Local H3 two-minute-range preview | `stopped` | 608x352/7-step Sage reached 176.49 seconds but reduced quality settings; same-content 864x480/20-step Sage preserved the Standard profile and decoded fully but took 521.79 seconds, missing the 180-second target; no quality-preserving two-minute claim; Standard remains default |
| A0 — SageAttention stackable component admission | `pending_review` | Issue #80 completed / PR #81 merged; `AVAILABLE_OPTIONAL`, product default false, human visual review pending |
| A1 — Compound Eye regional active-query attention | `stopped` | Issue #82 / Draft PR #83; CONTROL valid and comparable, but Rust boundary p95 and block admission failed; SELECTIVE 0; `FALLBACK_ONLY` |
| P0 — Local H3 vertical slice | `done` | [Issue #53](https://github.com/ksse29077-byte/HIVEFRAME/issues/53) completed; PR #54 merged; `P0_LOCAL_H3_COMFYUI_READY` |
| F0-SAGE — External SageAttention paired probe | `verified_once` | Issue #55; 1.207148× is below 1.3×; `F0_SAGE_NO_GAIN`; Draft review pending |
| P1-A - Release Alpha shell and one-click Local H3 launcher | `done` | Explicit T2V/I2V, fixed Standard Quality, Local H3 readiness, product status/error/result UX, dev-only Mock, and bounded Windows launcher verified by 52 focused tests plus desktop/mobile browser checks; Generation 0 |
| P1-A1 - Real Alpha end-to-end smoke | `blocked` | Actual launcher and Standard I2V submit verified once, but an unattributed T2V already occupied the fresh local runtime; the I2V prompt was removed before running, output is absent, retry is 0, and a clean rerun requires separate Generation approval; `P1_A1_REAL_ALPHA_E2E_FAILED` |
| P2 — Real local H3 product flow | `planned` | replace provisional pipeline/output details only after official artifact code exists |
| P3 — Selective runtime integration | `planned` | requires backend-admitted partial-compute evidence and complete accepted-result costs |
| P4 — Internal alpha/commercial preparation | `planned` | operational, rights, retention/deletion, terms, packaging, and release safeguards |
| M1-B1/B2 — Engine Beta Track | `planned` | separately approved, one backend/selector-cache maximum; integrate benefit or use `FALLBACK_ONLY`/`DROP` |

## R0 — Compound-eye architecture RFC

| Task | Status | Evidence or blocker |
|---|---|---|
| Verify repository visibility | `done` | GitHub reports `PUBLIC` |
| Preserve pre-rebase state | `published` | annotated tag `pre-compound-eye-v1` → `2bc35ff...` |
| Create RFC branch | `published` | `agent/compound-eye-architecture-v1` |
| Preserve patch-centric architecture | `done` | `docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md` |
| Add hypothesis, architecture, protocol, gates | `done` | four RFC documents |
| Add four JSON Schema drafts | `done` | `schemas/*eye*`, shared state, compute plan |
| Add model-free reference packages | `done` | `hive_eyes`, `hive_fusion`, `hive_visual_state`, `hive_probes` |
| Verify deterministic simulation | `done` | 59 Python tests at `041311b...` |
| Verify Rust workspace | `done` | `cargo check --workspace --locked` |
| Add operating worklog documents | `done` | operating documents; 59 Python tests and Rust check passed |
| Reconcile official Compound I/O roadmap | `verified` | RFC branch; 59 Python tests, Cargo, schemas, and diff check passed |
| Push RFC branch | `published` | exact local Git history verified remotely |
| Push preservation tag | `published` | annotated tag object and target verified remotely |
| Create RFC Issue | `published` | [Issue #32](https://github.com/ksse29077-byte/HIVEFRAME/issues/32) |
| Create Draft PR | `published` | [Draft PR #33](https://github.com/ksse29077-byte/HIVEFRAME/pull/33) |
| Confirm CI | `planned` | review checks on Draft PR #33 |

## M0 — Single-Eye Cost Truth

Overall milestone status: `in_progress`. Completed component rows below do not
close M0; the eligible canonical same-condition baseline and input-side cost
scopes remain outstanding.

| Task | Status |
|---|---|
| Pinned Wan code/checkpoint/license | `done` |
| RTX 3060 WSL CUDA/BF16/FlashAttention verification | `done` |
| Smoke and regression Smoke | `done` |
| Cold/warm and same-seed reproducibility | `done` |
| Receipt 0.2.0 measurement correction | `done` |
| 49-frame memory admission | `done` |
| Canonical same-condition official baseline | `planned` |
| Input-side cost extensions | `planned` |

## M1-P0 — Analytical Topology Pre-Gate

Overall pre-gate status: `done`; final bounded decision
`RUST_CONTROL_PLANE_ADMITTED`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Search and preserve existing Analytical WIP | `verified` | no implementation found; new branch starts at post-PR36 main |
| Cost equations, synthetic cases, unavailable metrics, and pruning rules | `verified` | 9 analytical combinations |
| Use merged Rust I/O measurements | `verified` | local control-plane calibration only; Amdahl end-to-end remains unavailable |
| Minimal model-free probe | `verified` | 4 pruned, 5 measured at 5 warm-ups / 20 repetitions |
| M1-P0 decision | `verified` | `REFINE_COST_MODEL`; prediction error exceeded 35% twice |
| Publish Analytical branch and Draft PR | `published` | [Issue #37](https://github.com/ksse29077-byte/HIVEFRAME/issues/37), [Draft PR #38](https://github.com/ksse29077-byte/HIVEFRAME/pull/38) |

M1-P0 does not start or close M1 and does not close M0. Keep the same five
measured combinations and correct the cost model before another decision.

## M1-P0-R1 — Same-run Mono Cost Normalization

Overall refinement status: `verified`; decision `REFINE_COST_MODEL`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve v1 evidence and 35% threshold | `verified` | seven immutable v1 SHA-256 checks pass |
| Predeclare paired cost model and deterministic order | `verified` | config, design, runner, and 19 R1 tests |
| Keep the same five measured combinations | `verified` | 4 combinations remain analytically pruned; no corpus growth |
| Run 5 warm-up and 20 measured blocks | `verified` | 100 final measured samples in one process |
| Validate Case B paired deltas | `verified` | T1 error 61.83%; T2 error 56.60%; ranking matches |
| Preserve safety and deterministic semantics | `verified` | recall 1.0, false-stable 0.0, hashes match v1 |
| Publish and merge R1 | `published` | Issue #40 closed; [PR #41](https://github.com/ksse29077-byte/HIVEFRAME/pull/41) merged at `e5bbaa7...` |

Same-run pairing did not bring the Rust-derived incremental coefficients
within the unchanged 35% rule. Do not expand to the rights-cleared M1 Cost
Surface from this result. The next calibration change requires a separately
predeclared explanation of the missing Python topology-variable stages.

## M1-P0-R2 — Python Attribution and Rust Compound Runtime

Overall refinement status: `verified`; decision `REFINE_RUST_BOUNDARY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve v1 and R1 evidence | `verified` | sixteen merged Git-blob SHA-256 checks pass |
| Predeclare Python stage attribution | `verified` | inclusive/exclusive taxonomy, signed pairing, overhead calibration, fixed thresholds |
| Keep exact Case B T0/T1/T2 | `verified` | 20 paired blocks; no topology or corpus growth |
| Attribute Python Compound overhead | `verified` | T1 100.0606%, T2 99.8828%; every block equation holds |
| Add one coarse Rust batch boundary | `verified` | one packed input handoff, no per-Eye round trips |
| Verify semantic and copy safety | `verified` | R1/Python/Rust hashes equal; deterministic; exactly 2.0x input boundary copies |
| Decide R2 | `verified` | Rust T1/T2 core lower, but in-process FFI remains `null/not_collected` |
| Sanitize and normalize public R2 evidence | `verified` | Logical digest unchanged; private execution paths removed and semantic payloads stored once per candidate/hash |
| Publish R2 branch and Draft PR | `published` | [Issue #42](https://github.com/ksse29077-byte/HIVEFRAME/issues/42); [Draft PR #43](https://github.com/ksse29077-byte/HIVEFRAME/pull/43) |

Do not interpret the decision as `MONO_FIRST` or as rejection of Compound
Perception First. The next bounded runtime work is an in-process shared-buffer
boundary using the same Case B and semantic/copy contracts. H3 Issue #39
remains separate and no backend/model execution was performed.

## M1-P0-R3 — In-process Shared-buffer Boundary

Overall refinement status: `verified`; decision `RUST_CONTROL_PLANE_ADMITTED`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve v1, R1, and R2 evidence | `verified` | immutable R2 Git objects are checked before plan or execution |
| Pin Python/Rust boundary | `verified` | Python 3.12, PyO3 0.29.0, `abi3-py312`, Rust MSRV 1.83 |
| Fix Case B T0/T1/T2 scope | `verified` | 5 warm-ups and 30 same-process paired blocks declared |
| Borrow one shared input buffer | `implemented` | read-only C-contiguous uint8 buffer; one Rust call per candidate; zero per-Eye calls |
| Predeclare thresholds and decisions | `verified` | config, contract receipt, tests, and Issue #44 |
| Execute R3 measurement | `verified` | 30 paired blocks per candidate; T1/T2 p50 lower by 31.21%/35.98% |
| Verify shared-buffer safety | `verified` | parity 100%; input copies, subprocesses, temp files, and per-Eye calls are zero |
| Decide R3 | `verified` | `RUST_CONTROL_PLANE_ADMITTED`; 1,348 independent audit assertions pass |
| Publish and merge R3 | `published` | Issue #44 closed; [PR #45](https://github.com/ksse29077-byte/HIVEFRAME/pull/45) merged at `156d955...` |

R3 is a model-free control-plane experiment. It cannot close M0 or M1 and
cannot claim real-video, model, quality, or product speedup. Compound
observation remains a candidate evidence mechanism rather than the product
direction; Mono remains the comparator and safety fallback. M1-P0 is complete;
no R4 is authorized. The next chronological work was M1-A rights-cleared
real-video corpus and oracle admission.

## Backend product target policy

| Task | Status | Evidence or blocker |
|---|---|---|
| Designate MiniMax H3 as primary product target | `verified` | policy only; no runtime or speedup claim |
| Review current official H3 API documentation | `verified` | V2 contract names `MiniMax-H3`; runtime admission remains pending |
| Optional H3 API adapter admission | `planned` | [Issue #39](https://github.com/ksse29077-byte/HIVEFRAME/issues/39) remains separate; it is not required for P0-LR or P1-L |
| Admit future H3 open weights | `blocked` | official repository, checkpoint, source, license, digest, and runtime not jointly verified |
| Preserve Wan M0 comparator | `done` | frozen code, pins, receipts, fingerprints, and reports; no new feature development |
| Remove LTX from active scope | `done` | historical code and Git history retained; no cleanup in this change |
| Create backend capability matrix | `implemented` | protocol-only matrix exists with no admitted selector or skip authority; runtime evidence remains Issue #39 work |

## M1-A — Rights-cleared Real-video Corpus and Oracle Protocol

Overall status: `in_progress`. The initial metadata-only admission decision
`CORPUS_ACQUISITION_REQUIRED` and the later M1-A2 decision
`RIGHTS_REVIEW_BLOCKED` remain chronological evidence. The current M1-A2 Gate
is `ORACLE_PROTOCOL_REVISE`: visible-change review is not compute-relevance or
safe-skip truth. No topology or backend performance run is authorized.

| Task | Status | Evidence |
|---|---|---|
| Preserve M0 and M1-P0 evidence | `done` | PR #45 merged; R3 remains `RUST_CONTROL_PLANE_ADMITTED` |
| Track M1-A admission work | `published` | Issue #46 closed; [PR #47](https://github.com/ksse29077-byte/HIVEFRAME/pull/47) merged at `b50051b...` |
| Predeclare corpus, rights, derivative, oracle contracts | `implemented` | schemas, configs, validators, and negative tests |
| Fix T0-T7 candidate contract and metric/Gate semantics | `implemented` | metadata only; no performance result |
| Search task-scoped approved assets | `done` | repository metadata and supplied task artifacts only; zero actual video assets found |
| Admit 12 distinct actual clips | `blocked` | no eligible actual clip is currently recorded in repository metadata |
| Produce oracle-reviewed complete coverage | `blocked` | depends on eligible clip acquisition and review |
| Emit M1-A admission reports | `verified` | 0 eligible/pending/rejected; all 12 classes missing; `CORPUS_ACQUISITION_REQUIRED` |
| Run topology cost/safety measurement | `stopped` | original admission path superseded; corrected M1-B0/M1-B1 work requires separate approval |

The initial empty-corpus result remains immutable evidence. It is not replaced
by M1-A2.

## M1-A2 — Deterministic Derivatives and Human Review Gate

Bounded M1-A2 implementation status: `done`. Validation status: `done`.
Publication status: `merged`. Final decision: `ORACLE_PROTOCOL_REVISE`.
`RIGHTS_REVIEW_BLOCKED` remains preserved as the previous chronological Gate.
Phase-one human rights, scene-content, and privacy review is complete for all
twelve clips. The exported Guided Oracle is auxiliary observed-change evidence
only; it is not compute-relevance truth, safe-skip truth, or backend execution
evidence. Blind re-review, adjudication, and verified-Oracle promotion under
the superseded protocol are stopped.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track M1-A2 publication | `published` | [Issue #48](https://github.com/ksse29077-byte/HIVEFRAME/issues/48) completed; [PR #49](https://github.com/ksse29077-byte/HIVEFRAME/pull/49) merged at `e00145a...`; source branch preserved |
| Verify designated C01 consent evidence | `verified` | required structure present; SHA-256 `f1187f...63d2`; legacy similarly named file excluded |
| Inventory approved C01-C12 originals | `verified` | 12 distinct immutable H.264/MP4-family originals; no duplicate digest |
| Admit local FFmpeg/FFprobe 7.1.1 tools | `verified` | exact archive/binary/license hashes recorded; no PATH/admin change |
| Create deterministic analysis derivatives | `verified` | 12 FFV1 derivatives; independent encode hashes match; full decode passes |
| Preserve superseded manual-entry package | `done` | v1 retained as usability evidence; reviewer stopped before adding rows or exporting results |
| Prepare guided Oracle review package | `verified` | model-free adjacent-frame proposals: 110 intervals, 106 dirty boxes, 17 uncertain boxes, eight C07 cut candidates; all remain `pending_review` and are not truth |
| Complete human rights/privacy/scene review | `done` | exact C01-C12 checklist validated; 12/12 rows have all three phase-one fields `yes`; checklist SHA-256 `1ca230...f216` |
| Preserve Guided Oracle export | `done` | JSON/CSV names, hashes, structure, and 12-clip coverage recorded without promoting coordinates or decisions to compute truth |
| Classify observed-change evidence | `verified` | auxiliary/human-reviewed-or-partially-reviewed; not compute relevance, safe skip, or backend-claim eligible |
| Complete compute-relevance Oracle | `blocked` | 0 verified; replacement protocol requires separate approval |
| Complete blind review and adjudication | `stopped` | superseded pixel-change Oracle path will not be promoted |
| Admit backend selective compute | `blocked` | eligible 0; BackendCapabilityMatrix contains no admitted selector |
| Run topology/backend cost measurement | `planned` | separate approval after M1-B0/M1-B1 protocol gates |

The current task stops at protocol correction. Do not run model-free
topologies, train a planner, connect a backend, or modify Wan hooks. The next
work requires a separate approval under the corrected selective-recompute
roadmap.

Published and verified here mean that the M1-A2 protocol correction, evidence
preservation, and validation record are on `main`. They do not mean
`M1_CORPUS_AND_ORACLE_READY`, safe-skip truth, backend capability admission,
actual selective compute, GPU-work reduction, speedup, or VRAM reduction.

## M1-B0 — Model-free Locality Opportunity

Overall implementation and measurement status: `verified`. Publication
status: `published`. Final bounded decision:
`M1_B0_LOCALITY_SURFACE_MEASURED`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Create separate review surface | `published` | [Issue #51](https://github.com/ksse29077-byte/HIVEFRAME/issues/51) completed; branch preserved |
| Verify C01-C12 FFV1 inputs | `verified` | 12/12 SHA, size, codec, shape, FPS, and frame counts pass |
| Measure fixed pixel/tile/halo/temporal surface | `verified` | all predeclared gray8/RGB24 configurations retained |
| Validate NumPy/Rust parity | `verified` | 24/24 clip-format pairs, zero mismatches |
| Separate detector costs | `verified` | decode-only, resident-warm, and streaming scopes retained separately |
| Run CPU worker sweep | `verified` | required 1/2/3/4/6 plus labeled 8/12 diagnostics |
| Admit backend selective compute | `blocked` | M1-B1 is not started; selector and compute relevance remain unsupported |
| Publish M1-B0 | `published` | [PR #52](https://github.com/ksse29077-byte/HIVEFRAME/pull/52) merged at `4ddb6a5...` |

Guided Oracle movement evidence was not used as safe-skip truth. Model, CUDA,
GPU, backend, VRAM, selective-compute, and product-speedup result counts remain
zero. The decision records a measured opportunity surface only and does not
start M1-B1.

## HIVEFRAME 2.0 RFC

Overall status: `planned`; protocol-only. It requires separate user approval
and a separate Issue, branch, and Draft PR. It cannot bypass M1-B0 or backend
evidence and is not started by the M1-A2 publication.

## P0 — Local MiniMax H3 product vertical slice

Overall implementation status: `verified_once`. Publication status: `published`.
Bounded decision: `P0_LOCAL_H3_COMFYUI_READY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve P0-LR wait-state contract | `done` | existing Mock and future local-files-only adapter remain compatible |
| Inspect supplied H3 assets and workflow | `verified_once` | four model components and one T2V workflow recognized without copying or modification |
| Connect loopback ComfyUI backend | `implemented` | explicit backend key, bounded polling, cancellation, result and receipt collection |
| Connect UI and product Job states | `verified_once` | Mock/real provenance, queued/running/succeeded, video display/download, feedback ledger |
| Run one actual Local H3 smoke | `verified_once` | one submission, 124 decoded frames, OOM 0, retry 0 |
| Preserve H3 Knowledge Flywheel | `implemented` | workflow, runtime, failure, capability, and decision files; no automatic promotion |
| Publish P0 through PR #54 | `published` | Issue #53 completed; PR #54 merged at `d716a22...` |
| Complete P1-A release shell and one-click launcher | `done` | Repository-owned `.cmd`/`.ps1`, owned-runtime lifecycle, Local H3 preflight, browser-after-ready ordering, and bounded failure paths verified without Generation |

This result proves only the first Local H3 product path. It does not establish
quality, speed, cost, cache, selective compute, or production-default settings.

## F0-SAGE — External SageAttention KJ paired validation

Overall status: `verified_once`; publication status: `published`; decision:
`F0_SAGE_NO_GAIN`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated F0 review | `published` | [Issue #55](https://github.com/ksse29077-byte/HIVEFRAME/issues/55) completed; [PR #56](https://github.com/ksse29077-byte/HIVEFRAME/pull/56) merged at `2faa8a7...`; branch preserved |
| Pin compatible external components | `verified_once` | KJNodes `6edfa765...`, SageAttention 2.2.0 post6, Triton Windows 3.7.1 post27 |
| Preserve Standard workflow | `verified_once` | Sage node count 0; new Standard output hash equals P0 |
| Patch Sage API copy | `verified_once` | one `PathchSageAttentionKJ` node in `auto`; two MODEL consumers rewired |
| Execute fixed paired comparison | `verified_once` | Standard 586.972500 s; Sage 486.247216 s; 1.207148×; OOM/retry 0 |
| Verify output integrity | `verified_once` | both H.264, 864x480, 124/124 frames, 24 FPS, native audio, black/corrupt 0 |
| Promote Fast mode | `rejected` | below fixed 1.3× candidate threshold; visual review remains required |

This is external F0 acceleration, not HIVEFRAME Core acceleration. Standard
full compute remains the fallback. No other mode, accelerator, Rust runtime,
selective compute, or model training is authorized automatically.

## A0 — H3 SageAttention stackable component admission

Overall status: `pending_review`; publication status: `published`. Automatic
decision: `A0_SAGE_STACKABLE_COMPONENT_READY_FOR_VISUAL_REVIEW`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Preserve immutable F0 decision | `verified` | `F0_SAGE_NO_GAIN` and the former standalone 1.3x contract remain unchanged |
| Predeclare stackable component Gate | `verified` | fixed provenance, integrity, nMAE, motion, gradient, temporal-difference, review, fallback, and claim boundaries |
| Reuse valid F0 pair | `verified_once` | output/workflow/profile hashes match; new Generation, retry, CUDA Generation, and benchmark counts are zero |
| Run offline catastrophic-regression screen | `verified_once` | nMAE 0.018065; motion 0.986199; gradient 1.029342; temporal difference 1.033998; all fixed checks pass |
| Preserve quality claim boundary | `verified` | SSIM is diagnostic only; quality-at-least-Standard and visual equivalence remain unproven |
| Prepare private visual review | `pending_review` | fixed frames plus three highest-motion transitions; human decision not inferred |
| Admit product default | `not_admitted` | `KEEP_AS_OPTIONAL` / `AVAILABLE_OPTIONAL`; Standard Full Compute fallback preserved; final 2.0x not reached |
| Publish A0 evidence | `published` | [Issue #80](https://github.com/ksse29077-byte/HIVEFRAME/issues/80) completed; [PR #81](https://github.com/ksse29077-byte/HIVEFRAME/pull/81) merged |

A0 treats the historical 1.207148x result as one optional external component,
not as a standalone product accelerator or a HIVEFRAME invention. Component
ratios may not be multiplied to claim cumulative performance. Human review is
required before any further quality disposition. A1 later ran independently
with Sage disabled and did not modify A0. See
the detailed [A0 worklog](docs/worklogs/2026-08-09-a0-h3-sage-stackable-attention.md).

## A1 — H3 Compound Eye regional active-query attention

Overall status: `stopped`; publication status: `draft_pr`. Bounded decision:
`A1_CONTROL_PLANE_OVERHEAD_TOO_HIGH`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated A1 work | `draft_pr` | [Issue #82](https://github.com/ksse29077-byte/HIVEFRAME/issues/82); branch `accel/a1-h3-compound-eye-active-query-attention`; Draft PR [#83](https://github.com/ksse29077-byte/HIVEFRAME/pull/83) |
| Freeze A1 mechanism and Gates | `verified` | commit `8b18126...`; full QKV projection, subset Q after RoPE, global/full K/V, one-patch halo, anchors, cooldown, Full FF, max two Generations, retry zero |
| Prove structural active-Q path | `verified` | full-Q wrapper and subset-Q row equivalence, smaller Q with unchanged K/V, non-video preservation, fixed region mapping, PyO3 A1 ABI roundtrip |
| Execute CONTROL shadow | `verified_once` | one Generation, retry zero; live C2 + 18 A1 Rust plans; 20 forwards/1,000 Full Attention blocks; H.264 864x480, 124/124 frames, audio 1 |
| Meet CONTROL comparability | `verified_once` | sampler 489.823359 s, +0.199661% versus immutable C4-S0 488.847320 s; within +/-5% |
| Meet Rust overhead Gate | `stopped` | A1 boundary p95 202.5 us exceeded fixed 100 us; first-call sample retained |
| Admit block opportunity | `stopped` | 12 observations/block, but zero blocks passed mean <=0.020; lowest mean 0.033861; planned Q reduction 0% |
| Execute SELECTIVE and paired quality | `stopped` | prohibited by CONTROL Gate; SELECTIVE 0, paired quality/runtime not collected, visual equivalence not proven |

The exact zero-update mechanism is `FALLBACK_ONLY`; this is not an attention-
surface rejection. Structural query-subset/global-KV evidence, live C2/Rust
control evidence, valid Full Compute output, and sampler comparability are
preserved. The primary next mechanism candidate is `GPU_RESIDENT_PLAN_MASK`
under separate approval. A0 remains optional and uncombined; product speedup,
quality promotion, product promotion, and automatic A2 starts remain zero.
See the detailed [A1 worklog](docs/worklogs/2026-08-10-a1-h3-compound-eye-active-query-attention.md).

## A2 — GPU-resident regional query prototype attention

Overall status: `stopped`; publication status: `draft_pr`. Bounded decision:
`A2_QUERY_PROTOTYPE_OPPORTUNITY_TOO_LOW`; disposition: `FALLBACK_ONLY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated A2 work | `draft_pr` | [Issue #84](https://github.com/ksse29077-byte/HIVEFRAME/issues/84); branch `accel/a2-h3-gpu-regional-query-prototype`; Draft PR [#85](https://github.com/ksse29077-byte/HIVEFRAME/pull/85) |
| Freeze exact-query prototype mechanism | `verified` | commit `3e2847a...`; exact post-RoPE Q, fixed 2x2 stride, same-time/region bilinear reconstruction, global/full K/V, full projections, max two Generations, retry zero |
| Prove model-free mapping and execution contract | `verified` | 16 focused tests; 16 deterministic semantic masks, stable-only omission, reconstruction, full-row parity, full K/V, GPU-plan reuse, installed source, PyO3 ABI roundtrip |
| Reuse metadata-only Rust region plan | `verified_once` | ABI unchanged; 18 calls, boundary p95 17 us, tensor bytes and per-block/per-token calls zero |
| Execute Full Attention CONTROL diagnostic | `verified_once` | one Generation, retry zero; 20 forwards/1,000 blocks; 600 finite counterfactual block-region observations; valid H.264 124/124 output |
| Meet CONTROL comparability | `verified_once` | sampler 493.593208 s, +0.970832% versus immutable C4-S0 488.847320 s; within +5% |
| Admit prototype blocks and query opportunity | `stopped` | zero blocks passed fixed fidelity Gate; best block mean L2 0.193671 > 0.120; planned Q reduction 0% |
| Meet combined callback Gate | `stopped` | inclusive Compound Eye callback p95 59.829032 ms exceeded fixed 3 ms; Rust child span was not double-counted |
| Execute SELECTIVE and paired quality | `stopped` | prohibited by CONTROL admission; SELECTIVE 0, actual Q reduction 0, paired quality/runtime not collected, visual equivalence not proven |

The exact A2 mechanism is fallback-only; it does not invalidate A1 structural
subset-Q/global-KV evidence or the global-attention cost surface. Standard Full
Compute remains the product path. `REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1`
is only a next candidate requiring separate approval. A0 integration, combined
speedup, quality/product promotion, and automatic A3 starts remain zero. See
the detailed [A2 worklog](docs/worklogs/2026-08-10-a2-h3-gpu-regional-query-prototype-attention.md).

## C0-H3 — Execution phase and Runtime Hook Map

Overall status: `verified_once`; publication status: `published`.
Bounded decision: `C0_H3_PHASE_MAP_READY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C0 work | `published` | [Issue #57](https://github.com/ksse29077-byte/HIVEFRAME/issues/57) completed; [PR #58](https://github.com/ksse29077-byte/HIVEFRAME/pull/58) merged as `3d6728d...`; branch preserved |
| Add model-free telemetry fixtures | `verified` | WebSocket lifecycle, progress semantics, phase union, resource context, sanitizer, collision, and fixed-profile tests |
| Execute one Standard instrumented run | `verified_once` | 864x480, 124/124 frames, 20 steps, audio, retry 0, Sage nodes 0 |
| Attribute execution phases | `verified_once` | sampler 486.604 s (81.196% runner); video VAE 63.162 s (10.539%); exact kernel time remains unavailable |
| Map runtime hooks | `verified_once` | observable, controllable, wrapper/custom-node/core-patch, not-found, and unsafe states recorded |
| Select first Rust handoff target | `contract_only` | sampler progress/callback metadata boundary; initial directive remains `FULL_COMPUTE` |
| Implement Rust acceleration | `superseded_by_c1` | metadata-only C1 bridge work is tracked separately below; selective acceleration remains not started |

C0 does not implement Rust, Compound Eye execution, selective compute, cache
reuse, a product Fast Mode, or training. The unchanged Standard H3 path is the
mandatory fallback. Raw events, media, logs, prompt, and private receipt remain
outside Git.

## C1 — Rust Sampler Step Policy Bridge

Overall status: `verified_once`; publication status: `published`. Bounded
decision: `C1_RUST_POLICY_BRIDGE_READY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C1 work | `published` | Issue #59 completed; [PR #60](https://github.com/ksse29077-byte/HIVEFRAME/pull/60) merged as `4635f47...`; branch preserved |
| Reuse existing Rust workspace and PyO3 bridge | `implemented` | `hive-retina-runtime` plus `hive-retina-python`, ABI v1, PyO3 0.29 `abi3-py312` |
| Define fixed metadata contracts | `verified` | 184-byte `StepObservation`, 76-byte `StepDirective`, fixed digests/enums, no tensors or private payloads |
| Enforce full-compute-only policy | `verified` | `FULL_COMPUTE` / `ESCALATE_FULL_COMPUTE`; every skip/reuse/partial counter fixed at zero; panic and malformed-response fail-open tests |
| Register repository runtime wrapper | `verified_once` | custom node visible in ComfyUI 0.30.2 without core or original-workflow changes |
| Execute approved Standard parity run | `failed` | one submission, retry 0; locked V3 class guard failed before callback 1; output and policy timing unavailable |
| Correct the observed wrapper defect | `model_free_verified` | guard moved to module-local state; one direct delegated callback and Rust call passed; second H3 generation 0 |
| Execute approved regression parity run | `verified_once` | one additional authorized submission, retry 0; 20 callbacks and 20 Rust calls, full-compute output decoded 124/124 |
| Pass C1 parity and overhead gates | `verified_once` | boundary p95 38.1 us, conservative cumulative policy span 2.592 ms, submit-to-terminal 556.433 s |

C1 does not implement or validate step/block/token/latent skipping, cache reuse,
partial compute, Compound Eye execution, Fast Mode, SageAttention, or training.
The failed 34.44-second first attempt remains diagnostic history. The single
approved regression validates metadata-only full-compute parity; it is not a
speedup claim or product-default promotion. See the detailed
[C1 worklog](docs/worklogs/2026-08-06-c1-rust-sampler-policy-bridge.md).

## C2 — Local H3 Compound Eye Shadow Policy

Overall status: `verified_once`; publication status: `draft_pr`. Latest bounded
decision: `C2_COMPOUND_EYE_SHADOW_READY`; the initial
`C2_SHADOW_SIGNAL_NOT_ADMITTED` and R1 `C2_SHADOW_REVISE_ONCE` results remain
immutable chronological evidence.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C2 work | `published` | [Issue #61](https://github.com/ksse29077-byte/HIVEFRAME/issues/61) completed; [PR #62](https://github.com/ksse29077-byte/HIVEFRAME/pull/62) merged as `e7bae90...`; branch preserved |
| Predeclare five-eye topology and thresholds | `verified` | `overlap_2x2`, x0-only 4x4x3 sketch, fixed scale 4096 and immutable ppm thresholds |
| Implement separate C2 Rust/PyO3 ABI | `verified` | 536-byte observation, 232-byte directive, one fixed-sketch call maximum, actual decisions limited to Full Compute/escalation |
| Pass focused model-free validation | `verified` | seven C2 Rust tests, workspace check, 20 C2+C1 Python tests, real ABI roundtrip, compile/fmt/diff checks |
| Execute approved Standard shadow run | `verified_once` | one submission, retry 0, video 124/124; all 20 callbacks fail open because x0 is not a `torch.Tensor` |
| Identify and fix one exact container path | `model_free_verified` | source-backed `x0.tensors[0]`; fixed video/audio container contract; 14/14 focused tests |
| Execute the one approved C2-R1 regression | `verified_once` | one submission, retry 0; adapter 20/20, Rust 20/20, Full Compute 20/20, video 124/124 |
| Validate stable candidates counterfactually | `verified_once` | 76 eligible eye-steps; stable/active/uncertain 25/4/47; validated/contradicted/unvalidated 25/0/0 |
| Pass C2-R1 admission and overhead gates | `revise_once` | actual signal dtype was `torch.float32` while the committed gate required BF16; 48-scalar blocking transfer made total-shadow p95 7.147 s and cumulative span 135.699 s |
| Fix strict FP32 pre-Rust admission and async sketch path | `verified` | exact float32 CUDA contract, three pinned slots, current-stream non-blocking 192-byte copies, callback synchronization 0 |
| Execute the one approved C2-R2 regression | `verified_once` | one submission, retry 0; callback/admission/enqueue/consume/Rust/Full Compute all 20; event ready 20, not-ready/overflow/timeout 0 |
| Validate lagged stable candidates | `verified_once` | 72 eligible eye-steps; stable/active/uncertain 23/4/45; validated/contradicted/unvalidated 23/0/0; two-step horizon |
| Pass C2-R2 admission and overhead gates | `verified_once` | callback CPU p95 1.5082 ms and cumulative 73.0815 ms; CUDA sketch p95 0.217248 ms; Rust boundary p95 37.6 us |
| Select C3 execution hook | `candidate_admitted` | `h3.transformer_block_wrapper` is the one separately approved C3 candidate; it is not implemented or product-promoted |

C2-R2 preserved Standard Full Compute and produced a valid H.264 video while
removing the R1 contract mismatch and blocking callback transfer. This admits
one C3 *candidate contract*, not selective execution: actual skip, cache reuse,
partial compute, raw-tensor FFI, speedup, and product promotion remain zero.
C3 implementation requires separate approval. See the detailed
[C2 worklog](docs/worklogs/2026-08-06-c2-h3-compound-eye-shadow.md).

## C3 — H3 Transformer Block Selective Compute pre-gate

Overall status: `stopped`; decision `C3_POLICY_OPPORTUNITY_TOO_LOW`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C3 work | `in_progress` | [Issue #63](https://github.com/ksse29077-byte/HIVEFRAME/issues/63); branch `accel/c3-h3-transformer-block-selective-compute`; Draft review only |
| Inspect installed H3 block source | `verified` | 50 ordered `DiTBlock` entries; repository-owned `patches_replace` identity wrapper is structurally admitted without installed-source changes |
| Replay immutable C2-R2 signal | `verified` | G4/G3: 0%; G2: selected steps 5, 8, 13, 16 and 148/1000 theoretical bypass calls |
| Pass predeclared opportunity floor | `stopped` | G2 reaches 14.8%, below the fixed 18% minimum |
| Implement C3 Rust/PyO3/runtime path | `stopped` | prohibited after opportunity rejection; C1/C2 ABIs remain unchanged |
| Execute CONTROL and SELECTIVE pair | `stopped` | generation count 0; no runtime mapping, speed, quality, or product claim |

The H3 source admits the proposed identity-bypass hook, but source admission
does not override the opportunity Gate. See the detailed
[C3 worklog](docs/worklogs/2026-08-07-c3-h3-transformer-block-selective-compute.md).

## C3-R1 — Frozen Replay Selective Block Experiment

Overall status: `verified_once`; publication status: `draft_pr`. Bounded
decision: `C3_R1_LIVE_VETO_OPPORTUNITY_TOO_LOW`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C3-R1 work | `draft_pr` | [Issue #65](https://github.com/ksse29077-byte/HIVEFRAME/issues/65); branch `accel/c3-r1-frozen-replay-block-selective`; Draft PR [#66](https://github.com/ksse29077-byte/HIVEFRAME/pull/66) |
| Freeze schedule and implementation before runtime | `verified` | steps 5/6/8/13/16/17, anchors 0/1/18/19, blocks 12..48, separate 208/80-byte C3 ABI; commit `a1a369a...` |
| Execute matched CONTROL | `verified_once` | one submission, retry 0; 1,000 original and 0 bypass calls; 124/124 H.264 frames |
| Execute matched SELECTIVE | `verified_once` | one submission, retry 0; 852 original and 148 bypass calls; exact call accounting; 124/124 H.264 frames |
| Meet actual opportunity floor | `stopped` | live safety vetoed steps 8 and 16; actual 148/1,000 = 14.8%, below fixed 18% |
| Meet performance targets | `stopped` | sampler 1.153991x below 1.20x; submit-to-terminal 1.125478x below 1.15x |
| Meet quality Gate | `stopped` | mean/p05 SSIM 0.805245/0.764500 and motion ratio 1.834976; visual equivalence not proven |

C3-R1 verifies once that the repository-owned identity wrapper can omit real
H3 `DiTBlock` forwards and fail open on a live veto. It does not admit a
dynamic product policy, cross-prompt quality, speedup, cache reuse, partial
repair, or product promotion. The existing C3 rejected evidence is unchanged.
See the detailed [C3-R1 worklog](docs/worklogs/2026-08-07-c3-r1-frozen-block-bypass.md).

## C3-R2 — Quality-Preserving Segment Residual Replay

Overall status: `stopped`; publication status: `draft_pr`. Bounded decision:
`C3_R2_RESIDUAL_SIMILARITY_TOO_LOW`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C3-R2 work | `draft_pr` | [Issue #67](https://github.com/ksse29077-byte/HIVEFRAME/issues/67); branch `accel/c3-r2-h3-segment-residual-reuse`; Draft PR [#68](https://github.com/ksse29077-byte/HIVEFRAME/pull/68) |
| Freeze residual-replay contract before runtime | `verified` | blocks 12..48, age-one Full Compute cache, fixed six candidates, 0.99 cosine/0.20 L2 thresholds, and quality-first Gate; commit `0ec5945...` |
| Validate model-replaceable Core and H3 adapter | `verified` | generic metadata-only Rust contract; H3 owns packed tensor, residual cache, block mapping, and GPU lifecycle |
| Execute CONTROL residual capture | `verified_once` | one fresh-process submission, retry 0; 1,000 original calls, 20 residual captures, 124/124 H.264 frames |
| Admit SELECTIVE schedule | `stopped` | zero of six candidates passed both frozen similarity thresholds; minimum was two |
| Execute SELECTIVE residual replay | `stopped` | prohibited by the predeclared admission Gate; generation count 0 |
| Claim quality, compute reduction, or speedup | `stopped` | paired output does not exist; metrics are not collected rather than recorded as zero |

CONTROL verified bounded one-residual ownership and fail-open behavior once,
but it did not establish a usable replay schedule. Actual replay, omitted block
calls, paired quality, runtime speedup, visual equivalence, and product
promotion remain unverified. C3-R1 evidence is unchanged. See the detailed
[C3-R2 worklog](docs/worklogs/2026-08-07-c3-r2-segment-residual-reuse.md).

## C3-R3 — Compact Residual Correction / Prediction

Overall status: `stopped`; publication status: `draft_pr`. Bounded decision:
`C3_R3_PREDICTOR_SIMILARITY_TOO_LOW`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C3-R3 work | `draft_pr` | [Issue #70](https://github.com/ksse29077-byte/HIVEFRAME/issues/70); branch `accel/c3-r3-h3-compact-residual-correction`; Draft PR [#71](https://github.com/ksse29077-byte/HIVEFRAME/pull/71) |
| Freeze compact predictor before runtime | `verified` | channel standard deviation, epsilon `1e-6`, gain clip `0.90..1.10`, 64 KiB metadata limit, unchanged C3-R2 thresholds; commit `b48022e...` |
| Validate Core/Adapter and memory boundary | `verified` | generic tensor-free Rust correction ABI; H3 owns channel layout, block 12..48 mapping and CUDA correction; one persistent residual, zero persistent predictions |
| Execute CONTROL correction shadow | `verified_once` | one fresh-process submission, retry 0; 1,000 original calls, 20 captures, 19 finite predictors, 124/124 H.264 frames |
| Admit SELECTIVE schedule | `stopped` | zero of six candidates passed fixed corrected similarity plus raw-non-regression Gates; minimum was two |
| Execute corrected replay | `stopped` | prohibited by the predeclared Gate; SELECTIVE and third Generation counts 0 |
| Claim quality, compute reduction, or speedup | `stopped` | no paired output exists; metrics remain uncollected and product promotion remains zero |

The compact metadata and bounded predictor path were verified once, but the
predictor did not clear the immutable quality-first admission threshold. Full
Compute remains the default and safe fallback. See the detailed
[C3-R3 worklog](docs/worklogs/2026-08-07-c3-r3-compact-residual-correction.md).

## C3-R4 — Two-Residual Directional Prediction

Overall status: `stopped`; publication status: `published`. Bounded decision:
`C3_R4_DIRECTIONAL_SIMILARITY_TOO_LOW`. Residual-predictor family disposition:
`RESIDUAL_PREDICTOR_FAMILY_FALLBACK_ONLY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C3-R4 work | `published` | [Issue #72](https://github.com/ksse29077-byte/HIVEFRAME/issues/72) completed; branch `accel/c3-r4-h3-two-residual-directional-prediction`; PR [#73](https://github.com/ksse29077-byte/HIVEFRAME/pull/73) merged as `e784166...` |
| Freeze directional predictor before runtime | `verified` | exact two-residual formula, eight non-zero alpha values, one global-alpha rule, unchanged C3-R2 thresholds, raw non-regression, memory Gate; commit `6ff0726...` |
| Validate metrics, Core/Adapter boundary, and ABI | `verified` | exact sufficient-stat equivalence; existing tensor-free C3-R3 Rust ABI reused; H3 tensor/block logic remains adapter-owned |
| Execute CONTROL directional shadow | `verified_once` | one submission, retry 0; 1,000 original calls, 20 actual residual captures, 48 finite candidate diagnostics, 124/124 H.264 frames |
| Admit SELECTIVE schedule | `stopped` | selected diagnostic alpha `-0.125`, but zero spaced calibrated targets; minimum was two |
| Execute directional replay | `stopped` | prohibited by the predeclared Gate; SELECTIVE and third Generation counts 0 |
| Claim quality, compute reduction, or speedup | `stopped` | no paired output exists; metrics remain uncollected and product promotion remains zero |

C3-R4 verified bounded two-residual diagnostics and fallback once, but no
directional candidate cleared the immutable Quality Gate. The bounded
residual-predictor family is now fallback-only; C3-R5 and automatic next-stage
research are prohibited. See the detailed
[C3-R4 worklog](docs/worklogs/2026-08-07-c3-r4-two-residual-directional-prediction.md).

## C4-S0 — H3 Sub-Block Cost & Coupling Surface

Overall status: `verified_once`; publication status: `published`. Bounded
decision: `C4_S0_SUBBLOCK_COST_SURFACE_MAPPED`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C4-S0 work | `published` | [Issue #74](https://github.com/ksse29077-byte/HIVEFRAME/issues/74) completed; branch `accel/c4-s0-h3-subblock-cost-coupling`; [PR #75](https://github.com/ksse29077-byte/HIVEFRAME/pull/75) merged as `f2d79ac...` |
| Freeze source map and instrumentation before runtime | `verified` | six source-order groups, coupling classes, deferred CUDA-event accounting, +/-5% comparison Gate, and ranking rules; commit `d1ffa3e...` |
| Execute fixed Full Compute profile | `verified_once` | one submission, retry 0; 20 model forwards, 1,000 block calls, all six groups observed 1,000 times; 124/124 H.264 frames with audio |
| Preserve unchanged execution | `verified_once` | skip/reuse/prediction/regional/token/attention omission all zero; mapping and wrapper failures zero; Full Compute fallback preserved |
| Pass instrumentation comparison | `verified_once` | sampler 488.847320 s versus 488.584958 s frozen reference; +0.053698%, inside +/-5% |
| Map dominant costs | `verified_once` | global attention 70.2245% and positionwise feed-forward 19.4935% of sampler CUDA event span |
| Select next bounded lever | `candidate_only` | `MIXED_SUBBLOCK_SELECTIVE`: keep global attention Full Compute and examine feed-forward positionwise work under a separate Quality-First approval |

The ideal group elimination ceilings are theoretical only. C4-S0 implemented
no selective execution and makes no quality, speedup, combined-speedup, or
product-promotion claim. Exact GPU kernel duration was not collected because
profilers were disabled. See the detailed
[C4-S0 worklog](docs/worklogs/2026-08-07-c4-s0-h3-subblock-cost-coupling.md).

## C4-S1 — H3 Feed-Forward Positionwise Token Selective Compute

Overall status: `stopped`; publication status: `published`. Bounded decision:
`C4_S1_INSTRUMENTATION_OVERHEAD_TOO_HIGH`; constitution disposition:
`REVISE_ONCE`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated C4-S1 work | `published` | [Issue #76](https://github.com/ksse29077-byte/HIVEFRAME/issues/76) completed; branch `accel/c4-s1-h3-ff-token-selective`; PR [#77](https://github.com/ksse29077-byte/HIVEFRAME/pull/77) merged into the R1 base main |
| Freeze causal selector and Gates before runtime | `verified` | P0/P1/P2, anchors 0/1/18/19, actual-history-only features, no consecutive skip, 10% block guard, fixed quality/comparison Gates; commit `6c21862...` |
| Validate source, segment, execution, and memory contracts | `verified` | exact H3 source digest; final contiguous 14,985-row video segment; 5,376 hidden width; 15 focused model-free tests |
| Execute fixed CONTROL shadow | `verified_once` | one eligible Generation, retry 0; 20 forwards, 1,000 full MLP calls, 15,424,000 rows, attention and FF both Full Compute; 124/124 H.264 frames with audio |
| Pass instrumentation comparison | `stopped` | sampler 519.822272 s versus immutable C4-S0 488.847320 s; +6.336324% exceeds fixed +/-5% band |
| Select a causal FF policy | `stopped` | selection was blocked by the earlier comparison Gate; no policy received execution authority |
| Execute SELECTIVE | `stopped` | prohibited by the predeclared Gate; SELECTIVE Generation count 0 and paired quality/runtime not collected |
| Preserve safety and claim boundary | `verified_once` | Full Compute output valid; OOM/retry/CUDA-fatal 0; tensor-to-Rust and full tensor cache 0; speedup, quality, and product promotion 0 |

The CONTROL shadow observed only 8, 78, and 1,000 predicted skipped rows for
P0, P1, and P2 respectively; even P2 represented 0.0064834% of all MLP rows
and affected nine blocks. These observations are not an official downstream
admission because CONTROL comparability failed first. This result rejects
neither the entire feed-forward cost surface nor the cumulative 2.0x product
goal. It requires one separately approved instrumentation refinement before
this exact selector can be tested further. See the detailed
[C4-S1 worklog](docs/worklogs/2026-08-08-c4-s1-h3-ff-token-selective.md).

## C4-S1-R1 — Minimal Telemetry / Selector Overhead Truth

Overall status: `stopped`; publication status: `draft_pr`. Bounded decision:
`C4_S1_R1_MINIMAL_PATH_OVERHEAD_TOO_HIGH`; exact-selector disposition:
`FALLBACK_ONLY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track the single C4-S1 revision | `draft_pr` | [Issue #78](https://github.com/ksse29077-byte/HIVEFRAME/issues/78); branch `accel/c4-s1-r1-h3-ff-minimal-telemetry`; Draft PR [#79](https://github.com/ksse29077-byte/HIVEFRAME/pull/79) |
| Freeze unchanged selector and reduced telemetry | `verified` | Commit `28c21dc...`; P0/P1/P2, anchors, history, 10% guard, quality/opportunity Gates unchanged; per-block events, explicit sync, histogram, CONTROL host reads, and resource sampler removed |
| Validate decision-equivalent p99 handling | `verified` | numeric p99 `null`; fixed >0.010 rate <=0.005 conservatively implies nearest-rank p99 <=0.010; focused boundary tests passed |
| Execute minimal CONTROL | `verified_once` | one Generation, retry 0; 20 forwards, 1,000 full MLP calls, 15,424,000 rows; 124/124 H.264 frames with audio; instrumentation integrity Gate passed |
| Pass CONTROL comparison | `stopped` | sampler 520.488870 s versus immutable 488.847320 s; +6.472686% exceeds fixed +/-5% band |
| Evaluate official policy admission | `stopped` | blocked by earlier CONTROL Gate; 8/78/1,000 candidate rows remain diagnostic only |
| Execute SELECTIVE | `stopped` | prohibited by the fixed Gate; Generation count 0 and quality/runtime not collected |
| Preserve safety and claims | `verified_once` | Full Compute fallback preserved; actual work reduction, speedup claim, quality promotion, and product promotion 0 |

The one permitted revision removed measurement-only telemetry but did not
recover comparability. The exact selector is now fallback-only and has no
automatic R2. The independent feed-forward cost surface remains valid but
requires a different, separately approved product question and mechanism.
Global attention remains Full Compute. See the detailed
[C4-S1-R1 worklog](docs/worklogs/2026-08-09-c4-s1-r1-h3-ff-minimal-telemetry.md).

## A3 — Regional Attention Output Reuse with Correction

Overall status: `stopped`; publication status: `draft_pr`. Bounded
decision: `A3_ATTENTION_OUTPUT_REUSE_STRUCTURALLY_NOT_ADMITTED`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated A3 work | `draft_pr` | [Issue #86](https://github.com/ksse29077-byte/HIVEFRAME/issues/86); branch `accel/a3-h3-attention-output-reuse-correction`; Draft PR [#87](https://github.com/ksse29077-byte/HIVEFRAME/pull/87) |
| Freeze mechanism before any runtime | `verified` | Commit `ef6f700...`; prior actual Full Attention-core cache only, channel-mean delta, age one, no chaining, unchanged A1 ABI, fixed Gates and decision matrix |
| Validate source, mapping, cache, and ownership | `verified` | Installed H3/A1/A2 structural checks passed; H3-specific rows, cache, CUDA, and correction remain adapter-owned; 26 focused model-free tests passed |
| Admit host cache capacity | `verified_once` | 50,546,864,128 available host bytes; 172,390,400 bytes/block; 12 ranked blocks fit the 2 GiB cap; staging stays below 256 MiB |
| Admit same-block runtime guard dispatch | `stopped` | Current PyTorch adapter cannot branch from a current CUDA scalar guard to same-block Full Attention without a blocking host sync or unconditional Full Attention |
| Execute CONTROL or SELECTIVE | `stopped` | Pre-generation structural Gate failed as declared; model load, CUDA, Generation, retry, CONTROL, and SELECTIVE counts are zero |
| Claim work reduction, quality, or speedup | `stopped` | Runtime and paired output do not exist; values remain uncollected rather than zero-filled |

The cache/correction idea remains an attention-surface hypothesis, but A3 V1
does not have safe execution authority. A GPU-native conditional-dispatch hook
or a separately approved pre-admission contract is required before another
runtime experiment. Full Compute remains the default. See the detailed
[A3 worklog](docs/worklogs/2026-08-10-a3-h3-attention-output-reuse-correction.md).

## A3-G0 — GPU-Native Conditional Kernel Omission Primitive

Overall status: `verified_once`; publication status: `draft_pr`. Bounded
decision: `A3_G0_GPU_CONDITIONAL_OMISSION_READY`.

| Task | Status | Evidence or blocker |
|---|---|---|
| Track isolated A3-G0 work | `draft_pr` | [Issue #88](https://github.com/ksse29077-byte/HIVEFRAME/issues/88); branch `runtime/a3-g0-gpu-conditional-omission`; Draft PR [#89](https://github.com/ksse29077-byte/HIVEFRAME/pull/89) |
| Admit a native Windows CUDA build path | `verified_once` | Official CUDA 13.0.2 minimal developer components; NVCC 13.0 V13.0.88; conditional-device source compiled and linked |
| Freeze the bounded primitive | `verified` | Two complementary CUDA Graph IF nodes, one GPU guard, fixed SAFE/UNSAFE/SAFE/UNSAFE replay, preallocated buffers, exact fail-closed fallback |
| Execute the fixed synthetic primitive | `verified_once` | One fixed native sequence; reuse/exact body evidence 2/2; branch history 0/1/0/1; no state leak |
| Preserve exact fallback parity | `verified_once` | SAFE output bit-exact to an independent reuse reference; UNSAFE output bit-exact to standalone exact control |
| Preserve the host/synchronization boundary | `verified_once` | guard D2H 0 bytes; host guard reads 0; hot-path explicit CPU sync 0; one final evidence sync; conditional-body allocations 0 |
| Integrate actual H3 attention | `not_started` | A3-G0 is synthetic only; actual H3 attention omission, model load, and Generation counts are zero |
| Claim speed or quality | `stopped` | No profiler kernel-launch count, H3 paired output, runtime speedup, quality success, or product promotion exists |

A3-G0 closes only the missing GPU-native conditional execution primitive. It
does not revive A3 V1 automatically and does not authorize A3-G1. Standard
Full Compute remains the product default, and the experimental adapter
capability is disabled by default. See the detailed
[A3-G0 worklog](docs/worklogs/2026-08-10-a3-g0-gpu-conditional-omission.md).

## Maintenance checklist

- [ ] Update this file when task state changes.
- [ ] Add a dated entry to `docs/WORKLOG.md`.
- [ ] Link receipts, reports, commits, Issues, and PRs only after verification.
- [ ] Keep unsupported and unverified items explicit.
