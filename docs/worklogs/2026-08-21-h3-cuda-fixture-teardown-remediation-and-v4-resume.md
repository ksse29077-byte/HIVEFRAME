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

## V4 Full Preflight Continuation

The current release PyO3 extension was rebuilt and loaded from the exact
continuation branch. The real Rust CachePlan V2 round trip, panic containment,
and three-percent fixture passed. The focused release-extension set passed
29/29 with skip zero, and the complete adjacent H3 regression set passed 88/88
with skip zero. Model-free exact, burst, H2D-latency, oracle-latency, and
combined stress replays all completed 199 records with no backlog, overwrite,
drop, duplicate, stale source, or invalid transition.

The frozen preflight evidence was:

```text
inventory digest:             8375783b8afdb3257699a310e9b0faf0d4d152a1dcc31bc4a6d1ef9986a11ebc
exact holdout records:        199
planned Q rows/full Q rows:   463,869 / 15,424,000
planned Q reduction:          3.007449429460581%
source capture D2H:           10,040,016,896 B
candidate source H2D:         9,605,593,088 B
metadata D2H:                 50,944 B
total tensor transfer:        19,645,609,984 B
resident host source:         627,501,056 B
shared GPU staging:           48,269,312 B
projected V4 peak VRAM:       12,562,895,209 B
projected VRAM headroom:      321,482,391 B
available RAM:                46,998,458,368 B
RAM after resident source:    46,370,957,312 B
```

The memory and transfer admissions passed. `cargo fmt --all -- --check` also
passed. The first strict clippy run exposed two pre-existing Rust 1.97
`manual_div_ceil` findings in `locality.rs`. The final bounded remediation
cycle replaced those two expressions with the equivalent stable integer
`div_ceil` operation. The next strict clippy run advanced to a separate
pre-existing `too_many_arguments` finding on the eight-argument PyO3
`run_candidate` function in `crates/hive-retina-python/src/lib.rs:70`.

At that point all three authorized remediation cycles were consumed:

1. Windows Torch peak-reset compatibility.
2. FakeTorch device-object normalization.
3. Rust 1.97 manual-div-ceil compatibility.

The instruction requires termination when the budget is exhausted before the
full preflight passes. The PyO3 public function was not refactored or lint-
suppressed. Workspace test/release build, Formal CONTROL Admission, runtime
start, model load, Generation, holdout Rust compile/replay, and output analysis
were not entered after the failed Gate.

```text
current-task submission/GPU start/completion: 0/0/0
current-task retry/fallback:                   0/0
SELECTIVE/partial-Q/Attention omission:        0/0/0
cumulative prior Formal CONTROL submissions:  3
H3_V4_INFRASTRUCTURE_REMEDIATION_BUDGET_EXHAUSTED
```

## Approved Baseline Lint Resolution

The continuation approval reclassified a pre-existing static warning as lint
hygiene rather than a fourth V4 functional remediation. Exact base
`cabe03127ff1e7ee1503861ca62515e3dd40afce` contains the same eight-argument
`run_candidate` function, and PR #138 changes did not alter that file or its
argument count. A detached base worktree reproduced the strict workspace's
older `manual_div_ceil` findings first; an isolated no-dependency PyO3 Clippy
run then reproduced `clippy::too_many_arguments` at the same function. The
classification is therefore:

```text
BASELINE_PREEXISTING_ABI_LINT
```

`run_candidate` is a directly registered `#[pyfunction]`. A function-scoped
allow with the reason `PyO3 ABI boundary; argument order and cardinality are
contract-bound.` was added. No function body, Python argument, argument order,
ABI structure, or crate/workspace lint policy changed.

Verification after the scoped resolution:

```text
cargo fmt:                         PASS
strict workspace Clippy:           PASS, new lint 0
Rust workspace tests:              50 PASS
release PyO3 focused tests:         29 PASS, skip 0
release PyO3 load:                  PASS
Python signature before/after:      identical
CachePlan ABI before/after:         2 / 2
old release SHA-256:                0758bba92c7f0f60e9f85a90fee30582a3cee758b567cb8326ef567a3e86d3b5
new release SHA-256:                60e0a1cf58a772841465ff622bf708ab2ce29485d75c12013bae56c1214dd711
Formal CONTROL submission:          0
```

## Formal CONTROL Admission Result

The lint-resolution commit was pushed before Admission so the local worktree,
local HEAD, and Draft PR #138 head were clean and identical at
`27bfcb02269d43e1136efafde1407a7874b5820e`. The frozen inventory digest and
release binary identity matched the verified preflight. Resource observations
were also admissible: RTX 3060 use was 10 MiB at 0%, projected V4 headroom was
321,482,391 bytes, available system RAM was 46,599,868,416 bytes, port 8191 had
zero listeners, and no ComfyUI Python candidate was running.

