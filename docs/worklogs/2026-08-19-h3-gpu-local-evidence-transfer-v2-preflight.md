# H3 GPU-Local Evidence and Transfer V2 Preflight

Date: 2026-08-19
Issue: #105
Draft PR: #106
Branch: `codex/h3-gpu-local-evidence-transfer-v2`
Base: `963b68bf8d00f2871378e1496ae3f8cd02abf1db`
Implementation commit: `8b838db`
Decision: `H3_GPU_LOCAL_EVIDENCE_TRANSFER_V2_PREFLIGHT_READY`

## 1. Scope and Exception

The user granted a one-time constitution exception for this preflight only.
It allowed analysis of the failed CONTROL's partial evidence, implementation of
a GPU-local evidence structure, model-free tests, bounded synthetic CUDA, and
isolated GitHub work. H3 Generation, a CONTROL rerun, SELECTIVE, partial-Q,
Attention omission, product integration, LTX, Wan2.2, installer work, ROADMAP,
TASKS, and changes to PRs #91/#95/#97/#99/#101/#103 were prohibited.

No prohibited execution occurred. H3 model loads, ComfyUI Generations, CONTROL
Generations, SELECTIVE Generations, and partial-Q executions were all zero.
The next full CONTROL remains an unexecuted holdout.

## 2. Git Isolation

GitHub CLI authentication was restored without credential extraction. The
previous CONTROL retry branch was clean at the exact required HEAD. Its pending
Draft PR was created first as #104. Issue #105 and this branch were then created
from that exact HEAD. Draft PR #106 targets the CONTROL retry branch. Prior PRs
were not modified.

## 3. Failed CONTROL Ledger

The source callback receipt SHA-256 is
`2baf0159f08a4b5e6a07e1f01db2e94160c26c4ee8d120efab7c0c7ae28a5dda`.
It remains outside Git. Its incomplete evidence is classified
`CALIBRATION_ONLY`; it was not sent to Rust and was not used as holdout success.

| Transfer leg | Bytes |
|---|---:|
| Payload D2H | 30,057,990,144 |
| Payload H2D | 12,856,610,816 |
| Reproduced total | 42,914,600,960 |
| 40 GiB hard cap | 42,949,672,960 |
| Remaining at rejection | 35,072,000 |

The failure was structural: source payloads were copied to pinned host at each
eligible source step and uploaded again for each metric observation. GPU metric
reduction was already present, but it occurred after repeated payload movement.

## 4. False-Safe Attribution

All 19 false-safe records are attributed below. `lineage` is a non-identifying
source identity digest over the frozen run/model/workflow/settings lineage plus
source step, block, and region. Packed rows are a sparse set represented by its
minimum, maximum, and exact count.

