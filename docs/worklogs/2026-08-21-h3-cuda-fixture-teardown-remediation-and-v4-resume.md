# H3 CUDA Fixture Teardown Remediation And V4 Resume

Date: 2026-08-21  
Issue: #137  
Exact base: `cabe03127ff1e7ee1503861ca62515e3dd40afce` (Draft PR #136 head)  
Branch: `codex/h3-cuda-fixture-teardown-remediation-v4-resume`

## Start Gate

The local checkout and remote PR #136 head matched the exact authorized base,
the worktree was clean, and all protected Draft PR heads matched the frozen
snapshot. The cumulative Formal CONTROL submission count remained three.
Before remediation execution, the RTX 3060 reported 12,288 MiB total, 10 MiB
used, and 0% utilization. Port 8191 listener count and discovered ComfyUI
runtime candidate count were both zero.

## PR #136 Root Cause Classification

The PR #136 fixture measured final memory before its Python function frame was
released. Its `finally` block deleted the large source, current, staging, and a
subset of host/event variables, but retained other fixture-owned locals,
including the CUDA generator, GPU row indices, fingerprint tensors, metric
outputs, producer event, and other temporary owners until function return.

The root cause is therefore:

```text
LIVE_TENSOR_REFERENCE_LEAK
```

This does not classify all post-initialization CUDA memory as a leak. The new
design separately records cold and warm baselines so lazy CUDA initialization
can be identified without hiding fixture-owned allocations.

## Implemented Remediation Contract

The remediation branch introduces an explicit ownership registry for CUDA and
pinned tensors, events, streams, futures, workers, and helper objects. The
fixture lifecycle is fixed as:

```text
RUNNING
-> STOP_ACCEPTING
-> DRAINING
-> CUDA_COMPLETION_CONFIRMED
-> WORKERS_JOINED
-> REFERENCES_RELEASED
-> ALLOCATOR_CLEANED
-> CLOSED
```

Weak references verify that released fixture tensors are actually dead after
`gc.collect()`. `empty_cache()` is called only after owned asynchronous work is
complete and strong references are cleared. `close()` is idempotent and the
registry rejects post-close enqueue. Memory snapshots include allocator bytes,
active and inactive-split bytes, allocations, segments, pinned ownership,
Python CUDA tensors and storages, worker/future/event/stream counts, and
fixture-owned object counts.

Four planned negative cases were implemented for a CUDA tensor, staging,
future-held CUDA result, and source-cache entry. Static focused tests passed
13/13 before the planned CUDA sequence.

## Planned CUDA Sequence Failure

The authorized sequence was invoked exactly once:

```text
warm-up cycle planned:       1
verification cycles planned: 3
retry:                       0
```

The warm-up failed before its first V4 source allocation. The installed
Windows Torch build rejected a `torch.device("cuda:0")` argument passed to
`torch.cuda.reset_peak_memory_stats()`:

```text
RuntimeError: Invalid device argument
source basename: h3_cuda_fixture_teardown_v4.py
function: V4CudaFixture.run
```

Execution counts at the stop point:

```text
warm-up entered:                 1
warm-up V4 source allocation:    0
warm baseline finalized:         0
negative CUDA leak cases run:    0
verification cycles completed:   0
bounded CUDA retry:              0
H3 model load:                   0
Formal CONTROL submission/start/completion: 0/0/0
Rust live compile/replay:         0/0
```

The cold memory snapshot was collected in process before the failing call, but
the probe writes receipts only after the complete sequence returns. Therefore
the exception prevented that snapshot from being persisted. It is reported as
`NOT_PERSISTED_DUE_TO_WARMUP_EXCEPTION`, not synthesized as zero. The external
pre- and post-process GPU observations were both 10 MiB used and 0%
utilization.

## Stop Decision

The instruction requires immediate termination on a teardown remediation Gate
failure and retry zero. The device argument was not changed and the planned
CUDA sequence was not rerun. V4 preflight, release PyO3, Rust/workspace build,
runtime ownership start, Formal CONTROL, holdout, output, and performance
analysis were not entered.

```text
H3_CUDA_FIXTURE_TEARDOWN_REMEDIATION_FAILED
```

Post-stop checks found port 8191 listener count zero, ComfyUI runtime candidate
count zero, GPU usage 10 MiB at 0%, and no private or public probe receipt left
by the failed process. This public worklog and the bounded failure summary are
the durable evidence for the attempt.

## Approved Continuation: Peak Reset Compatibility

The user approved continuation on the same Issue, branch, and Draft PR. The
pre-allocation error is not treated as a V4 architecture or teardown result.
The installed Windows Torch `2.12.1+cu130` API was probed directly:

```text
signature: (device: 'Device' = None) -> None
CUDA device count/current: 1/0
omitted argument: PASS
integer current index 0: PASS
torch.device("cuda:0") after current-device initialization: PASS
CPU device: ValueError
invalid index 1: RuntimeError Invalid device argument
small allocation peak: 0 -> 16,384 B -> final allocated/reserved 0/0 B
```

The failure was an initialization-sensitive call site, not proof that this
Torch build never supports a CUDA device object. The implementation now calls
`current_device()`, normalizes and validates the requested CUDA device against
the available and current index, and passes the supported integer index to
`reset_peak_memory_stats()`. There is no multi-form fallback and exceptions are
not swallowed. This compatibility correction is remediation cycle 1; two
independent fix-forward cycles remain.

The first focused run exposed a FakeTorch-only normalization defect: an
already-normalized device object was passed back through the fake constructor.
Fix-forward cycle 2 now accepts objects with explicit `type` and `index`
attributes and applies the same CUDA/current-index validation directly. This
does not relax real-device admission. One fix-forward cycle remains.

## Teardown Remediation Result

The compatibility helper passed on the installed Windows Torch with integer
device index `0`, including a real 16,384-byte CUDA allocation and return to
`0/0` allocator bytes. The authorized production-equivalent sequence then
completed with retry zero.

```text
decision: H3_CUDA_FIXTURE_TEARDOWN_REMEDIATION_READY
cold allocated/reserved: 0 / 0 B
warm allocated/reserved: 8,519,680 / 25,165,824 B
warm active bytes: 8,519,680 B
warm fixture-owned CUDA/pinned: 0 / 0 B
warm Python CUDA tensors/storages: 0 / 0
warm worker/future/event/stream: 0 / 0 / 0 / 0
```

The nonzero warm allocation is classified separately as
`LAZY_CUDA_INITIALIZATION_BASELINE_MISMATCH`. It contains no fixture-owned or
Python-live CUDA tensor and is stable after representative initialization.
This classification is supported by the warm snapshot and all three planned
verification cycles; it is not an arbitrary tolerance.

| cycle | final allocated | final reserved | active | fixture CUDA/pinned | worker/future/event/stream |
|---|---:|---:|---:|---:|---:|
| verification 1 | 8,519,680 | 25,165,824 | 8,519,680 | 0 / 0 | 0 / 0 / 0 / 0 |
| verification 2 | 8,519,680 | 25,165,824 | 8,519,680 | 0 / 0 | 0 / 0 / 0 / 0 |
| verification 3 | 8,519,680 | 25,165,824 | 8,519,680 | 0 / 0 | 0 / 0 / 0 / 0 |

Allocated and reserved growth were both `[0, 0]`. The representative
verification peak was 205,137,920 allocated bytes and 239,075,328 reserved
bytes. Fixture-owned pinned peak was 48,269,348 bytes, consisting of the exact
48,269,312-byte BF16 host source plus 36 bytes of bounded metric output.

All four actual CUDA negative cases behaved correctly:

| retained owner | retained Gate | release Gate |
|---|---|---|
| CUDA tensor | FAIL | PASS |
| shared staging | FAIL | PASS |
| worker future CUDA result | FAIL | PASS |
| source cache entry | FAIL | PASS |

BF16 D2H/H2D bit identity, fingerprint, preliminary metric, exact metric,
packed-row mapping, threshold boundaries, and CPU/GPU bounded-reference error
all passed in warm-up and verification cycles. Maximum/mean reference error
remained `1.1920928955078125e-07` / `1.987791620194912e-08`. The focused suite
after the compatibility fix passed 14/14.

Internal remediation decision:

```text
H3_CUDA_FIXTURE_TEARDOWN_REMEDIATION_READY
```
