# H3 Row Region Safety Evidence CONTROL V2

Date: 2026-08-19  
Issue: #109  
Branch: `codex/h3-row-region-safety-evidence-control-v2`  
Base: Draft PR #108 head `42dbf2415a50a6351c2025efab9f32b47c7eda3f`  
Decision: `H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED`

## Scope and safety boundary

The one-time exception authorized at most one H3 Standard Full Compute CONTROL.
It did not authorize SELECTIVE, partial-Q, Attention omission, retry, or an
automatic Standard fallback. Product UI/backend, LTX, Wan2.2, installer,
`ROADMAP.md`, and `TASKS.md` were unchanged. Protected PRs were not modified.

The implementation connects the PR #108 Balanced12GB staging design to the
completed Full Attention output of candidate blocks 0 through 29, region zero.
Blocks 30, 31, 48, and 49 remain Full Compute vetoes. The oracle is an observer
only and cannot affect the tensor returned by H3 Attention.

## Implemented CONTROL V2 path

- Two fixed 48,269,312-byte pinned BF16 ingress slots are allocated while the
  dedicated node is loaded, before workflow submission.
- A dedicated CUDA stream schedules one non-blocking D2H per candidate and
  step. The producer hot path has no CPU scalar read or synchronization.
- One background worker owns CUDA event waits and exact CPU metrics using the
  real 1,036 representative and 2,331 omitted region-zero row positions.
- Thirty fixed pageable BF16 source tensors are updated in place. This avoids
  a transient second 48 MB source allocation during each refresh.
- Ring lag, overwrite, overflow, duplicate identity, lineage mismatch,
  nonfinite evidence, incomplete batch, or transfer overrun fails the CONTROL.
- The complete batch is the only input to one live Rust CachePlan ABI V2 call;
  offline replay is separate. Rust tensor bytes and per-block/per-region/per-row
  calls remain zero.

The intended complete schedule is 600 D2H copies and 480 holdout records. Its
D2H bound is 28,961,587,200 bytes, H2D is structural zero, and the final source
cache is 1,448,079,360 bytes.

## Model-free and ABI verification

The real row-map CUDA preflight ran in a separate process and exited before
runtime admission. No H3 model or workflow was loaded.

| Check | Result |
|---|---:|
| BF16 D2H bit preservation | PASS |
| CPU/GPU maximum metric error | 6.4682552e-8 |
| Metric error limit | 1e-6 |
| Threshold classification | identical |
| Hot-path forced synchronization | 0 |
| H3/Generation/CONTROL/SELECTIVE/partial-Q/omission | 0/0/0/0/0/0 |

The preflight receipt SHA-256 is
`76610295e315a8ce688f231462a230bb051f94a2cc10e4596dd398dd042887bb`.

A fresh release PyO3 ABI 2 binary was built. It is 587,264 bytes with SHA-256
`34b3404e05155a99afcade419464893b2ccbe2e7c35683c09a3d58df1447185f`.
The required PyO3 subset passed 15/15 with skip 0. Rust CachePlan ABI V2 passed
12/12. The expected panic-containment test printed its panic hook and passed.
Related Python passed 30/30.

## Pre-start admission

Both existing product databases had zero queued/running/pending jobs. Their
servers were not stopped or changed. Foreign ComfyUI process count was zero,
port 8191 was free, and baseline NVIDIA VRAM usage was 10 MiB.

| Item | Bytes |
|---|---:|
| Physical VRAM | 12,884,377,600 |
| Projected CUDA peak | 12,514,625,897 |
| Projected headroom | 369,751,703 |
| Required minimum headroom | 268,435,456 |
| Available host RAM before runtime | 46,323,421,184 |

The workflow, installed H3 source, prompt source, input image, release PyO3,
Rust tests, and model-free oracle checks all passed. The Balanced12GB 2 GiB
reserve remains explicitly false as approved.

## Post-start admission and stop

The dedicated runtime started and loaded the V2 node. The node successfully
allocated and page-locked exactly 96,538,624 bytes before submission. It
reported 45,070,376,960 bytes available after that allocation, leaving
43,622,297,600 bytes after the future 1,448,079,360-byte source cache. Runtime
queues were both zero.

The final process-ownership cardinality assertion returned false. The runner
therefore stopped its owned runtime immediately, before creating a workflow
submission. The original receipt did not include the observed process list or
cardinality, so the exact extra/missing process identity cannot be recovered
after shutdown. This is a diagnostic evidence gap. The runner now records the
observed process list and requires its sole PID to match the node admission PID
for any separately approved future attempt.

Lifecycle result:

```text
submission/GPU start/completion = 0/0/0
retry/fallback = 0/0
SELECTIVE/partial-Q/omission = 0/0/0
Rust live compile/offline replay = 0/0
```

No output video or holdout batch exists, so false-safe, false-unsafe, planned Q
reduction, live/replay digest, and output integrity are `NOT_EXECUTED`, not
zero or PASS. No calibration value was copied into holdout evidence.

The private and sanitized receipts both have SHA-256
`9388ef53b507e7f02e4a747aca296154065fe6e0e7423b88bf46027ee4dbff7a`.
The matching hashes are expected because no private path reached the receipt.

## Decision

Final decision:

```text
H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED
```

The success state
`H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_READY_FOR_EXECUTOR_INTEGRATION`
was not reached. `H3_COMPOUND_EYE_ATTENTION_EXECUTOR_INTEGRATION` was not
started. The one-time exception ends with this blocked admission result; there
is no automatic retry.

