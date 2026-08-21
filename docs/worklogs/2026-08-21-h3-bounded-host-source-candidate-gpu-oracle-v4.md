# H3 Bounded Host Source Candidate GPU Oracle V4

Date: 2026-08-21  
Issue: #135  
Exact base: `346e4a45b6fa0b9006d113e46c265b99ac6abcf7` (Draft PR #134 head)  
Branch: `codex/h3-bounded-host-source-candidate-gpu-oracle-v4`

## Authorization And Scope

The one-time exception authorizes an exact BF16 bounded host source cache,
GPU-local preliminary evidence, candidate-only source H2D, an exact GPU oracle,
model-free and bounded CUDA preflight, and at most one unchanged H3 Standard
Full Compute Formal CONTROL. SELECTIVE execution, partial-Q, Attention or cache
omission, product integration, a second H3 submission, and automatic retry are
out of scope.

The Start Gate passed before modification. Local and remote PR #134 heads were
the exact authorized base, the worktree was clean, cumulative prior Formal
CONTROL submissions were three, queue and listener counts were zero, and the
RTX 3060 was idle. Existing protected Draft PR heads were snapshotted and are
not modified by this branch.

## Frozen Inventory Recalculation

The immutable calibration remains `CALIBRATION_ONLY`. It supplies safe geometry
blocks `0..29`; blocks `30/31/48/49` remain vetoed. Region 0 contains 2,331
omittable Q rows and one exact BF16 source payload is 48,269,312 bytes.

There are sixteen age-one source opportunities. Twelve simultaneous source
blocks can produce at most `12 * 16 * 2,331 = 447,552` planned rows, below the
three-percent requirement of 462,720 rows. Thirteen blocks are therefore the
minimum. The deterministic inventory selects calibration-safe blocks `0..12`,
all thirteen for the first fifteen source steps, and blocks `0..3` for source
step 16. This produces exactly 199 candidate records:

```text
planned Q rows:             463,869
Full Q rows:             15,424,000
planned Q ratio:           3.00745%
resident exact host source: 627,501,056 B
candidate source H2D:      9,605,593,088 B
```

This is opportunity planning only. A future Formal CONTROL record is admitted
as holdout evidence only after preliminary candidacy, age-one lineage, and the
exact GPU oracle all complete. No calibration label is promoted.

## Model-Free Contract

`h3_bounded_host_source_oracle_v4.py` freezes:

- the 13-block, 199-record inventory and digest;
- exact BF16 source shape and byte accounting;
- zero current-payload and CPU-oracle payload D2H;
- one shared 48,269,312-byte GPU staging buffer;
- strict `FREE -> H2D_IN_FLIGHT -> GPU_READY -> ORACLE_PROCESSING -> FINALIZED -> FREE` ownership;
- candidate H2D admission with 20% headroom and the 12 GiB hard cap;
- the 32 GiB total tensor-transfer cap;
- exact-order, same-step burst, H2D latency, oracle latency, and combined 1.5x replays.

The first focused run passed 7/7 tests. The CUDA-helper static additions then
passed the expanded 9/9 focused tests. They allocated no model, submitted no
workflow, performed no H3 Generation, and executed no GPU Attention work.

## Bounded CUDA Gate Failure

The one model-free bounded CUDA fixture was executed on the idle RTX 3060. The
pre-run device receipt was 12,288 MiB total, 10 MiB used, and 0% utilization.
The fixture passed exact BF16 D2H/H2D bit identity, compressed fingerprint,
exact GPU metric, packed-row, threshold-boundary, metadata-size, and bounded
allocation checks. Its measured peak was 196,618,240 allocated bytes and
213,909,504 reserved bytes. CPU/GPU bounded-reference error was:

```text
maximum absolute error: 1.1920928955078125e-07
mean absolute error:    1.987791620194912e-08
```

The mandatory in-process teardown Gate failed:

```text
baseline allocated/reserved: 0 / 0 B
final allocated/reserved:    8,606,720 / 27,262,976 B
allocated returned:          false
reserved returned:           false
```

The implementation retained auxiliary tensor/event references that were not
included in its final deletion set before `empty_cache()` and the final memory
check. Therefore this is an implementation/preflight failure, not an admitted
allocator result. The fixture process exited normally enough for an external
read-only check to show the GPU back at 10 MiB and 0% utilization, but process
exit recovery cannot replace the required in-process teardown proof.

Per the no-retry and immediate-stop rule, the CUDA fixture was not rerun. The
runtime controller, ComfyUI node, release PyO3 Gate, Formal CONTROL, holdout,
and Rust compile/replay were not started. No threshold or budget was changed.

## Execution Ledger

```text
H3 model load:             0
Formal CONTROL submission: 0
GPU start:                 0
Generation completion:     0
SELECTIVE:                 0
partial-Q:                 0
Attention omission:        0
retry:                     0
```

Final bounded decision:

```text
H3_BOUNDED_HOST_SOURCE_CANDIDATE_GPU_ORACLE_V4_FAILED
```

The Formal CONTROL is blocked with submission/GPU start/completion `0/0/0`.
The single bounded CUDA fixture is not an H3 GPU start and is not a CONTROL
submission. A future teardown remediation requires a separate user approval;
this task does not retry it automatically.
