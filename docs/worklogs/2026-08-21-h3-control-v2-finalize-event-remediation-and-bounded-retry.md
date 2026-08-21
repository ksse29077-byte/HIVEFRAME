# H3 CONTROL V2 Finalize Event Remediation and Bounded Retry

## Authorization and exact base

Issue #121 tracks the one-time constitutional exception for
`H3_CONTROL_V2_FINALIZE_EVENT_REMEDIATION_AND_BOUNDED_RETRY`. The branch starts
from exact Draft PR #120 head
`318e24cb1d7c4fbc925f04ada77293c4111e24f3` with a clean worktree and matching
local/remote head.

The task may audit the failed CONTROL evidence, repair the CUDA completion and
timing-event contract, run bounded production-path finalization tests, and run
one H3 Standard Full Compute CONTROL only when recovery is impossible and all
pre-submission Gates pass. SELECTIVE, partial-Q, Attention omission, executor
integration, product wiring, LTX, Wan, and Installer work are prohibited.

## Immutable recovery audit

The failed CONTROL directory contains seven immutable files. Their sizes and
SHA-256 digests are:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| callback receipt | 96,605 | `a7263727c3cf33f0bc9e3cc64af5a2c7bd993f71db32671a030eb433cd6d3954` |
| fixed input copy | 258,324 | `493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411` |
| runtime log | 16,015 | `63f7f34548880f2f523062e5c84f06ecb9f5ed6ca3bc8236ac46bfe8e5093a4d` |
| runtime model-path config | 260 | `ddc79cf30fee42811fc5ecb9d3d2defa4679eb49793b3ce430a87c61579b03df` |
| pinned admission receipt | 197 | `e65ac8fa8db72ba063a9fc288f87257d6e5939a4b6f54535c61cb64befc281d1` |
| private runner receipt | 161,577 | `b51398700b169f32b2ed5fd29532288e6554946ffd00c32ce3c19e012c309bf6` |
| public runner summary | 161,577 | `b51398700b169f32b2ed5fd29532288e6554946ffd00c32ce3c19e012c309bf6` |

The runner receipt preserves 20 progress records ending at 20/20 Full Compute
steps. It does not preserve expected versus actual Full Attention cardinality,
the bounded holdout records, record lineage and packed-row identity, ring
write/read sequence, ring integrity counters, D2H/H2D counters, nonfinite or
mismatch counters, candidate inventory, plan digest, or output video. The
callback contains the finalizer error instead of `attention_execution`.
Completion is 0, Rust live/replay calls are 0/0, and no MP4 exists.

Pinned memory, tensors, and CUDA Event state ended with the verified runtime
shutdown and are not inferred or reconstructed from logs. Because complete
immutable evidence, exact record cardinality, ring integrity, lineage, and
artifact completeness cannot all be verified, the audit decision is:

```text
EXISTING_CONTROL_EVIDENCE_RECOVERY=NOT_POSSIBLE
```

The failed run remains historical execution evidence only. None of its partial
worker state may enter Rust admission, holdout safety, or planned-reduction
decisions.

## Next bounded Gate

The next permitted change is the minimal completion/timing-event remediation.
Focused tests must prove production finalization with actual small CUDA events
and tensors before any H3 model load or CONTROL submission. A failed test or
runtime Admission Gate ends the task with zero current-task submissions.

Diagram impact: none. This audit does not change architecture, ownership, or
the verified product execution flow.

## CUDA Event contract remediation

The production pinned slot now owns three distinct events:

- a timing-disabled completion event used only by nonblocking `query()`;
- a timing-enabled start event;
- a timing-enabled end event.

The transfer stream records start, asynchronous D2H, end, then completion in
that order. The background worker does not call `synchronize()` and does not
admit a record before completion query reports ready. CUDA duration uses only
`start.elapsed_time(end)`. A timing exception produces `UNKNOWN`, a null CUDA
duration, and a bounded fallback reason; it does not replace CUDA duration
with host time and does not discard an otherwise complete record.

The production finalizer records bounded ring write/read sequences and checks
exact enqueue/record/D2H cardinality, sequence identity, zero incomplete,
backpressure, overflow, overwrite, drop, duplicate, lineage mismatch, H2D,
and hot-path sync counts. Successful finish releases Event references, clears
slot metadata/state, and drops the controller's last completion-event
reference. Any evidence-integrity failure remains fail-closed.

## Focused and bounded verification

- CONTROL V2 focused tests: 13/13 PASS.
- Adjacent hybrid staging, release PyO3/Rust bridge, and process ownership
  regression set: 55/55 PASS, skip 0.
- The first adjacent invocation omitted the tests and release-extension paths;
  it produced one import error and three skips before executing product code.
  The corrected 55-test invocation above is the admitted result.
- Actual model-free CUDA preflight: PASS.

The CUDA preflight used the same production `D2HEventFinalizer` with a real
3367x32 BF16 CUDA tensor, a pinned host tensor, one timing-disabled completion
event, and timing-enabled start/end events. It proved completion admission,
bit-preserved asynchronous D2H, measured timing, isolated injected timing
failure with preserved payload, cleanup, no completion-event timing call, and
hot-path forced sync zero. H3 model load, Generation, CONTROL submission,
SELECTIVE, partial-Q, and Attention omission remained zero.

Preflight receipt SHA-256:
`21f967e3793b3f829b19530d711bb2892022190f4a905ac360b8fa7e36027e4b`.

Diagram impact remains none. This change repairs bounded adapter telemetry and
evidence finalization without changing the Core/adapter boundary, compute
authority, product execution flow, or Full Compute fallback.
