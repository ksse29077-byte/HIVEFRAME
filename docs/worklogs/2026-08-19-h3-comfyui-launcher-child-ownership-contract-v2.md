# H3 ComfyUI Launcher Child Ownership Contract V2

Date: 2026-08-19  
Issue: #115  
Branch: `codex/h3-comfyui-launcher-child-ownership-contract-v2`  
Base: Draft PR #114 head `47609d1cf1b03b3ff56496a4d64c438d4e7976a0`  
Decision: `H3_COMFYUI_LAUNCHER_CHILD_OWNERSHIP_CONTRACT_V2_BLOCKED`

## Scope

This one-time exception allowed only a Windows ComfyUI process-tree ownership
contract, focused model-free tests, and one dedicated model-free runtime
lifecycle. H3 model loading, workflow submission, Generation, CONTROL,
SELECTIVE, partial-Q, and Attention omission were prohibited and remained
unexecuted. Existing PRs were not changed.

## Implemented contract

Ownership receipt schema V3 separates `launcher_pid`, `runtime_pid`, and
`listener_pid`. A single-PID runtime remains valid, while a listener may also
be the launcher's direct child or a verified deeper descendant.

Admission binds all runtime candidates to:

- a launcher-rooted process tree;
- PID plus process creation time;
- one non-reused parent chain from listener/runtime to launcher;
- the same run ID component and dedicated config/input/output/temp/user paths;
- exact Python argv, `main.py`, loopback host, port, and disabled auto-launch;
- exactly one listener inside the approved tree;
- zero matching ComfyUI runtime candidates outside that tree.

Unexpected process-tree children, foreign listeners, PID reuse, path mismatch,
same-port takeover, and foreign runtime candidates fail closed. Shutdown can
target only creation-time-bound descendants from a passing receipt; the
backend-owned `Popen` launcher remains the only root the backend may stop.

The existing CONTROL V2 teardown call site was adapted to the role-specific
receipt and verified-descendant shutdown helper. No CONTROL was executed.

## Focused verification

The ownership and unchanged CONTROL V2 structure suite passed 25/25. It
includes the observed Windows two-PID launcher/direct-child fixture, the
legacy single-PID fixture, a separate descendant listener role, and negative
fixtures for unrelated child, foreign listener, PID reuse, path mismatch,
same-port takeover, broken lineage, and foreign runtime. A structural test
confirms the lifecycle probe has no `/prompt`, workflow-build, or job-create
path. Python bytecode compilation and whitespace checks passed.

An additional related 29-test run passed 28 tests. The remaining existing
product HTTP test completed its functional assertions but failed during
temporary-directory cleanup because an existing SQLite connection remained
open. That teardown issue is outside this ownership task and was not changed.

## Single lifecycle result

The read-only launch Gate found zero ComfyUI candidates, zero collection
errors, and zero listeners on port 8191. The dedicated probe then started the
runtime exactly once. HTTP ready, running/pending queue zero, exact one
listener, launcher identity, runtime identity, listener identity, run/path
identity, creation-time matching, and descendant lineage all passed.

The observed process tree contained three members:

```text
launcher python.exe
|- runtime/listener python.exe
`- conhost.exe
```

The two exact ComfyUI candidates were the launcher and runtime/listener. The
third member was a Windows console host created as a direct launcher child.
The contract intentionally required every tree member to be an exact Python
runtime candidate, so these checks failed:

```text
tree_members_are_runtime_candidates = false
tree_processes_are_python = false
```

The lifecycle therefore failed closed before PRE_SHUTDOWN contract admission.
It was not retried. The probe did not automatically terminate an unpassed
tree. A separate check confirmed the two Python roles' exact run ID, direct
parentage, listener ownership, and empty queues; only those two verified
Python roles were stopped. The console host was not directly terminated and
exited with its owner. Foreign termination count was zero. Final run Python
processes, run console hosts, and port 8191 listeners were all zero.

Execution counts:

```text
runtime start/ready/contract shutdown = 1/0/0
runtime lifecycle retry = 0
H3 model load request = 0
Generation/CONTROL submission = 0/0
SELECTIVE/partial-Q/Attention omission = 0/0/0
foreign process termination = 0
```

The private and sanitized receipts both have SHA-256
`bdf73334131a8e08d0a94fd9e754db8eeb325aeeddc5ab12833b25545415ba07`.

## Decision

Final decision:

```text
H3_COMFYUI_LAUNCHER_CHILD_OWNERSHIP_CONTRACT_V2_BLOCKED
```

The requested READY state was not reached. A future contract revision would
need an explicitly bounded identity rule for the Windows console-host helper;
no such revision, second lifecycle, or CONTROL was started automatically.
