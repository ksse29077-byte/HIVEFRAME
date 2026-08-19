# H3 12 GB Hybrid Cache Staging Preflight

Date: 2026-08-19  
Issue: #107  
Branch: `codex/h3-12gb-hybrid-cache-staging-preflight`  
Base: Draft PR #106 head `be0e8f0d2e81fb4a69a5aa6962f3333ead7d945f`  
Decision: `H3_12GB_HYBRID_CACHE_STAGING_PREFLIGHT_READY`

## 1. Scope and exception boundary

The one-time constitution exception allowed only a model-free staging
preflight. No H3 model was loaded and no ComfyUI workflow, CONTROL,
SELECTIVE, partial-Q, or Attention-omission execution was submitted. Product
UI/backend, LTX, Wan2.2, installer, `ROADMAP.md`, and `TASKS.md` were unchanged.
PRs #91, #95, #97, #99, #101, #103, #104, and #106 were not modified.

The product-blocking question was whether the V2 evidence design can fit the
RTX 3060 12 GB runtime by moving the Full Compute CONTROL oracle payload to
host memory without changing the GPU pre-Attention predictor or Rust ABI.

## 2. Preserved safety boundary

- STABLE/ACTIVE/UNCERTAIN, motion, uncertainty, and pre-Attention metrics stay
  on GPU.
- Rust receives one bounded metadata batch at most once per generation. Rust
  tensor bytes and per-block/per-region/per-row Rust calls remain zero.
- The CONTROL oracle labels only completed Full Compute output. They cannot
  authorize current-step reuse or enter the online predictor.
- Blocks 30, 31, 48, and 49 remain pre-Attention Full Compute vetoes.
- The immutable 279-record evidence remains `CALIBRATION_ONLY`; holdout status
  remains `UNKNOWN`.
- The remaining 30-block region-zero geometry has calibration false-safe zero
  and 489,510 planned rows out of 15,424,000, or 3.173690%. This is geometry
  potential only.

## 3. Balanced12GB staging contract

The previous full source-residency proposal is replaced for CONTROL only:

1. Each current BF16 candidate is copied once by async D2H through one
   dedicated CUDA stream.
2. Two fixed pinned ingress slots are used. Each slot is bounded by the
   largest candidate, 48,269,312 bytes.
3. The prior step's 30 BF16 sources are retained in a bounded pageable-host
   cache totaling 1,448,079,360 bytes.
4. A background CPU worker waits on the slot's CUDA event, computes exact
   cosine and corrected normalized L2, then rotates the current payload into
   the source cache.
5. A busy slot is never overwritten or dropped. Backpressure, timeout,
   overflow, lineage mismatch, step disorder, nonfinite data, page-lock
   failure, or allocation failure blocks CONTROL submission.

The enqueue hot path contains no `.cpu()`, `.numpy()`, `.item()`, `.tolist()`,
or `.synchronize()`. CONTROL H2D is structurally zero. Source identity
deduplication runs before D2H; the admitted schedule requires zero duplicate
transfers.

## 4. VRAM admission

The reported 1,448,079,360 bytes is a logical BF16 candidate payload and, in
the Balanced12GB profile, a host source-cache budget. It is not persistent CUDA
VRAM. The pinned ring is host/page-locked memory, also not VRAM.

| Item | Bytes | Classification |
|---|---:|---|
| Historical H3 Comfy peak | 12,459,802,548 | measured system sample |
| Historical NVIDIA peak | 11,990,466,560 | measured system sample |
| Physical RTX 3060 VRAM | 12,884,377,600 | measured device capacity |
| Shared candidate staging | 48,269,312 | projected additional CUDA allocation |
| Compact metric buffer | 28,160 | projected additional CUDA allocation |
| Allocator-adjusted staging + metric | 53,774,773 | projected from 3,690,987,520 / 3,315,037,120 reserve ratio |
| Stream/event bookkeeping reserve | 1,048,576 | conservative bounded ledger |
| Projected simultaneous peak | 12,514,625,897 | projected |
| Physical headroom | 369,751,703 | projected |

The simultaneous interval is H3 Full Attention plus shared staging, compact
metrics, stream/event bookkeeping, and allocator reserve. Persistent full
source CUDA bytes are zero. The projected peak is below physical VRAM, so the
bounded preflight passes. It does not satisfy the 2 GiB policy reserve:
`BALANCED12GB_2GIB_RESERVE_SATISFIED=false`.

## 5. Host RAM admission

| Item | Bytes |
|---|---:|
| Physical RAM | 66,145,665,024 |
| Current available RAM at preflight | 47,136,583,680 |
| Historical system-wide H3 peak | 62,809,526,272 |
| Historical process-tree RSS peak | 47,340,367,872 |
| Pageable BF16 source cache | 1,448,079,360 |
| Pinned slot size / depth | 48,269,312 / 2 |
| Total pinned ring | 96,538,624 |
| Projected historical-peak total | 64,354,144,256 |
| Remaining physical headroom | 1,791,520,768 |
| Reserved for OS/ComfyUI | 1,610,612,736 |
| Headroom after reserve | 180,908,032 |

