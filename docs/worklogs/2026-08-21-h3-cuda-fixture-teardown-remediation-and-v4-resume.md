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
