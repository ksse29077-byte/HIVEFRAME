# H3 Background Oracle Lineage Trace and Remediation

## Authorization and exact base

Issue #125 and Draft PR #126 track the one-time constitutional exception for
`H3_BACKGROUND_ORACLE_LINEAGE_TRACE_AND_REMEDIATION`. The branch starts from
exact Draft PR #124 head `d2077bb09794e5701549912ca1383965619ce451`.
The local and remote base matched and the worktree was clean. Existing PRs
were not changed.

The authorized runtime scope was one diagnostic H3 Standard Full Compute
probe after model-free and bounded CUDA admission. The probe was not a formal
CONTROL result. SELECTIVE, partial-Q, Attention omission, holdout admission,
Rust CachePlan execution, executor integration, and product changes remained
prohibited.

## Diagnostic implementation and Gate

Commit `822210f05a375b83932b6dd6ff2259e8ef6322c4` added a 512 KiB maximum,
metadata-only lineage capsule. It binds generation, workflow, model,
scheduler, and settings identity and records denoise ordinal, raw scheduler
timestep, model/Attention order, block/region, enqueue/completion/finalizer
order, and ring slot generation. It records no tensor, image, prompt, full
command, or private path.

The pre-H3 Gate passed 33 focused/adjacent tests and the production finalizer
bounded CUDA path. BF16 payload preservation, pinned nonblocking D2H,
timing-enabled event separation, reordered completion identity, cleanup, and
hot-path forced sync zero passed. The final stored preflight file SHA-256 is
`93272cfff6bb82265be3407fb61b27d8c16b8fdcaccda8c00b1abac87b61b09b`.

Admission then passed with external jobs, foreign runtimes/listeners, and port
8191 use all zero. The fixed input, prompt, workflow, model source, scheduler,
release PyO3, and Rust verification identities matched. Projected CUDA peak
was 12,514,625,897 bytes against 12,884,377,600 physical bytes, leaving
369,751,703 bytes.

## One diagnostic H3 trace

Exactly one Standard diagnostic submission reached H3 GPU execution. It used
seed 101, 864x480, 124 frames, 24 FPS, 20 steps, `res_multistep`, `simple`,
the fixed checkpoint/precision/offload behavior, Sage disabled, and Full
Compute only.

The first fail-closed capsule was written at Attention call ordinal 52,
denoise ordinal 1, block 2, region 0, enqueue sequence 33. The captured source
was denoise ordinal 0, so the source/current pair was a valid age-one pair.
Raw scheduler values were preserved separately and were not used as ordinal
arithmetic.

The physical and logical order was:

1. Sequences 1 through 30 were fully consumed for step 0, blocks 0 through 29.
2. Sequence 31 for step 1/block 0 completed D2H and entered CPU metric work,
   but its slot was not yet free.
3. Sequence 32 for step 1/block 1 occupied the second ring slot.
4. Sequence 33 for step 1/block 2 found slot 0 non-free and failed with
   `DUPLICATE_OR_MISSING_RECORD:RING_SLOT_NOT_FREE`.

The first 30 records were complete, completion/finalizer counters had reached
31, and two ring slots remained occupied. This rules out raw scheduler misuse,
reversed denoise direction, async completion reordering, stale source, and
cross-run identity as the initiating cause.

## Proven cause

The root cause is `DUPLICATE_OR_MISSING_RECORD`. CPU oracle metric processing
held both bounded pinned slots. The enqueue failure was a
`ControlV2EvidenceError(RuntimeError)`, which matched the parent H3 wrapper's
native Full Compute fallback tuple. The wrapper therefore continued model
compute without the rejected D2H record. A later step then observed an older
source and reported the misleading age mismatch retained by the prior run.

The actual trace capsule SHA-256 is
`bf791ee9a8c641bfb4f031f337d0be9caa5a510538fe9d85bbb76465e572ae13`.
The callback SHA-256 is
`3366e7d70404c869c3afa937c7775d82649dcbbfd9b7e056f4d8ad4695328d18`.

## Minimal remediation

`ControlV2EvidenceError` now derives directly from `Exception`, not
`RuntimeError`. V2 evidence-integrity failures therefore bypass the native
Full Compute fallback and fail closed before a missing record can be created.
`LineageDiagnosticError` and `LineageDiagnosticAbort` also derive from
`Exception`: they still bypass the wrapper's narrow fallback tuple, while
ComfyUI can now emit its normal terminal error event.

The runner now finalizes GPU-start counters from observed progress even when
the websocket exits through an error. No age threshold, scheduler semantics,
ring size, cache budget, metric algorithm, Attention path, ABI, or Rust policy
changed.

The anonymized actual-trace fixture preserves fully-consumed sequence 30,
physical completion/finalizer 31, occupied sequences 31 and 32, and rejected
sequence 33. Replay proves age one at failure, two occupied slots, immediate
fail-closed action, no missing record, and prevention of the later false age
mismatch. Its deterministic replay digest is
`f3af6e841992b9d5ae0e05cda75eb6cb611747c8c3bbf121451798fae68e6811`.

## Runtime terminal recovery

The diagnostic originally used a `BaseException`, which bypassed both the H3
fallback and ComfyUI's terminal-event handler. The capsule was already safe,
but the websocket waited with a stale running queue entry. A normal
`/interrupt` did not produce a terminal event. No second submission occurred.

Before shutdown, recovery revalidated the original runner, launcher,
runtime/listener, run identity, PID creation times, executable identity,
dedicated paths, and port binding. Only the verified launcher/runtime Python
tree was stopped. The console helper exited naturally; direct console-helper
and foreign-process termination counts were zero. Port/listener/runtime counts
returned to zero and GPU memory returned to the 10 MiB baseline. The shutdown
result SHA-256 is
`e583e1fc7b04a79fe62ddf752dc95f931a61ecade4624cc53b18d3a603bec092`.
The new `Exception` contract removes this terminal-event defect for subsequent
runs.

## Counters and decision

- diagnostic H3 submission/GPU start: 1/1
- valid CONTROL result and completed Generation: 0/0
- retry and fallback Generation: 0/0
- SELECTIVE, partial-Q, Attention omission: 0/0/0
- holdout admission and Rust CachePlan calls: 0/0
- foreign process and direct console-helper termination: 0/0

The private adjudication receipt binds the capsule, callback, original runner
receipt, shutdown ownership/result, and final CUDA preflight. Its SHA-256 is
`6dd909d76b1d86da5571ab6b085671605fe8f8ded7d62c5d9b31d0257516b19d`.

Final decision:

```text
H3_BACKGROUND_ORACLE_LINEAGE_TRACE_CAPTURED_AND_REMEDIATED_READY_FOR_CONTROL
```

This decision means the lineage failure is now truthful and fail-closed. It
does not claim that the two-slot CPU oracle has enough throughput to complete
a formal CONTROL. A formal CONTROL requires separate authorization and was not
started. Executor integration was not started.
