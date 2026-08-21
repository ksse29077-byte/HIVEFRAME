# H3 Background Oracle Step-Lineage Remediation

## Authorization and exact base

Issue #123 tracks the one-time constitutional exception for
`H3_BACKGROUND_ORACLE_STEP_LINEAGE_REMEDIATION`. The branch starts from exact
Draft PR #122 head `dd06404dfc7080b3aeb3293b93d9c1ae0edcb5e5`. The local
head, remote PR head, and clean worktree matched before analysis. PR #122 and
all earlier PRs remain unchanged.

The authorized scope is model-free analysis of the retained failure evidence,
the fixed scheduler and lineage source, and bounded fixtures only after the
root-cause Gate. H3 model load, Generation, CONTROL retry, SELECTIVE,
partial-Q, Attention omission, executor integration, and product changes are
prohibited.

## Retained evidence audit

The immutable retry callback and runtime log preserve 20/20 sampler progress
and the compound worker exception:

```text
ControlV2EvidenceError: source lineage or step ordering changed
```

The callback has no `attention_execution` object because finalization failed.
Consequently, it does not preserve the worker's partial state. The required
failure fields have the following evidence status:

| Required field | Retained status |
| --- | --- |
| actual model-forward order | NOT PRESERVED; sampler callback order `0..19` is not substituted |
| forward scheduler timestep | NOT PRESERVED |
| failing source/current step | NOT PRESERVED |
| oracle enqueue order | NOT PRESERVED |
| CUDA completion order | NOT PRESERVED |
| pinned-ring write order | NOT PRESERVED |
| finalizer read order | NOT PRESERVED |
| failing block/region | NOT PRESERVED |
| first mismatch position | NOT PRESERVED |
| normal records before mismatch | NOT PRESERVED |
| Attention call order within a step | NOT PRESERVED |

The retained artifact digests remain:

- callback: `a4852a2d2d333599d836fab2ff5d0c157b1eaa50d90670463a401e52f3196c5c`
- runtime log: `37672b9182fc89b7734cb72a40656457edb55157be71c6b5961c1731c82b6ebb`
- private/public receipt: `74236c23198237c3d403c116ab1ab02ff126d9285050e6b744bda3a98d36ca5d`

No partial worker record is reconstructed from process memory, CUDA state, or
the final exception.

## Source-readonly findings

The failing `step` is not a raw scheduler timestep. `H3A3G1Controller` derives
it as `step, block_index = divmod(block_call_count, 50)`. The CONTROL V2 node
receives the scheduler `sigmas` input, but does not pass the sigma/timestep
sequence to the controller or worker. The worker therefore cannot have applied
numeric `+1` to a raw scheduler timestep in the failed predicate.

The worker stores source payloads and steps by synthetic block identity. Its
single consumer reads a FIFO queue and waits for each queued slot to report
completion before reading the next queue entry. Under the documented
single-producer assumptions, a later CUDA completion cannot change that FIFO
finalizer order. The preserved evidence does not establish whether those
assumptions were violated by concurrent enqueue, stale event/slot state,
duplicate or missing work, or another condition.

The exception combines two checks in one branch:

```text
source_step + 1 != step OR metadata.lineage_base != worker.lineage_base
```

It records neither operand. Although the lineage value is constructed as a
constant in this controller instance, the retained trace cannot prove which
subcondition evaluated true or identify the first offending record.

## Scheduler and Rust contract audit

The fixed Standard workflow uses `BasicScheduler` with `scheduler=simple` and
20 steps. A model-free scheduler sequence could demonstrate that raw sigma
values may decrease or be non-unit-spaced, but it cannot recover the absent
source/current/completion values from the completed run. Running such a
sequence would not identify the actual failure category because raw timesteps
were not inputs to the failed predicate.

Rust CachePlan ABI V2 currently treats `target_step` and `source_step` as
bounded denoise ordinals: both must be below `total_steps`, and structural
admission requires `target_step == source_step + 1`. `scheduler_id` belongs to
the generation identity. No raw scheduler timestep is carried. This meaning is
internally consistent, but the requested scheduler digest/timestep extension
must not be introduced speculatively before the actual failure cause and
pairing record are established. ABI version and size therefore remain
unchanged. Rust calls, Rust metadata bytes, tensor-to-Rust bytes, and CUDA sync
count for this task are all zero.

## Root-cause Gate

The evidence rules out `RAW_SCHEDULER_TIMESTEP_MISUSED` in the failing worker
predicate. It does not prove any one of the remaining allowed categories. In
particular, it cannot distinguish `ASYNC_COMPLETION_REORDER`,
`STALE_SOURCE_SLOT`, `CROSS_STEP_SLOT_REUSE`,
`DUPLICATE_OR_MISSING_RECORD`, or another cause. The required result is:

```text
root_cause = UNKNOWN
```

The instruction explicitly forbids guessing when the trace is insufficient.
The root-cause Gate therefore fails before contract edits, anonymized real
failure fixture construction, or bounded CUDA execution. Fabricating a
source/current sequence would not be a regression fixture of the actual run.

## Counters and decision

- H3 model loads: 0
- Generation and CONTROL submissions: 0
- SELECTIVE, partial-Q, and Attention omission: 0/0/0
- bounded CUDA executions: 0
- Rust calls and tensor-to-Rust bytes: 0/0
- production code changes: 0
- existing PR changes: 0

The fail-closed decision is:

```text
H3_BACKGROUND_ORACLE_STEP_LINEAGE_REMEDIATION_BLOCKED
```

The exception ends at the evidence-insufficiency Gate. No CONTROL retry or
executor work is authorized or started.

Diagram impact: none. No architecture or runtime contract changed.