| Step | Source | Block | Region | Predicted | Motion ppm | Uncertainty ppm | Cosine | Corrected nL2 | Packed rows | Age | Lineage | Payload B |
|---:|---:|---:|---:|---|---:|---:|---:|---:|---|---:|---|---:|
| 6 | 5 | 30 | 0 | STABLE | 11809 | 295225 | 0.957275 | 0.290521 | 0-14754 (3367) | 1 | `21524cb41dd7dacf4723a660a058f6d13b539a7be79b226ce742fddd951b8033` | 48269312 |
| 6 | 5 | 31 | 0 | STABLE | 11809 | 295225 | 0.944383 | 0.331581 | 0-14754 (3367) | 1 | `6b6294183317bddcb207b9baa26ca033951553441c04f3c4f4e05ec7c7612a6c` | 48269312 |
| 6 | 5 | 48 | 0 | STABLE | 11809 | 295225 | 0.953837 | 0.302894 | 0-14754 (3367) | 1 | `fcfc9c44a9d88d99d9f4777746788b58e33edafd31568dd60774cfaae112e040` | 48269312 |
| 6 | 5 | 48 | 1 | STABLE | 11644 | 291100 | 0.959585 | 0.283085 | 15-14768 (3108) | 1 | `ff5e7bd2d80b5a86c1353f9581d8127168d3ec9aa9045e5cc16255079af4a885` | 44556288 |
| 6 | 5 | 49 | 0 | STABLE | 11809 | 295225 | 0.964178 | 0.267922 | 0-14754 (3367) | 1 | `8bbc75a202c284638d5a9665cad57498ca45d781ca1d9105484c64437ae97d1a` | 48269312 |
| 8 | 7 | 30 | 0 | STABLE | 4720 | 118000 | 0.962632 | 0.272011 | 0-14754 (3367) | 1 | `fde1502cdd9d947b8f6e5a3f60f418a3c6c88261861cc7f43d2cafb0a643bee1` | 48269312 |
| 8 | 7 | 31 | 0 | STABLE | 4720 | 118000 | 0.950863 | 0.311414 | 0-14754 (3367) | 1 | `d11ebf18549d22e74edc25f8ff0407140d41a3d5af8997a4503b5ed31754bc81` | 48269312 |
| 8 | 7 | 48 | 0 | STABLE | 4720 | 118000 | 0.968186 | 0.251474 | 0-14754 (3367) | 1 | `ed78a27bf7f74ea8f969fbb341bd3065f068a3f2ad9e502f85ca9eb3c5a9e33d` | 48269312 |
| 10 | 9 | 30 | 0 | STABLE | 4548 | 113700 | 0.968172 | 0.251353 | 0-14754 (3367) | 1 | `25bcf741756c9592b80ef7f3088681e8b51ca918a47d734dc626ec9f09cff8e5` | 48269312 |
| 10 | 9 | 31 | 0 | STABLE | 4548 | 113700 | 0.957856 | 0.288825 | 0-14754 (3367) | 1 | `1b777d45d556b3f2ff5ed9cb00dd273afa831e6e5d5e0bb4e259690460845d03` | 48269312 |
| 10 | 9 | 48 | 0 | STABLE | 4548 | 113700 | 0.964638 | 0.264713 | 0-14754 (3367) | 1 | `28abbdeadb259760a4f772de4bd01419713bd616b1a9e944938a057c1c9301b4` | 48269312 |
| 10 | 9 | 48 | 1 | STABLE | 4469 | 111725 | 0.953210 | 0.305497 | 15-14768 (3108) | 1 | `337ca2cef3da677471d6af608a80ad4f777d4b9ff0685e69f380bd28790e20b4` | 44556288 |
| 10 | 9 | 49 | 1 | STABLE | 4469 | 111725 | 0.954828 | 0.302017 | 15-14768 (3108) | 1 | `87508816e4d465ceca20e46bdbb7f0c4665bbd6b4453ba9516a1bcb9356e5abd` | 44556288 |
| 12 | 11 | 30 | 0 | STABLE | 2495 | 62375 | 0.968063 | 0.251852 | 0-14754 (3367) | 1 | `4c2cf5d800968f390a96a6e9aa639ea8454f28e157884c6a8ebc9f69cfe790c6` | 48269312 |
| 12 | 11 | 31 | 0 | STABLE | 2495 | 62375 | 0.958178 | 0.287998 | 0-14754 (3367) | 1 | `b517599de11b669c0102aca0c855476b9df50ee0ad3f36eb048b7d8c23d53ec8` | 48269312 |
| 12 | 11 | 48 | 0 | STABLE | 2495 | 62375 | 0.952597 | 0.308471 | 0-14754 (3367) | 1 | `d5c7778bd71c32f50015db53a21423b8fcd3838f82a52cb77eb5bc168e083823` | 48269312 |
| 12 | 11 | 49 | 0 | STABLE | 2495 | 62375 | 0.963489 | 0.270805 | 0-14754 (3367) | 1 | `1d19da6c3a7b5f145864466365c230791576a0365a375761fef02934b61b2168` | 48269312 |
| 14 | 13 | 30 | 0 | STABLE | 1690 | 42250 | 0.964880 | 0.264337 | 0-14754 (3367) | 1 | `3809555d3b5e09119e6c2bb7896fae4d7ef76d057000070a26ae5a0941333222` | 48269312 |
| 14 | 13 | 31 | 0 | STABLE | 1690 | 42250 | 0.953262 | 0.304728 | 0-14754 (3367) | 1 | `628bf6dbc546ea8be23caca2ef9530c8de39996506c25faae0b23fa61f5ce38b` | 48269312 |

The failures concentrate in blocks 30, 31, 48, and 49. Blocks 30 and 31 each
failed at every fully observed STABLE interval. The conservative pre-Attention
rule therefore sends all regions of those four blocks to Full Compute. It does
not read post-Attention cosine or nL2 online. The remaining calibration-selected
set has 150 records, false-safe zero, and 349,650 planned Q rows (2.2669%). That
is calibration only, not a three-percent or holdout claim.

## 5. Safe Geometry Potential

