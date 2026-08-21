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

## Release ABI and full admission

The release PyO3 extension was rebuilt from this branch and loaded from the
fresh release target. The required Python/PyO3 tests passed 15/15 with zero
skips, and the Rust CachePlan V2 tests passed 12/12. Rust tensor bytes remain
zero, Rust calls are bounded to one per Generation, and per-block,
per-region, and per-row Rust calls remain zero. The release extension SHA-256
is `f63d99fcded29b78e64059a3c5145fa7c43cf51670dbb65c3250994052e7df2f`.

The immutable P1-A2 database identified exactly one succeeded Standard I2V
job. Its prompt digest was
`5839910f0399be0c3e6b9b4cdad11890a0d0d65327b38a36d6f1e190dacfdc82`.
The original reference image digest was
`493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411`,
and the approved workflow digest was
`31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6`.

Immediately before execution, external product queues were empty, port 8191
was free, no foreign ComfyUI process was found, and the process-ownership Gate
passed. GPU use was 10 MiB. The projected CUDA peak was 12,514,625,897 bytes
against 12,884,377,600 physical bytes, leaving 369,751,703 bytes of projected
headroom, above the fixed 256 MiB minimum. All pre-start and post-start
admission checks passed.

## Formal CONTROL result

The one authorized H3 Standard Full Compute Formal CONTROL was submitted
exactly once. It reached GPU execution and one reported sampler progress
record before ComfyUI terminated with `execution_error`:

```text
error_type=ControlV2EvidenceError
error_message=CPU oracle lag would overwrite the pinned ring
submission/GPU start/completion=1/1/0
retry/fallback=0/0
SELECTIVE/partial-Q/Attention omission=0/0/0
```

The production oracle failed closed while `_refresh_cache()` attempted to
enqueue another 48,269,312-byte D2H payload and no slot in the four-slot ring
was reusable. The preflight saturation fixture proved that all four slots and
their state transitions work, but the live H3 producer burst exceeded the
CPU oracle's actual service progress. No overwrite, partial result admission,
or Standard fallback occurred.

Because Generation did not complete, expected 600-enqueue/480-evidence
cardinality, holdout false-safe/false-unsafe, planned Q reduction, output
integrity, and runtime ring high-water could not be established. Rust live
compile and offline replay were therefore not entered; their counts remain
zero. No MP4 was produced.

The private receipt SHA-256 is
`46190416d72301e32a636238c9a40eca89c4c8e1e63278dbb497f141b885e714`.
The callback receipt SHA-256 is
`c5f71cf734b2e7d362933ab9ec3698b2b33d914442b81c18b7d8b49f7bc79fe2`,
the pinned admission receipt SHA-256 is
`f848b4accc7d40529e11331e28bf97743e708dab28296aae85dfdc64d5021650`,
and the runtime log SHA-256 is
`b819e56c1bce62d1381c867a9ae1e1cd0ae91320eeb3ef3d6de7030e0dbcda8b`.

Repository-wide Rust verification after the run passed `cargo fmt --check`,
all 50 workspace tests, and the all-feature release build. The all-target,
all-feature clippy command remained blocked by two pre-existing
`manual_div_ceil` diagnostics in `crates/hive-retina-runtime/src/locality.rs`
at lines 243 and 244. Those unrelated lines were not changed under this
bounded authorization.

## Cleanup and final counters

Only the verified owned runtime tree was stopped. Foreign-process and direct
console-helper termination counts were both zero. A post-run ownership check
found zero runtime candidates and zero listeners on port 8191; both external
product queues remained empty and GPU use returned to the 10 MiB baseline.

```text
PRIOR_CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=2
CURRENT_TASK_FORMAL_CONTROL_SUBMISSIONS=1
FINAL_CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=3
CURRENT_TASK_RETRY_COUNT=0
DIAGNOSTIC_SUBMISSIONS=1
```

## Decision

```text
H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_FAILED
```

The READY-for-executor-integration verdict is not earned. The one-time
exception ends with this failed single submission. No additional CONTROL,
remediation, SELECTIVE execution, partial-Q, Attention omission, executor or
product integration, LTX, Wan, or Installer work was started.