The structural V4 production Gate did not pass. The repository contains the
V4 model-free contract and bounded CUDA fixture, but no V4 runtime controller,
ComfyUI node, one-shot Formal CONTROL runner, or callback that can emit the
frozen 199-record candidate-only-H2D exact-GPU-oracle holdout. The earlier V4
worklog explicitly records that these production components were not started
after the original teardown failure, and the approved teardown/lint changes do
not add them.

The existing V2 runner cannot be substituted. It uses the V2 controller,
candidate set, D2H-only oracle contract, cardinality, settings digest, node
class, and holdout label. A V2 Generation would therefore be a fourth Formal
CONTROL submission without proving the authorized V4 product question.

The Gate failed before runtime start. External queue query, Process Ownership
V2 finalization, an approved 8191 listener, H3 model load, workflow submission,
holdout collection, Rust live/replay, video output, and production net-saving
calculation were not entered. No follow-up implementation or remediation was
created automatically.

```text
current-task submission/GPU start/completion: 0/0/0
current-task retry/fallback:                   0/0
cumulative Formal CONTROL submissions:        3
SELECTIVE/partial-Q/Attention omission:        0/0/0
H3_V4_CLOSE_THE_LOOP_ADMISSION_BLOCKED
```

## V4 Observer Runtime Integration and Formal Admission

The approved continuation started from exact clean PR #138 head
`0aa869414b3096cecd8fa2ed016391d8937204b0`. It added a generation-scoped V4
controller, an observation-only callback after real H3 exact Full Attention,
an isolated CONTROL-only ComfyUI node root, indexed exact-GPU metric helpers,
and a one-shot runner. The callback preserves the Full Attention output and
keeps SELECTIVE, partial-Q, cache omission, and Attention omission disabled.
The isolated node root prevents the V2 all-candidate pinned ring from loading.

Verification before Admission:

```text
focused Python/release PyO3 tests: 53 PASS
release PyO3 fixed subset:         29 PASS, skip 0
Python compile:                    PASS
cargo fmt:                         PASS
strict workspace Clippy:           PASS
Rust workspace tests:              50 PASS
release workspace build:           PASS
```

The broad Python discovery run executed 609 tests, with 35 errors caused by
the installed Comfy Python losing access to newly created temporary
directories and one pre-existing C0 knowledge-status mismatch; 16 tests were
skipped. These failures were not changed or represented as a full-suite pass.

The final implementation commits were `8bb44d498af14d84876390a5738a29595ef55770`,
`41a1febe2a57f207347dba773716f269ccc3b21d`, and
`310e76a9f07ed7fff9db00264e33e76c87993d45`. Local, origin, and PR #138
actually matched the last SHA with a clean worktree. The one-shot runner was
mistakenly invoked with expected SHA
`310e76a8c5f66e716e24fcf9616a3c83ab5c7580`. Consequently only
`head_exact` and `remote_head_exact` failed. Per the fixed Admission failure
rule, the runner did not automatically run again.

Every non-SHA pre-start check passed. The CUDA fixture passed, P1-A2 receipt,
prompt, input, workflow, model source, release PyO3, inventory, transfer,
queue, port, process ownership, RAM, and VRAM checks matched. Measured and
projected admission values were:

```text
baseline GPU use:                  10,485,760 B
physical VRAM:                     12,884,377,600 B
projected V4 peak VRAM:            12,562,895,209 B
projected VRAM headroom:           321,482,391 B
available RAM:                     47,036,989,440 B
resident pinned host source:       627,501,056 B
RAM after host source:             46,409,488,384 B
source capture D2H:                10,040,016,896 B
candidate source H2D:              9,605,593,088 B
expected tensor transfer:          19,645,609,984 B
frozen inventory:                  199 records
planned Q reference:               3.007449429460581%
```

Runtime start, model load, `/prompt`, GPU generation, callback holdout, Rust
live compile, Rust replay, video output, and production-net timing were not
entered. The private fail-closed receipt is outside the repository under the
approved local HIVEFRAME evidence root.

```text
current-task submission/GPU start/completion: 0/0/0
current-task retry/fallback:                   0/0
runtime/model load:                            0/0
Rust live/replay:                              0/0
SELECTIVE/partial-Q/Attention omission:        0/0/0
cumulative Formal CONTROL submissions:        3
H3_V4_FORMAL_CONTROL_ADMISSION_BLOCKED
```