Admission passes, but the margin is narrow. The implementation therefore does
not treat allocation or page-lock failure as a regional Full Compute fallback;
it blocks CONTROL submission before Generation. A future admission must repeat
the current available-RAM check immediately before the one approved CONTROL.

## 6. Transfer and receipt contract

Thirty candidate payloads aggregate to 1,448,079,360 bytes per step. The
conservative 20-step projection is 28,961,587,200 bytes (26.97 GiB), below the
32 GiB limit. Each source identity transfers at most once per step. CONTROL
oracle H2D, duplicate D2H, duplicate H2D, hot-path forced sync, Rust tensor
bytes, and actual reuse are structural zero.

The receipt explicitly carries `PROFILE`, `ORACLE_MODE`, GPU source/staging/
metric bytes, pinned slot/depth/total, CONTROL D2H/H2D, duplicate transfer
bytes, CUDA stream/event counts, hot-path/background waits, ring backpressure/
overflow, CPU oracle/D2H/GPU predictor timings, Rust calls/tensor bytes, and
projected attention saving/H2D cost/net gain. Actual H3 timing fields are
`NOT_EXECUTED`; speed fields are `UNKNOWN`, never numeric zero.

## 7. Quality24GBPlus and future Selective

Quality24GBPlus uses the same predictor, lineage, metadata, and Rust ABI. Its
GPU-resident source and shared-current-staging peak remains the prior projected
15,355,989,428 bytes. No 24 GB device was present, so the profile is
`SIMULATED_NOT_EXECUTED`; no speed or quality claim exists.

Future Selective is contract-only and was not executed. It may retain BF16
source on host and perform H2D only for an actual cache hit. It must use fixed
source/current staging, preserve partial/full XOR, and admit reuse only when
measured Attention savings exceed H2D and synchronization cost. Miss, timeout,
lineage mismatch, scene cut, or prefetch failure means regional Full Compute.
FP8, INT8, and INT4 cache formats remain prohibited.

## 8. Synthetic verification

Both loopback queue endpoints reported running 0 and pending 0. A single
96x32 BF16 source/current fixture ran on the RTX 3060 without importing H3 or
submitting a workflow.

| Check | Result |
|---|---|
| BF16 D2H bit preservation | PASS |
| CPU/GPU maximum metric error | 2.3841858e-7, PASS <= 1e-6 |
| Prior error reference | 2.980232e-7; not worsened |
| Threshold classification | identical |
| Duplicate source D2H | deduplicated before transfer |
| Busy-slot overwrite | blocked by backpressure |
| Normal synthetic ring overflow/backpressure | 0 / 0 |
| Hot-path forced sync | 0 |
| H3/model/Generation/CONTROL/SELECTIVE/partial-Q/omission | 0/0/0/0/0/0/0 |

The sanitized local receipt is 14,681 bytes with SHA-256
`1970ad50efa50fe2ded9649f65ef1dc8f6a5315d4a94dd198f047568155dd4fc`.
The immutable source receipt is 357,928 bytes with SHA-256
`2baf0159f08a4b5e6a07e1f01db2e94160c26c4ee8d120efab7c0c7ae28a5dda`.
Both remain outside Git.

## 9. Verification

- New focused Python: 8/8 passed.
- Related Python with release PyO3 loaded: 29/29 passed.
- Required CONTROL + CachePlan PyO3 subset: 15/15 passed, skip 0.
- Rust CachePlan ABI V2: 12/12 passed.
- `cargo fmt --all -- --check`: passed.
- Python bytecode compilation: passed.
- Release PyO3 ABI 2 binary: 587,264 bytes, SHA-256
  `7257df472c558415c0a2d4b90d9a327b4ac6ccda40dff5cd78cedff936f35e18`.
- Completion Gates: 21/21 passed.

The expected panic-containment test printed the Rust panic hook and passed;
the panic was contained as Full Compute. Rust tensor bytes are zero, the plan
boundary remains at most one generation call, and per-block/per-region/per-row
Rust calls are zero.

## 10. Decision

Final decision: `H3_12GB_HYBRID_CACHE_STAGING_PREFLIGHT_READY`.

This admits only the staging and runtime-admission structure. It does not claim
H3 quality, runtime gain, holdout safety, or real Attention omission. The next
separately approvable task is `H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2`.
It was not started. The one-time exception ends with this report.

Diagram impact: updated. The system map now shows host-staged CONTROL oracle
preflight as verified model-free structure and CONTROL V2 as a dashed,
separately approved next step.
