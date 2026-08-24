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

## Corrected Administrative Recheck and One-Shot Formal CONTROL

The approved SHA was fixed as the full 40-character value
`bbf81a0469c0af7c858a7e486dca89eb83f46b32`. Authorized, local, origin, and
Draft PR #138 heads matched exactly and the worktree was clean. The previous
bad `expected_head` was classified as `OPERATOR_INPUT_ERROR`; this pass was an
`ADMINISTRATIVE_ADMISSION_RECHECK`, not a Formal CONTROL retry. The release
PyO3 extension was rebuilt from the authorized head, loaded successfully, and
passed its fixed 29-test subset with skip zero. No V4 runtime source changed
between the previously verified implementation head and this execution head.

All pre-start gates passed. The dedicated runtime admitted 13 page-locked BF16
source slots (`627,501,056 B`), a page-locked metric buffer (`7,164 B`), and
one shared GPU staging allocation (`48,269,312 B`). Available system RAM after
the pinned allocations was `44,388,995,072 B`. The frozen inventory and
profile digests remained respectively
`8375783b8afdb3257699a310e9b0faf0d4d152a1dcc31bc4a6d1ef9986a11ebc` and
`99de39e52efbf92c3238c4d0580fccf412d3822b4e541e2025a77cda343d7f7d`.

The runner submitted exactly one `/prompt`, bringing the cumulative Formal
CONTROL submission count to four. H3 entered GPU execution, initialized the
model, and executed exact Full Attention only. During the first target
admission, after 13 source captures and before any candidate H2D or exact
oracle record, the observer failed closed with:

```text
V4ObserverAbort: V4 candidate source lineage changed
```

The callback receipt proves the following bounded partial execution:

```text
lifecycle:                             created -> admitted -> observing -> aborted
submission/GPU start/completion:       1/1/0
retry/fallback:                        0/0
model forwards:                        4
Full Attention calls:                  151 of expected 1,000
partial-Q/SELECTIVE/Attention omission: 0/0/0
output mutation:                       0
source captures/source D2H:            13 / 627,501,056 B
candidate source H2D:                  0 B
C2 auxiliary telemetry D2H:            576 B
total observed device transfer:        627,501,632 B
Rust policy metadata:                  2,448 B
exact completed records:               0
Rust tensor bytes:                     0
hot-path forced CUDA sync:             0
```

The failure receipt records the lineage classifier but not the compared
actual and expected digests, so the exact changed identity field is not
claimed. The 199-record holdout, confusion matrix, measured holdout planned-Q
reduction, Rust live/replay digests, output integrity, exact terminal timings,
exact peak VRAM, and production net saving are therefore unavailable rather
than inferred from preflight fixtures. Static planned Q remains the preflight
reference `3.007449429460581%`; it is not a Formal CONTROL result.

The live NVIDIA spot sample reached at least `9,333 MiB` used on a physical
`12,288 MiB` device, leaving at most `2,955 MiB` at that sample. The exact peak
was not persisted because the abort escaped ComfyUI's ordinary exception path
and prevented a terminal websocket event. The callback receipt was preserved,
the hung runner was stopped without a second prompt, and only the verified
owned Python tree was terminated. External termination and direct
`conhost.exe` termination remained zero. Post-stop related runner/ComfyUI
processes and port-8191 listeners were zero, and NVIDIA usage returned to
`10 MiB`.

Private evidence is stored under run ID
`h3-v4-formal-control-20260821-2`. The separate manual finalization receipt
binds the callback, node admission, and runtime log by SHA-256 without adding
private absolute paths to repository evidence.

```text
H3_V4_FORMAL_CONTROL_FAILED
```

No second H3 submission, remediation, SELECTIVE execution, executor
integration, or product work was started.

## V4 Lineage Diagnostic Continuation

The continuation started from exact clean Draft PR #138 head
`ace5be83f1ddecdd71c002c98109769c90ae2969`. Authorized, local, origin, and
PR heads matched. The existing run `h3-v4-formal-control-20260821-2` callback,
node admission, runtime log, manual finalization, their SHA-256 values, and the
earlier worklog and Knowledge entries were not changed or reconstructed.

