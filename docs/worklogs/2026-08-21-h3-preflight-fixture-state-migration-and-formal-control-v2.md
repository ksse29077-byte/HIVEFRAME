# H3 Preflight Fixture State Migration and Formal CONTROL V2

## Authorization and exact base

Issue #131 tracks the one-time constitutional exception for
`H3_PREFLIGHT_FIXTURE_STATE_MIGRATION_AND_FORMAL_CONTROL_V2`. This branch
starts from exact Draft PR #130 head
`c10d2e559b5fc70b69615fcec8d3c864a4302afe`; local, upstream, and remote PR
heads matched and the worktree was clean before branch creation. Existing PRs
remain unchanged.

The authorized code change is limited to migrating stale row-region CUDA
preflight fixtures from `PENDING` to the production slot lifecycle. The
production finalizer must continue to reject `PENDING`, unknown states,
skipped transitions, duplicate finalization, and reuse before FREE.

## Execution boundary

Focused and bounded CUDA fixture Gates must pass before H3 model load or
workflow submission. Only then may exactly one H3 Standard Full Compute Formal
CONTROL run, followed by complete holdout adjudication and one Rust CachePlan
V2 live compile plus deterministic offline replay.

SELECTIVE, partial-Q, Attention omission, executor integration, product
wiring, production-finalizer relaxation, retry, fallback Generation, and
automatic follow-up work are prohibited.

## Starting counters

```text
PRIOR_CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=2
CURRENT_TASK_FORMAL_CONTROL_SUBMISSIONS=0
CURRENT_TASK_RETRY_COUNT=0
DIAGNOSTIC_SUBMISSIONS=1
```

The PR #130 Admission block had submission/GPU start `0/0` and is not a Formal
CONTROL submission.

## Fixture migration

The stale row-region CUDA fixtures now begin FREE, enter
`D2H_IN_FLIGHT`, use the unchanged production finalizer to reach CPU_READY,
then advance through PROCESSING and FINALIZED before the unchanged release
contract returns them to FREE. The separate hybrid staging preflight ring was
migrated to the same strict sequence. Invalid, skipped, legacy `PENDING`, and
unknown transitions fail closed.

The repository-wide `PENDING` search was classified before editing:

- ComfyUI `queue_pending` and product job states are unrelated and unchanged.
- human-review and proposal `pending` values are unrelated and unchanged.
- row-region CUDA fixture slot states and the hybrid staging preflight slot
  states were the affected ring states and were migrated.
- the production finalizer remains unchanged and still rejects `PENDING`.

Focused fixture, finalizer, ring, lineage, worker-failure, cardinality, and
throughput tests passed 33/33. They cover the complete lifecycle, legacy and
unknown state rejection, transition skipping, duplicate finalization, reuse
before FREE, worker fail-closed behavior, exactly-once integrity, and the
trace-derived four-slot ring.

## Bounded CUDA preflight

The model-free CUDA preflight passed without loading H3 or submitting a
workflow:

```text
decision=H3_ROW_REGION_SAFETY_CONTROL_V2_ORACLE_PREFLIGHT_READY
ring slots=4
slot bytes=48,269,312
pinned bytes=193,077,248
ring high-water=4 (bounded saturation fixture)
RING_SLOT_NOT_FREE=0
overflow/drop/overwrite=0/0/0
duplicate/missing/stale=0/0/0
hot-path forced CPU sync=0
completion Event elapsed_time calls=0
final backlog=0
all slots FREE after cleanup=true
```

All four slots recorded the exact sequence
`FREE -> D2H_IN_FLIGHT -> CPU_READY -> PROCESSING -> FINALIZED -> FREE`.
BF16 preservation, CPU/GPU metric classification, timing-event separation,
and reordered lineage checks passed. Maximum CPU/GPU metric error was
`6.468255198122108e-08`, below the fixed `1e-6` limit.

The private receipt file SHA-256 is
`fc143aeae5ed41a2aefb6dc1ca9c80b885bd8bded5e54845ad2fbda918277713`.
Its internal canonical JSON digest is
`092d6e0e56700f04f45570a2792b26a8c567fd0863959dda18f5c01181fb6c76`.
It records H3 model load, Generation, CONTROL submission, SELECTIVE,
partial-Q, and Attention omission as zero.

The Formal CONTROL runner now enforces the trace-backed runtime high-water
limit `<=3`; the four-slot saturation fixture above proves all slots are
usable but is not substituted for that runtime Gate.

Current status: `FIXTURE_AND_BOUNDED_CUDA_GATES_PASS_PENDING_FULL_ADMISSION`.
