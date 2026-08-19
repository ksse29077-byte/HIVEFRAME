# H3 Rust Region-Sparse Cache Plan ABI V2

Status: model-free contract implemented; runtime execution not connected  
ABI version: `2`  
Contract version: `1`

## Purpose

This ABI compiles one bounded generation-level metadata batch into a
deterministic region-sparse cache plan. It does not execute Attention, move a
cache payload, call CUDA, or authorize reuse by itself. Python and the future
H3 executor retain all tensors and must fail each selected key to exact Full
Compute on cache miss, lineage mismatch, scene cut, nonfinite data, or any
execution error.

ABI V2 is separate from the existing step-policy ABI V1. A version or fixed
size mismatch returns a generation-level Full Compute plan.

## Ownership Boundary

Rust owns:

- fixed metadata validation;
- `CacheLineageV2` digest verification;
- profile-driven cache and transfer budgets;
- deterministic effect-per-byte admission and eviction ordering;
- the 3% planned-Q pre-gate;
- plan, lineage, and performance-receipt contracts.

Python owns:

- collecting already-available scalar evidence into one bounded batch;
- retaining GPU tensors and payloads outside Rust;
- calling V2 no more than once per generation;
- applying the future plan with exact fail-open checks.

The existing A1 research policy may continue its 18 step-level metadata calls.
V2 adds one generation-level compile call and adds zero block, region, or row
calls. There is no subprocess, CLI, JSON, file I/O, Q/K/V, or Attention payload
in the real-time boundary.

## Fixed Inputs

`GenerationCachePlanRequest` carries ABI and contract versions, generation and
step identity, bounded record and byte limits, Full Q rows, overflow policy,
and unsupported flags.

`GenerationIdentityV2` carries only digests and non-sensitive scalar identity:
run, workflow, model, model revision, settings, source plan, layout, input,
scheduler, step count, resolution, frame count, and FPS. Prompt text, source
paths, and personal image data are excluded.

`HardwareProfileV2` is selected by capability profile rather than GPU name. It
contains VRAM, host cache, staging, reserve, transfer, precision,
quantization, offload, resolution, frame, age, candidate, selected-region,
batch, and bounded-work limits.

`GenerationEvidenceBatchV2` contains a fixed header and bounded
`CacheCandidateV2` records. Overflowed or truncated input is never interpreted
as safe evidence; the entire generation falls back to Full Compute.

`CacheCandidateV2` contains:

- target/source step, block, region, and packed-row range;
- state and actual safety evidence;
- uncertainty, motion, cosine, corrected nL2, false-safe and nonfinite counts;
- planned and Full Q rows, payload and transfer byte estimates;
- cache age, source kind, shape, dtype, device, precision, and quantization;
- shape, packed-row, and lineage digests;
- admission eligibility and rejection reason.

The existing cache inventory is bounded separately and contains metadata only.

## CacheLineageV2

The lineage digest combines every generation identity digest plus block,
region, source step and kind, shape, dtype, device class, precision,
quantization, scheduler, steps, resolution, frame count, and FPS. Any mismatch
rejects that candidate. Selection lineage and plan digests are deterministic
SHA-256 values over canonical binary fields.

## Profiles

`Balanced12GB` expresses the current 2 GiB host-cache contract inside the
fixture, not as a global constant. `Quality24GBPlus` injects a bounded 4 GiB
host cache and larger staging/selection limits. Both profiles use the same
validation, lineage, admission, eviction, and pre-gate algorithm. Neither
profile contains a GPU product name.

## Admission

Candidates must be STABLE, supported, actually safe, finite, age one,
lineage-valid, and explicitly eligible with zero false-safe observations.
Exact duplicate evidence events are counted once; conflicting duplicates fail
the generation open. Records for distinct source/target events of one
`(block, region)` are aggregated into one selected key.

Eligible keys are sorted by exact rational effect/payload-byte score, then by
block and region. Admission must stay within host-cache, staging, selected-key,
transfer, candidate, batch, and bounded-work limits. Rejected keys retain a
reason code. Inventory eviction is ordered deterministically by invalidity,
effect per byte, block, and region.

The plan is `READY` only when selected planned Q rows are at least 30,000 ppm
of Full Q rows. Unsafe evidence is never added to satisfy this gate. A lower
result returns `PRE_GATE_BELOW_THREE_PERCENT` and Full Compute.

## Fail-Open Rules

The generation returns Full Compute for ABI/size mismatch, invalid identity or
profile, batch overflow/truncation, malformed or unknown fields, malformed
inventory, Python conversion failure, Rust panic, or plan compilation failure.
Individual unsafe or lineage-invalid candidates are rejected. A future
executor must additionally Full Compute the affected key on cache miss or
runtime invalidation.

No forced thread termination is used. Input count, byte size, work units, and
the deterministic algorithm bound execution.

## Receipt

Every plan has status-bearing metrics. `MEASURED`, `STRUCTURAL_ZERO`,
`UNKNOWN`, and `NOT_EXECUTED` distinguish a real zero from unavailable work.
The receipt fixes module-load, process-spawn, generation/step/block/region/row
call counts, evidence size, conversion/Rust/FFI/serialization timing, Rust and
GPU/CPU transfer bytes, CUDA synchronization, selected payload, planned and
actual D2H/H2D, estimate error, fallback, partial-to-full recovery, and Rust
overhead fields.

In this model-free phase, `rust_transfer_bytes` measures the canonical fixed
metadata batch size. Rust process spawning, serialization, tensor bytes per
call, and block/region/row calls are structural zero. GPU transfer, CUDA,
actual cache transfer, recovery, and estimate-error metrics are
`NOT_EXECUTED`. Rust overhead ratio remains `UNKNOWN` until a real generation
defines the denominator.

## Frozen Compatibility

The PR #101 frozen safe set selects 18 `(block, region)` keys using
805,195,776 bytes and plans 157,398 of 15,424,000 Full Q rows, or 10,204 ppm.
It therefore remains Full Compute. A model-free 29-region fixture selects
1,399,810,048 bytes and plans 473,193 Q rows, or 30,679 ppm, proving only that
the contract can represent a qualifying safe plan.

Neither fixture proves real row-level safety, cache availability, actual GPU
work omission, quality parity, or speedup.

## Deferred Work

The H3 Attention executor connection, per-key cache-hit validation, actual
D2H/H2D receipt population, partial/full XOR enforcement, row-level CONTROL,
quality validation, and runtime timing require separate approval. The patch
scheduler and boundary bus remain stubs. Product, service, UI, installer, LTX,
Wan, Generation, and CUDA work are outside this contract.
