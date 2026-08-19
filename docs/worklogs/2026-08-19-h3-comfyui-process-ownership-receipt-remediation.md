# H3 ComfyUI Process Ownership Receipt Remediation

Date: 2026-08-19  
Issue: #111  
Branch: `codex/h3-comfyui-process-ownership-receipt-remediation`  
Base: Draft PR #110 head `aacaf761889e25277b2cfdb3519dfa4ffa3a2268`  
Decision: `H3_COMFYUI_PROCESS_OWNERSHIP_RECEIPT_REMEDIATION_READY`

## Scope

This task repairs only the process-ownership evidence gap that blocked CONTROL
V2 before submission. It does not authorize or execute an H3 model load,
Generation, CONTROL submission, SELECTIVE, partial-Q, Attention omission,
retry, fallback, or executor integration. Protected prior PRs, product
UI/backend, LTX, Wan2.2, installer, `ROADMAP.md`, and `TASKS.md` are unchanged.

## Prior failure

The PR #110 runner searched every process command line for the strings
`ComfyUI` and either `main.py` or `--listen`, then required exactly one result.
That broad textual classification was not bound to the process created by the
backend. Its original blocked receipt also omitted the raw candidate count and
process identities, so the post-shutdown mismatch could not be reconstructed.

The Gate failed closed and correctly prevented Generation, but its evidence
was not sufficiently specific for a safe follow-up admission.

## Remediated ownership contract

A process is now a ComfyUI runtime candidate only when its actual argv has the
repository backend shape:

1. argv 0 is the Python executable;
2. argv 1 basename is exactly `main.py`;
3. `--listen` and `--port` each have one parseable value;
4. the port is within the valid TCP range.

Text embedded in a shell command, log command, or probe argument is not a
runtime candidate.

Post-start ownership passes only when all independent signals agree:

- backend `Popen.pid` is positive and alive;
- node admission PID equals backend PID;
- exactly one parsed candidate has that PID;
- there are zero other parsed ComfyUI runtime candidates;
- the loopback listener PID equals backend PID;
- executable and `main.py` paths match the configured ComfyUI root;
- host and port are exactly the dedicated loopback endpoint;
- extra-model config and input/output/temp/user paths match the dedicated run;
- auto-launch is disabled exactly once.

Any missing process, PID mismatch, listener mismatch, foreign runtime,
malformed argv, or path mismatch remains fail-closed before submission.

## Receipt privacy

The collector uses full paths only for in-process comparison. The retained
receipt contains basename and SHA-256 path/command digests, PID, parent PID,
listen host, port, argument count, and creation time. Full argv and private
paths are not retained in candidate summaries. Existing public sanitization
still applies to the complete runner receipt.

## Verification

- New model-free focused tests: 7/7 passed.
- Related Python with release PyO3 loaded: 37/37 passed.
- Python bytecode compilation: passed.
- Rust formatting and whitespace checks: passed.
- Live read-only collector: candidate 0, access errors 0, disappeared 0.
- Port 8191 listener: none.
- NVIDIA VRAM usage after verification: 10 MiB.

Fixtures prove exact admission and fail-closed behavior for node PID mismatch,
foreign runtime, listener PID mismatch, output-path mismatch, and port mismatch.
The expected Rust panic-containment fixture printed its panic hook and passed.

Execution counts for this remediation:

```text
H3 model load = 0
Generation/CONTROL submission = 0/0
GPU start/completion = 0/0
SELECTIVE/partial-Q/omission = 0/0/0
retry/fallback = 0/0
```

## Decision

Final decision:

```text
H3_COMFYUI_PROCESS_OWNERSHIP_RECEIPT_REMEDIATION_READY
```

This decision validates the ownership receipt implementation only. It does not
change the blocked PR #110 result and does not authorize a CONTROL retry.

