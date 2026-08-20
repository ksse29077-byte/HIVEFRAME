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