The source-readonly audit established the frozen order mechanically:

```text
20 denoise ordinals x 50 blocks:       1,000 Attention calls
source capture steps 1..16 x 13:       208 captures
frozen target candidates:              199
expected first target Attention call:  101
```

A model-free replay using the fixed 20-step canonical scheduler trace ran the
complete order with `1,000` calls, `208` captures, `199` target admissions,
and zero lineage mismatch, overwrite, or incomplete source. This is a runtime
event-contract test, not H3 holdout evidence.

The retained failure prefix is `151` Full Attention calls, `13` captures, and
zero exact records. It occurs exactly 50 Attention calls later than the frozen
first target. The frozen order therefore does not reproduce the previous
failure. The old receipt does not contain the expected/actual operands, source
step, target step, or candidate key needed to explain that extra 50-call gap.
No past value was inferred or appended to the immutable receipt.

The only evidence-supported classification remains:

```text
root cause: UNKNOWN
H3_V4_LINEAGE_CONTRACT_BLOCKED
```

Because the required reproduction and non-UNKNOWN root-cause Gates failed,
no functional lineage fix was made. The legacy digest comparison, inventory,
thresholds, source storage, transfer limits, Attention output, and execution
paths remain unchanged.

The authorized diagnostic-only change adds a bounded component receipt for a
future mismatch. It records common generation/profile/model/inventory/layout
digests; source ordinal and canonical scheduler value; block, region, slot,
capture sequence and event digest; shape, dtype, and completion state; target
ordinal, scheduler value, candidate key, and sequence; and the component
mismatch mask and first mismatch. It stores no tensor payload, prompt, input,
or private path. The comparison still aborts before candidate H2D and exact
oracle work. Incomplete source admission now produces the same bounded
diagnostic schema.

Focused model-free verification passed 25/25 with skip zero. It covers the
full 1,000-call trace and generation, profile, model, ordinal, scheduler,
block, region, slot/capture sequence, completion, inventory, and layout
negative cases. Python compilation and `git diff --check` passed. The
candidate-H2D and exact-oracle calls remain after the fail-closed lineage Gate
in source order.

The failed reproduction Gate stopped the task before CUDA fixture execution,
release PyO3, adjacent H3 suites, Rust workspace validation, runtime Admission,
model load, or Formal CONTROL. This is a deliberate Gate stop, not a test pass
claim for unentered stages.

```text
current-task runtime/model load:                 0/0
current-task submission/GPU start/completion:    0/0/0
current-task retry/fallback:                     0/0
cumulative Formal CONTROL submissions:          4
CUDA exact-oracle fixture executions:            0
Rust live/replay:                                0/0
SELECTIVE/partial-Q/Attention omission:           0/0/0
output mutation:                                 0
```

No Formal CONTROL, minimal cause fix, V5 work, evidence expansion, executor
integration, or product work was started.

## Instrumented Live Lineage Formal CONTROL

The approved continuation started from exact clean Draft PR #138 head
`c9df8e9789acdce978af5bd26ac5fed04ffb9c6d`. The diagnostic-only diff from
`ace5be83f1ddecdd71c002c98109769c90ae2969` remained limited to lineage
receipt fields, tests, and documentation. The legacy lineage comparison,
inventory, thresholds, planned-Q math, source and transfer budgets, CachePlan
ABI, and execution behavior were not relaxed.

The installed ComfyUI executor catches `Exception` and emits
`execution_error`, while `V4ObserverAbort` previously inherited directly from
`BaseException`. A pre-run model-free reproduction proved that the abort could
escape the terminal path. The minimal fix changed it to a `RuntimeError`,
added terminal and cleanup regression coverage, and was committed and pushed
as `9dff881c660758ddc2865ff0ec5ed4229857fa07`. The existing single-PID and
launcher-child ownership behavior was unchanged.

