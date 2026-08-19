# H3 ComfyUI Console Helper Ownership Contract V2

## Purpose

Close the model-free Windows lifecycle blocker observed by the launcher-child
ownership contract. Windows may attach a `conhost.exe` helper to the dedicated
ComfyUI launcher tree. The helper must be admitted by process identity and
lifecycle ownership, never by basename alone.

This work is limited to
`H3_COMFYUI_CONSOLE_HELPER_OWNERSHIP_CONTRACT_V2`. It does not load H3 or submit
a workflow, Generation, CONTROL, SELECTIVE, partial-Q, or Attention omission
work.

## Start state

- Issue: #117
- Branch: `codex/h3-comfyui-console-helper-ownership-contract-v2`
- Exact base: Draft PR #116 head
  `8b08f14f99e5e270813abe52687ba3dab8a84591`
- Implementation commit:
  `62182e65f7d8016c7409083cd103c9962ad8ed58`
- Existing PRs were not changed.

## Contract change

Ownership receipt schema V4 preserves `launcher_pid`, `runtime_pid`, and
`listener_pid` and adds an optional `console_helper_pid`. A console helper is
admitted only when all of the following are true:

- it is a verified launcher/runtime descendant in the observed process tree;
- PID and creation time match the preserved snapshot;
- executable basename is exactly `conhost.exe` and the executable is one of
  the existing trusted Windows system binaries;
- it does not present Python, `main.py`, or ComfyUI argument markers;
- it is not the runtime or listener and owns no TCP listener;
- it belongs to the same launcher lifecycle; and
- there is at most one admitted console helper.

No helper is also a valid state. A private-path lookalike, unexpected tree
member, listener-owning helper, PID reuse, path/run mismatch, foreign runtime,
or foreign listener fails closed. Unrelated `conhost.exe` processes outside
the approved tree are ignored.

Shutdown targets only the verified Python launcher/runtime tree. It never
searches for or terminates `conhost.exe` by name. The receipt requires the
admitted helper to disappear naturally after its owning Python processes stop.

## Receipt privacy and recovery

The V4 receipt retains safe role data only:

- role PID and creation time;
- parent/ancestor relations;
- executable basename and executable-path digest;
- run identity digest and command digest;
- listener owner and console-helper admission reason;
- PRE_LAUNCH, POST_LAUNCH, PRE_SHUTDOWN, and POST_SHUTDOWN topology; and
- helper continuity and shutdown evidence.

Raw command lines and private absolute paths are not retained. The first
topology snapshot is preserved before finalization so a failed final Gate can
still report added or missing PIDs and role classification evidence. The live
snapshot digest is
`a3691840c3cdf645544206f5c7fd3b2f8d5a209041ada6280f6a41e1ff660b57`.

## Focused verification

Focused ownership regressions and the unchanged CONTROL V2 structure tests
passed 33/33. Python compile and `git diff --check` passed. Fixtures cover:

- single-PID runtime;
- launcher to runtime/listener;
- launcher to runtime/listener plus trusted console helper;
- optional helper absence;
- private-path fake helper;
- unknown in-tree child;
- helper listener ownership;
- PID reuse/creation-time mismatch;
- unrelated external helper;
- foreign ComfyUI/Python runtime;
- foreign listener; and
- runtime path/run identity mismatch.

A read-only preflight observed seven unrelated external `conhost.exe` samples;
none parsed as a ComfyUI runtime. The trusted Windows console-helper path count
was one. No process was changed by this scan.

## Authorized live lifecycle

The one authorized model-free lifecycle ran exactly once with retry zero:

```text
start
-> launcher/runtime/listener/console-helper roles observed
-> ready
-> POST_LAUNCH ownership PASS
-> PRE_SHUTDOWN ownership PASS
-> verified Python runtime descendant stopped
-> launcher stopped
-> console helper natural exit observed
-> POST_SHUTDOWN ownership PASS
```

Observed role topology:

```text
launcher python.exe (PID 41300)
|- runtime/listener python.exe (PID 38204)
`- trusted conhost.exe (PID 41140)
```

The listener owner was PID 38204. The helper admission reason was
`TRUSTED_WINDOWS_CONSOLE_HELPER`; all nine helper admission checks passed and
the unexpected-tree-member set was empty. Role and helper identity remained
continuous from POST_LAUNCH through PRE_SHUTDOWN.

Only runtime descendant PID 38204 was directly stopped before launcher
shutdown. Console-helper direct termination and foreign process termination
were both zero. The helper exit status was `natural_exit_observed`. Final run
Python processes and port 8191 listeners were both zero.

Private and public safe receipts have the same SHA-256:
`b1ba518a9391700c786fafe7fd7b3df556a24bba0b544966469da8e0cce794c1`.

## Cost and prohibited-path receipt

- Runtime start/ready/shutdown: 1/1/1
- Retry: 0
- H3 model load: 0
- Generation: 0
- CONTROL submission: 0
- SELECTIVE: 0
- partial-Q: 0
- Attention omission: 0
- External process termination: 0
- Console-helper direct termination: 0

The probe contains no workflow submission path, including no `/prompt`
request. Therefore GPU workload submission was structurally zero. No CONTROL
or later research stage was started.

## Decision

`H3_COMFYUI_CONSOLE_HELPER_OWNERSHIP_CONTRACT_V2_READY`

The optional Windows console helper is now admitted only by trusted executable,
ancestry, creation-time, listener, and lifecycle evidence. The exact one-time
model-free lifecycle passed and the constitutional exception ends here.
