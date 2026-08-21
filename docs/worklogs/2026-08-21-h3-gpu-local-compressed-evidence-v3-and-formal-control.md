# H3 GPU-Local Compressed Evidence V3 and Formal CONTROL

## Authorization and exact base

Issue #133 tracks the one-time constitutional exception for
`H3_GPU_LOCAL_COMPRESSED_EVIDENCE_V3_AND_FORMAL_CONTROL`. The work started
from exact Draft PR #132 head
`94b10cd6fdc9a39b4b6b56378200e41eedd7dce6`. Local HEAD, remote PR head,
the clean worktree, the V2 failure receipt, the production slot lifecycle,
and the cumulative Formal CONTROL submission count of three all matched.

The runtime was idle before analysis: external running/pending jobs were
zero, port 8191 had no listener, no ComfyUI runtime candidate was present,
and the RTX 3060 was at its 10 MiB idle baseline.

## Product question

The proposed V3 must replace the all-candidate 48 MiB-class D2H CPU oracle
with GPU-local compressed evidence while retaining a candidate-only exact GPU
oracle. It may not lower video quality settings, execute Selective or
partial-Q, omit Attention work, relax thresholds, allocate a persistent
per-candidate GPU payload, or transfer a full source/current tensor to the
CPU.

## Structural admission analysis

The exact oracle requires both the current Full Compute Attention output and
the exact same-generation source output. In the current runtime, the only
producer of the host source cache is the V2 `_refresh_cache()` path:

```text
current Full Attention output
-> 48,269,312-byte region payload D2H
-> host source cache
-> later candidate-only H2D
-> exact GPU comparison
```

V3 explicitly requires all of the following:

```text
legacy tensor-ring allocation=0B
full current/source tensor D2H=0B
oracle tensor D2H=0B
persistent per-candidate GPU payload=0B
shared GPU staging buffers=1
shared staging bytes<=48,269,312B
```

No other same-generation source provider exists in the installed H3 hook,
the repository host-cache implementations, or the approved workflow. A
previous Generation cannot provide the source because generation identity,
source step, scheduler timestep, and lineage must match the current
Generation. Compressed scalar metadata is not a lossless representation of
an arbitrary BF16 source tensor and therefore cannot produce the required
exact cosine and corrected nL2 against a later current tensor.

## Three-percent lower bound

The frozen Full Q baseline is 15,424,000 rows and one admitted block-region
record plans 2,331 omitted Q rows. A three-percent result therefore requires:

```text
minimum planned Q rows=462,720
minimum admitted exact-oracle records=199
eligible target records per retained block source=16
minimum simultaneously retained block sources=13
bytes per exact BF16 block-region source=48,269,312
minimum exact source storage=627,501,056B
```

The authorized shared staging capacity is one source, 48,269,312 bytes. Even
if the prohibition on persistent per-candidate GPU payloads were ignored,
the measured 369,751,703-byte projected VRAM headroom could retain at most
seven sources. Seven sources expose at most 261,072 planned rows, about
1.693%, below the frozen three-percent Gate. The single authorized shared
source exposes only 37,296 rows, 0.2418%.

Host retention would fit the historical RAM envelope, but populating it in
the same Generation requires the full-tensor D2H that V3 explicitly sets to
zero. Implicit unified-memory migration, delayed CPU reads, or a compressed
sketch relabeled as exact would violate the same contract rather than solve
it.

## Admission decision

The source-provenance and storage constraints are jointly unsatisfiable. An
implementation could only pass by doing at least one prohibited thing:

- transfer candidate source tensors D2H,
- retain multiple exact sources on the GPU,
- weaken the exact oracle into an approximate sketch comparison, or
- admit candidates without an exact oracle.

None was done. V2 code and evidence remain unchanged. No V3 node, tensor
buffer, CUDA kernel, PyO3 path, threshold, workflow, or product path was
modified. Model-free fixtures, CUDA preflight, release ABI tests, H3 model
load, runtime start, and Formal CONTROL were not entered after this
pre-submit structural Gate.

## Counters

```text
PRIOR_CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=3
CURRENT_TASK_FORMAL_CONTROL_SUBMISSIONS=0
FINAL_CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=3
CURRENT_TASK_RETRY_COUNT=0
SELECTIVE/PARTIAL_Q/ATTENTION_OMISSION=0/0/0
RUST_LIVE_COMPILE/OFFLINE_REPLAY=0/0
```

Because no V3 runtime path was admitted, execution counters such as metadata
D2H, candidate H2D, exact-oracle candidates, holdout confusion, plan digest,
and output integrity are `NOT_EXECUTED`, not measured zero.

## Final decision

```text
H3_GPU_LOCAL_COMPRESSED_EVIDENCE_V3_ADMISSION_BLOCKED
```

The one-time exception ends at this Gate. No threshold, memory, transfer, or
oracle requirement was relaxed, and no follow-up architecture or Generation
was started automatically.