After the static veto, blocks 0 through 29 and region 0 remain as the bounded
candidate geometry. Thirty blocks times 2,331 omitted rows require seven
age-one events to reach 489,510 planned rows, or 3.173690% of 15,424,000 Full Q
rows. Sixteen source intervals are structurally available. This is recorded as
`GEOMETRY_POTENTIAL_NOT_HOLDOUT_RESULT`; the holdout remains `UNKNOWN`.

The corresponding persistent GPU payload is 1,448,079,360 bytes, below the
2 GiB cap. Actual H3 free-VRAM admission was not executed. The collector itself
requires a measured free-VRAM value and reserve before allocating a slot, and
rejects calibration-veto blocks before allocation. Balanced12GB and
Quality24GBPlus use the same algorithm and candidate rules; the latter remains
`SIMULATED_NOT_EXECUTED`.

## 6. GPU-Local Collector

The new collector preallocates persistent source slots, current-region staging,
a maximum-640 GPU metric matrix, pinned final host storage, and CUDA events.
Source capture uses GPU `index_select(..., out=...)`. Age and lineage mismatches
fail open. Repeated source identities are deduplicated. Raw and corrected
metrics are reduced in bounded chunks on GPU, and unsafe status is written into
the GPU metric row.

The capture, reduction, and observation hot path contains no `.cpu()`,
`.numpy()`, `.item()`, `.tolist()`, or explicit synchronization. Finalization
performs one compact nonblocking copy and one final-only event wait. Incomplete,
overflowed, invalid, or nonfinite batches are not admission eligible. CONTROL
evidence storage remains separate from the unimplemented future Selective
cache path.

## 7. Projected Transfer Receipt

The maximum evidence matrix is 640 records x 11 float32 values = 28,160 bytes.
Including the existing 3,840-byte C2 compact metadata gives a projected next
20/20 CONTROL transfer of 32,000 bytes. Cache payload D2H/H2D are structural
zero in this GPU-local CONTROL evidence design. Headroom under 40 GiB is
42,949,640,960 bytes, above the required 8 GiB. Attention time saved, H3
transfer/sync cost, and net gain remain `UNKNOWN` because no H3 run occurred.

## 8. Bounded Synthetic CUDA

Before each CUDA probe, ports 8188 and 8191 had no listener and queue counts
were running 0 and pending 0. No external process was terminated. Four small
development-verification invocations were made, each only after a code change;
none imported H3 or submitted ComfyUI work. The final fixed receipt used one
96x32 BF16 source/current fixture on the RTX 3060.

| Final synthetic metric | Result |
|---|---:|
| Measured free VRAM before fixture | 11,799,625,728 B |
| CPU/GPU maximum metric error | 2.980232e-7 |
| GPU reduction event span | 134.627518 ms |
| Compact transfer event span | 0.046560 ms |
| Evidence metadata D2H | 44 B |
| Payload D2H / H2D | 0 B / 0 B |
| Duplicate source D2H avoided | 6,144 B |
| Hot-path forced sync | 0 |
| Final-only CUDA sync | 1 |
| Batch flush | 1 |
| Rust calls / tensor bytes | 0 / 0 B |

The event span includes CUDA context and first-use effects and is not an H3
performance result. The ignored local sanitized receipt is 24,036 bytes with
SHA-256 `7578f9036f0569dda027d521c4529d41331069eabf3a3a6bbac060269a6e3281`.
It contains no private path, prompt, image, model payload, or credential.

## 9. Verification

- New focused suite: 6/6 passed.
- Combined new, prior CONTROL, and Python ABI suite: 17 passed, 4 skipped.
- The four skips are real PyO3 cases because no local extension binary was
  present; the model-free bridge tests passed.
- Rust `cache_plan_v2` subset: 12/12 passed.
- `cargo fmt --all -- --check`: passed.
- Python bytecode compile: passed.
- Completion Gates: 20/20 passed.
- H3 model load / Comfy Generation / CONTROL / SELECTIVE / partial-Q: 0/0/0/0/0.

## 10. Decision

Final decision: `H3_GPU_LOCAL_EVIDENCE_TRANSFER_V2_PREFLIGHT_READY`.

This means the metadata-only GPU reduction structure, conservative calibration
veto, bounded transfer projection, and unchanged CachePlan ABI V2 boundary are
ready for review. It does not mean H3 quality, false-safe holdout, runtime gain,
or actual Attention omission has passed. `H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2`
is the next separately approvable task and was not started. The one-time
exception ends with this report. Diagram impact: none.