Pre-run verification passed 62 focused and adjacent Python tests, including
the 1,000-call/199-target trace, 11 lineage negative cases, abort-to-terminal,
runner source integration, and process ownership. The release PyO3 ABI V2
subset passed 8 tests with skip zero, Python compilation and diff checks
passed, and the loaded extension SHA-256 remained
`60e0a1cf58a772841465ff622bf708ab2ce29485d75c12013bae56c1214dd711`.
Rust and CUDA sources were unchanged, so their prior full workspace and
bounded teardown receipts were reused rather than rerun.

All Git, fixed-profile, idle-queue, ownership, source, memory, transfer, and
CUDA preflight Admission checks passed. The dedicated runtime admitted 13
page-locked BF16 source slots (`627,501,056 B`), one `7,164 B` page-locked
metric buffer, and one `48,269,312 B` shared GPU staging allocation. The
runner submitted exactly one prompt from execution head
`9dff881c660758ddc2865ff0ec5ed4229857fa07`; cumulative Formal CONTROL
submissions increased from four to five, with retry and fallback both zero.

The Full Compute path executed all 20 model forwards and all 1,000 expected
Full Attention calls. SELECTIVE, partial-Q, Attention omission, cache reuse
omission, and output mutation remained zero. During final holdout admission,
the diagnostic Gate captured an exact live mismatch and failed closed before
candidate H2D, exact oracle work, Rust admission, decode, or MP4 output:

```text
classification:                  SOURCE_SLOT_REUSE_OR_OVERWRITE
first mismatch field:            source_step_ordinal
actual source:                   step 1, block 3, region 0, slot 3, sequence 4
expected source:                 step 16, block 3, region 0, slot 3, sequence 199
target:                          step 17, block 3, region 0, sequence 199
mismatched components:           source step, scheduler, capture sequence,
                                 capture event ID, legacy lineage digest
shape/dtype/completion:           [3367, 7168] / BF16 / EVENT_RECORDED (matched)
generation/profile/model/inventory/layout: matched
```

The bounded diagnostic file is `105,239 B`, below the 1 MiB cap, and contains
no tensor, prompt, input payload, or private path. The observed source D2H was
`627,501,056 B`, C2 scalar D2H was `3,840 B`, candidate H2D was zero, and total
observed device transfer was `627,504,896 B`. Rust tensor bytes and forced
hot-path CUDA synchronization were zero.

The websocket terminal was automatically reported as `execution_error`; the
callback and private receipts were finalized without manual finalization, and
the runner exited after `671.311306 s`. The sampler node was observed for
`604.296236 s`, submit-to-terminal was `645.916571 s`, and bounded C2 observer
overhead was `0.041647456 s`. Exact oracle and production-net timing are not
available because exact records remained zero. Sampled NVIDIA peak VRAM was
`11,885,608,960 B`, leaving `998,768,640 B` against the frozen physical-VRAM
value.

The immediate shutdown receipt marked only its GPU-baseline sample false at
`165 MiB`; ownership shutdown itself passed. A delayed read-only cleanup check
found the owned Python and console-helper PIDs absent, port 8191 listeners
zero, GPU use back at `10 MiB` and 0%, external process termination zero, and
direct `conhost.exe` termination zero. No MP4 was produced, so output
integrity, the 199-record confusion matrix, false-safe, actual planned-Q
reduction, Rust live/replay digests, and production savings are unavailable.

```text
submission/GPU start/completion:       1/1/0
Full Attention actual/expected:        1,000/1,000
exact holdout records:                 0/199
retry/fallback:                        0/0
SELECTIVE/partial-Q/Attention omission: 0/0/0
H3_V4_LIVE_LINEAGE_CAUSE_CAPTURED
```

This is not a successful Formal CONTROL and does not authorize executor or
SELECTIVE integration. No second H3 submission, lineage fix, V5 work, or
automatic follow-up was started.

## Source Slot Lifecycle Remediation And Economics Gate

