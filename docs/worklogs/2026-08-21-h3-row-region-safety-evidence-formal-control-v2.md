# H3 Row Region Safety Evidence Formal CONTROL V2

## Authorization and exact base

Issue #129 tracks the one-time constitutional exception for
`H3_ROW_REGION_SAFETY_EVIDENCE_FORMAL_CONTROL_V2`. The branch starts from
exact Draft PR #128 head
`f91c85504d75be4b17e5049a335b3e47fc3c4621`. Local HEAD, upstream HEAD,
remote PR head, and a clean worktree matched before branch creation. The
ancestry includes the PR #126 lineage fail-closed remediation, PR #122 CUDA
Event remediation, and PR #118 process-ownership contract.

The authorized execution is one H3 Standard Full Compute Formal CONTROL with
the RAM-admitted four-slot CPU oracle ring. Complete evidence may then enter
one Rust CachePlan V2 compile and deterministic offline replay. SELECTIVE,
partial-Q, Attention omission, executor integration, product wiring, LTX,
Wan, Installer work, retry, and automatic follow-up generation are forbidden.

## Execution counters before admission

```text
CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=2
CURRENT_TASK_FORMAL_CONTROL_SUBMISSIONS=0
CURRENT_TASK_RETRY_COUNT=0
DIAGNOSTIC_SUBMISSIONS=1
```

The two previous Formal CONTROL submissions failed during finalization and
ring handling. The separate lineage diagnostic submission is not counted as a
Formal CONTROL.

## Pre-submit evidence Gate hardening

Before any runtime or model activity, the one-shot runner was tightened to
make the approved Gate machine-checkable. The receipt now requires the exact
four-slot allocation, actual slot bytes, all initial slots FREE, zero final
backlog, all final slots FREE, bounded ring high-water, zero backpressure and
nonfinite evidence, and exact per-step/per-block/per-region cardinality. It
also records producer and worker rates, CPU-oracle drain, evidence
finalization, and Rust live/replay durations.

Focused model-free tests passed 26/26. Python bytecode compilation and
`git diff --check` also passed. The branch was committed and pushed before
Admission so the worktree was clean.

## Admission result

The first model-free CUDA oracle preflight failed closed before H3 model load,
runtime start, or workflow submission:

```text
decision=H3_ROW_REGION_SAFETY_CONTROL_V2_ORACLE_PREFLIGHT_FAILED
error_type=ControlV2EvidenceError
error_message=event finalizer received an invalid D2H slot
```

PR #128 changed the production slot contract to accept only
`D2H_IN_FLIGHT`, but the bounded preflight fixture still constructs its CUDA
slots with the retired `PENDING` state. The production finalizer correctly
rejected that state. This is a preflight-fixture contract mismatch, not a
memory, model, queue, or generation failure. The mismatch was not repaired or
re-run under this authorization because the instruction requires immediate
termination on a pre-submit Gate failure.

The private model-free receipt is stored outside the repository. Its SHA-256
is `99f392ccad0dcf9c87b6e23a9aebc3c1ea562e7f4167b01df4fa2426b81f8f5e`.
It records H3 model load, Generation, CONTROL submission, SELECTIVE,
partial-Q, and Attention omission as zero.

Release PyO3/Rust verification, dedicated runtime start, post-start memory and
ownership admission, Formal CONTROL, holdout evidence, Rust live compile and
replay, MP4 retrieval, and owned-runtime shutdown were not entered after the
blocking Gate.

## Final counters

```text
CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=2
CURRENT_TASK_FORMAL_CONTROL_SUBMISSIONS=0
CURRENT_TASK_RETRY_COUNT=0
DIAGNOSTIC_SUBMISSIONS=1
submission/GPU start/completion=0/0/0
```

No previous failure was hidden or reclassified. The required cumulative value
of three applies only after an admitted third Formal CONTROL submission; this
task did not reach submission.

## Decision

```text
H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED
```

Executor integration, SELECTIVE, partial-Q, Attention omission, product
wiring, LTX, Wan, Installer work, and any additional H3 Generation were not
started. The one-time exception ends at this Gate result.

## Authorized procedure

1. Revalidate the immutable P1-A2 Standard profile and all repository,
   ownership, queue, memory, ring, CUDA, cardinality, and runtime Admission
   Gates.
2. If and only if every Gate passes, submit exactly one backend workflow.
3. Admit only a complete 600-enqueue/480-evidence batch.
4. Compile and replay Rust CachePlan V2 only after successful Generation and
   evidence finalization.
5. Verify output integrity and shut down only the owned runtime tree.
6. Record READY, ADMISSION_BLOCKED, or FAILED and stop without starting the
   executor integration.

Procedure stopped at step 1; steps 2 through 6 were not executed.
