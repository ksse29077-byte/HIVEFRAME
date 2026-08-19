# H3 Row Region Safety Evidence CONTROL V2 Admission Retry

Date: 2026-08-19  
Issue: #113  
Branch: `codex/h3-row-region-control-v2-admission-retry`  
Base: Draft PR #112 head `bbf7910d992e8fbceddbe8664d8dd89d75572cb6`  
Decision: `H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED`

## Scope

The one-time exception authorized the first actual H3 Standard Full Compute
CONTROL submission after the earlier attempt stopped before submission. The
maximum remained one submission, one GPU start, and one completion. It did not
authorize a retry, fallback Generation, SELECTIVE, partial-Q, Attention
omission, product integration, or changes to protected prior PRs.

The fixed P1-A2 I2V profile, private input digest, workflow digest, prompt,
seed 101, 864x480 resolution, 124 frames, 24 FPS, 20 steps,
`res_multistep`, `simple`, disabled Sage, and existing precision/offload
settings were unchanged.

## Ownership lifecycle hardening

The branch added phase-specific PRE_LAUNCH, POST_LAUNCH, PRE_SHUTDOWN, and
POST_SHUTDOWN receipts. They bind a run ID, runner root PID and creation time,
backend creation time, process-tree identity, listener, executable, `main.py`,
port, and dedicated path digests. A PRE_SHUTDOWN mismatch prevents the runner
from terminating a process whose ownership is not proven by the receipt.

External RTX 3060 process memory is collected from Windows dedicated GPU
process counters and excludes only a proven owned PID. The runtime admission
also records allocator, fragmentation, persistent-source, pinned-memory, and
host-reserve checks.

## Model-free verification

- Related Python tests with the release PyO3 binary: 41/41 passed.
- Required release PyO3 subset: 15/15 passed, skip 0.
- Rust CachePlan ABI V2 tests: 12/12 passed.
- Rust tensor bytes: 0.
- Rust calls per generation: maximum 1.
- Per-block/per-region/per-row Rust calls: 0/0/0.
- Python bytecode compilation, Rust formatting, and whitespace checks passed.
- The fresh CUDA row-map oracle preserved BF16 bits and measured maximum
  CPU/GPU metric error `6.468e-8`, below `1e-6`.

The release extension SHA-256 is
`34b3404e05155a99afcade419464893b2ccbe2e7c35683c09a3d58df1447185f`.
The fresh oracle receipt SHA-256 is
`e8588afcde026423bddddb32b56c32db146343006e3a3fb393d09d5fa5c378df`.

## Runtime admission result

PRE_LAUNCH passed with both product queues empty, no external Generation, no
foreign ComfyUI runtime, and no listener on port 8191. Baseline NVIDIA usage
was 10 MiB. The projected CUDA peak remained 12,514,625,897 bytes against
12,884,377,600 physical bytes, leaving 369,751,703 bytes, above the fixed
256 MiB minimum. The 2 GiB reserve remained explicitly false as approved.

The dedicated runtime loaded the node and allocated and page-locked exactly
96,538,624 pinned-host bytes before submission. It retained 41,522,282,496
host bytes after accounting for the future 1,448,079,360-byte pageable source
cache. External dedicated GPU usage remained 14,209,024 bytes.

POST_LAUNCH ownership then failed closed. Windows created a launcher process
using the configured virtual-environment executable and a direct child using
the standalone-environment executable. Both carried the identical exact
`main.py` argv, unique run ID paths, port, and configuration identity. The
child owned the node and loopback listener. The receipt contract required the
node and listener PID to equal `Popen.pid`, and treated the child as a foreign
candidate, so these checks failed:

```text
node_pid_matches_backend_pid = false
listener_pid_matches_backend_pid = false
foreign_runtime_count_zero = false
candidate_count = 2
```

The same receipt proved the backend process alive, exactly one candidate at
the backend PID, the child within the backend process tree, root parentage,
creation-time identity, run ID, executable/main identities, and all dedicated
path identities. This is a launcher-child topology mismatch in the ownership
contract, not evidence of an external workload. The fail-closed result is
nevertheless binding.

## Lifecycle and cleanup

The admission failure occurred before workflow submission:

```text
submission/GPU start/completion = 0/0/0
retry/fallback = 0/0
SELECTIVE/partial-Q/omission = 0/0/0
Rust live compile/offline replay = 0/0
```

Therefore holdout records, false-safe, false-unsafe, planned Q reduction,
transfer totals, Rust plan/replay digests, MP4, and output integrity are
`NOT_EXECUTED`. No prior calibration value was promoted as holdout evidence.

The runner correctly refused automatic shutdown because its PRE_SHUTDOWN
ownership receipt had not passed. A separate read-only check then established
the unique run ID in both exact command lines, direct launcher-child
parentage, child ownership of port 8191, and empty running/pending queues.
Only that proven process tree was terminated. Foreign termination count was
zero, port 8191 had no listener afterward, and NVIDIA returned to 10 MiB and
zero utilization. This cleanup does not convert the failed ownership Gate
into a PASS.

The private and sanitized runner receipts both have SHA-256
`5e3453a10279a5f87ef2b1e99caa83fa44d7230430d0cad742c44345942cface`.

## Decision

Final decision:

```text
H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED
```

The success state was not reached. No CONTROL retry or executor integration
was started. Any launcher-child ownership-contract remediation and any future
CONTROL require separate authorization.