The approved continuation began from exact clean Draft PR #138 head
`fbf41c9fa869f5b0407410b041c791878e0bf5fb`. The live step-1/sequence-4 slot
retained while step-16/sequence-199 was requested is now code-proven as
`TARGET_PROCESSING_DEFERRED`. `V4ObserverAbort` inherited `RuntimeError`; the
parent A3-G1 controller caught that type in its pre-mutation native fallback,
so target processing failed without releasing the READY source. Subsequent
capture refresh then rejected the unread slot and the stale identity survived.

The minimal correction makes the observer abort bypass that generic fallback
while remaining an ordinary `Exception` at the ComfyUI terminal boundary. The
13 existing slots now enforce the explicit lifecycle `EMPTY -> CAPTURING ->
READY -> CONSUMING -> RELEASED -> EMPTY`, a monotonic per-slot version, and
exact generation, scheduler, block, region, capture, shape, dtype, and
device/layout identity. A stale step-1/sequence-4 slot cannot satisfy the
step-16/sequence-199 request and fails closed without relabeling.

The full model-free order replay passed with 1,000 calls, 208 captures, 199
target lookups, 199 consumes, 199 releases, and peak live slots 13. Lineage
mismatch, overwrite, duplicate consume, incomplete admission, stale admission,
and unread overwrite were all zero.

One model-free CUDA rolling fixture also passed. It used the fixed 13 pinned
slots and one 48,269,312-byte staging tensor, transferred 10,040,016,896 bytes
D2H and 9,605,593,088 candidate-only bytes H2D, preserved BF16 bits, ran the
exact GPU metric path for all 199 consumes, and completed both normal and
planned-abort cleanup.
Allocator allocated/reserved values returned to the warm baseline, live
fixture tensor references were zero, and retry was zero.

The prior ACL regression failed only inside the managed sandbox because
Python-created temporary directories received unusable ACLs. The unchanged
original test passed outside that sandbox in 0.004 seconds and is classified
`TEST_ENVIRONMENT_ONLY`; no runtime or security Gate changed.

Verification passed 36 focused Python tests, 110 adjacent H3 tests, all 50 Rust
workspace tests, and the four required release PyO3 tests with skip zero.
`cargo fmt`, strict workspace Clippy, workspace release build, release extension
load, ABI V2, Rust tensor bytes zero, and maximum one Rust call per generation
all passed. The release extension SHA-256 remained
`60e0a1cf58a772841465ff622bf708ab2ce29485d75c12013bae56c1214dd711`.

The Product Economics Gate did not pass. P1-A2 running-to-terminal and the V4
sampler-node boundary are `NOT_COMPARABLE`. The valid C4-S0 same-profile sampler
baseline is 488.8473197 seconds and its global Attention mixing span is
343.2285699 seconds. Applying the 3.007449% planned Q ratio to that entire span
gives an optimistic upper bound of 10.3224257 seconds, not a speedup claim.
After the known 0.041647456-second C2 cost, the all-unknown-costs-equal-zero
counterfactual would be 10.2807782 seconds or 2.1031%.

That counterfactual is not admissible. Partial-kernel launch, representative
gather, reconstruction/scatter, cache read/write and identity guards,
per-generation GPU plan materialization, and Rust live-plan compile time are
unmeasured. Thus predicted net seconds and predicted E2E percentage are both
unknown, `unknown_runtime_cost_zero` is false, and the required >=1% Gate
cannot be established.

No dedicated runtime was started, no H3 model was loaded, and no prompt was
submitted. Current-task submission/GPU start/completion is `0/0/0`, cumulative
Formal CONTROL submissions remain five, retry/fallback is `0/0`, and
SELECTIVE/partial-Q/Attention omission/output mutation is `0/0/0/0`.

```text
H3_V4_ECONOMICS_NOT_VIABLE
```

The slot defect is remediated and bounded, but this does not establish that the
compound-eye path is commercially faster. Formal CONTROL and executor work
remain unauthorized and were not started automatically.

## Production-Shaped Executor Hot Path Economics And Conditional Formal Control

The approved PR #138 continuation began at exact clean head
`a4bb919700026f5d1faa43b4f9f7e1a366cad844`. It added a production-shaped V4
Executor Adapter and benchmark using the installed Standard H3
`attention_pytorch` backend, Sage disabled, and model-free synthetic BF16
tensors at the real H3 shape: 15,424 rows, 56 heads, head dimension 128, and
output width 7,168. No H3 generation was used to establish executor economics.

The adapter decodes the release Rust CachePlan ABI V2, validates runtime
profile/context/lineage/shape/dtype/device/cache identity, and enforces Full XOR
Selective execution. Its selective branch computes 13,093 rows and reuses
2,331 rows; all invalid or vetoed paths fail closed through the same exact Full
callable. Reconstruction was bit-exact when the cache contained the identical
omitted rows, and forced fallback matched the Full reference exactly.

Seven measured CUDA samples after two warmups produced these medians:

```text
Full reference:                 269.839355 ms
reduced-Q Attention:            229.707779 ms
selective executor hot path:    232.589127 ms
forced exact fallback:          269.876221 ms
Rust plan decode:                 0.225184 ms
representative gather:            1.165312 ms
reconstruction scatter:           1.659904 ms
cache read/write:                  0.212992 / 0.306176 ms
```

The previously unknown validation, plan materialization/application, launch,
allocator, explicit-sync, cache guard, and release Rust compilation costs were
also measured. Unknown runtime costs are now zero. The frozen 1,000-call
schedule contains 199 candidate targets, 208 source writes, and 463,869 omitted
rows of 15,424,000, or 3.007449%. Net projected savings are 7.190806 seconds
(1.470972%) optimistic, 7.000464 seconds (1.432035%) at the median, and
6.923862 seconds (1.416365%) conservatively. Conservative savings are positive,
median savings exceed 1%, p95 does not regress, and memory/fallback/pipeline
checks pass. Peak CUDA allocated/reserved memory was 3,223,861,760 /
3,948,937,216 bytes and cleanup returned both to zero.

```text
H3_V4_HOT_PATH_ECONOMICS_VIABLE
```

This result only clears the conditional Formal CONTROL Gate. It does not
authorize selective H3 generation and represents about 1.43% projected sampler
savings, so V4 remains an auxiliary optimization rather than the main path to
the product's two-minute target.

One and only one approved Full Compute Formal CONTROL was then submitted from
head `4fdb82dea0f4c4014dd85409fa8403611443abd7`. All pre-start and post-start
Admission checks passed. The run started H3 GPU work but failed closed on the
151st Full Attention call, at target step 3, before any exact holdout record:

```text
V4 candidate source is incomplete:
slot=0 source_step=2 target_step=3 block=0 region=0
```

At failure, 13 slots had been captured and consumed, none had been released,
and all were still `CONSUMING`. The requested step-2/version-2/capture-14 source
was not complete while the retained slot still described
step-1/version-1/capture-1. The generic diagnostic therefore reports a lineage
mismatch, but the direct runtime failure is an incomplete source-slot lifecycle
before consumption. No functional correction is made in this task.

Submission/GPU start/completion was `1/1/0`; cumulative Formal submissions are
six. Model forwards were 4, Full Attention calls were 151, and exact records,
Rust live/replay, Selective, partial-Q, Attention omission, output mutation,
retry, and fallback were all zero. The terminal was `execution_error`, no MP4
was produced, and output integrity is unavailable. Runner wall time was
194.865485 seconds. Sampled Comfy VRAM peaked at 12,037,813,671 bytes and
NVIDIA-used memory at 11,919,163,392 bytes.

The verified owned runtime tree stopped without terminating external processes.
The immediate shutdown sample still observed 165 MiB and therefore failed only
its instant GPU-baseline check; a later read-only check confirmed all owned
processes absent, port 8191 closed, and GPU memory restored to 10 MiB. No retry,
repair, second generation, executor integration, or follow-up research was
started.

```text
H3_V4_FORMAL_CONTROL_FAILED
```

The hot path has measurable auxiliary economics, but its production evidence
lifecycle is not safe enough to proceed. Actual selective H3 execution remains
unauthorized.
