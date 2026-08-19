# H3 Rust Region-Sparse Cache Plan ABI V2

Date: 2026-08-19  
Issue: [#102](https://github.com/ksse29077-byte/HIVEFRAME/issues/102)  
Draft PR: [#103](https://github.com/ksse29077-byte/HIVEFRAME/pull/103)  
Branch: `codex/h3-rust-region-sparse-cache-plan-abi-v2`  
Base: `fa5f94be1ebfeb1036d04bcc0398c25cd39e90fa` (Draft PR #101 head)  
Dependency: `e83c40f2ffba1d237c98e3f02f4d113fd9e50e22` (Draft PR #91 head)  
Decision: `H3_RUST_REGION_SPARSE_CACHE_PLAN_ABI_V2_READY`

## 1. Start State

The user's active LTX checkout remained clean on
`admission/ltx-video-2b-fp8` at `2f5eb92...` and was not modified. A separate
worktree was created from the exact PR #101 head. PR #101 contains the
region-sparse remediation and depends on PR #91 G1D; neither branch was
changed. No duplicate ABI V2 Issue, branch, or PR existed.

Issue #102, this dedicated branch, and Draft PR #103 isolate the work. The PR
base is `codex/h3-cache-density-false-safe-remediation`, not `main` or LTX.

## 2. Scope

This task implements a model-free planning contract only. It ran no H3 model,
Generation, CUDA, CONTROL, SELECTIVE, LTX, Wan, product backend, service, UI,
or installer. It did not alter `ROADMAP`, `TASKS`, PR #91, or PR #101. The
patch scheduler and boundary bus remain stubs.

The existing A1 step policy remains unchanged at 18 generation-step metadata
calls. ABI V2 adds one generation-level cache-plan call and zero block,
region, or row calls.

## 3. Existing ABI

The existing in-process PyO3 policy boundary is ABI V1 and metadata-only. Its
recorded p95 values remain 0.0067 ms Rust plan and 0.0243 ms PyO3 boundary,
with 18 calls per generation and zero Rust tensor bytes. V2 is a separate
fixed contract. V1/version/size mismatches return Full Compute and cannot be
interpreted as V2.

## 4. CachePlanAbiV2

`hive-retina-runtime::cache_plan_v2` owns fixed request, identity, profile,
batch, candidate, inventory, plan, rejection, eviction, digest, and receipt
types. Current fixed sizes are:

| Type | Bytes |
|---|---:|
| request | 56 |
| generation identity | 296 |
| hardware profile | 104 |
| batch header | 56 |
| candidate | 256 |
| inventory entry | 72 |

The output contains selected `(block, region)` keys, rejected keys and reasons,
deterministic eviction order, selected bytes, planned/Full Q, reduction ppm,
effect/payload and effect/transfer scores, fallback reason, plan and lineage
digests, planned transfer, and receipt metrics.

## 5. CacheCandidate

Each fixed candidate contains target/source step, block, region, packed-row
range, STABLE/ACTIVE/UNCERTAIN state, actual safety evidence, uncertainty,
motion, cosine, corrected nL2, false-safe and nonfinite counts, planned/Full Q,
payload and transfer bytes, effect ratio, age, source kind, shape, dtype,
device, precision, quantization, three digests, eligibility, and rejection
reason. Python accepts an exact field whitelist with scalar integers and
32-byte digests only. Q/K/V, tensors, payload objects, prompt text, and source
paths cannot cross the boundary.

## 6. GenerationEvidenceBatch

The bridge compiles one bounded batch per generation. It supports at most
4,096 records, 200 inventory entries, a 4 MiB ABI ceiling, and a tighter
profile ceiling. Header count and canonical byte size must match the fixed
layout. Overflowed or truncated input is sent only as an explicit overflow
header with no truncated evidence records and returns generation-level Full
Compute. Malformed records, unknown enums, unsupported flags, and conflicting
duplicate events also fail open.

Distinct source/target events aggregate into one `(block, region)` key. Exact
duplicate events are counted once so duplicated evidence cannot inflate the
planned reduction.

## 7. CacheLineageV2

The lineage digest covers run, workflow, model, model revision, settings,
source plan, layout, input identity, scheduler, steps, resolution, frame count,
FPS, block, region, source step and kind, shape, dtype, device, precision, and
quantization. One mismatch excludes the candidate. Selection and complete
plan digests use deterministic canonical binary fields. No private raw input
is stored.

## 8. HardwareProfile

`Balanced12GB` injects a 12 GiB VRAM declaration, 2 GiB bounded host cache,
256 MiB staging, 2 GiB reserve, 40 GiB maximum generation transfer, 44 selected
regions, 2 MiB batch, BF16, no quantization, pinned-host offload, 864x480, 124
frames, and cache age one.

`Quality24GBPlus` injects 24 GiB VRAM, 4 GiB host cache, 512 MiB staging, 4 GiB
reserve, 88 selected regions, and 4 MiB batch while retaining bounded transfer
and the same algorithm. No GPU name is hard-coded. The 2 GiB value is not a
global constant.

## 9. Admission and Eviction

Admission excludes missing safety, non-STABLE, actually unsafe, false-safe,
lineage mismatch, age mismatch, nonfinite, and ineligible records. Eligible
keys use exact rational effect/payload-byte ordering with block/region
tie-breaks. Cache, staging, selection, transfer, candidate, batch, and work
budgets cannot be exceeded. Inventory eviction is deterministic and prioritizes
invalid/lineage-mismatched then lower-effect entries.

The fixed 30,000 ppm gate remains unchanged. A smaller plan returns
`PRE_GATE_BELOW_THREE_PERCENT`; unsafe candidates are never added to reach it.

## 10. Transfer Budget

The prior 33,098,956,800-byte D2H and 6,651,617,280-byte H2D evidence motivated
explicit generation transfer limits. Every candidate supplies payload, planned
D2H, and planned H2D bytes. Rust returns selected transfer totals and rejects a
candidate that would exceed the profile limit. Rust performs no transfer.

`rust_transfer_bytes` records the canonical metadata batch crossing PyO3.
Actual D2H/H2D and estimate-error fields remain `NOT_EXECUTED` until a real
executor populates them.

## 11. Python and PyO3 Boundary

`hive-retina-python` converts Python dictionaries directly into typed Rust
values in process. There is no JSON, serialization, subprocess, CLI, file I/O,
or tensor buffer. The Python bridge rejects extra or non-scalar fields, imports
the extension through Python's module cache, allows one Rust call per
generation, and returns a cached result for a duplicate request without a
second Rust call. Python conversion failures and extension exceptions return
Full Compute.

The PyO3 boundary wraps Rust planning in `catch_unwind`. A deliberate panic
probe returned Full Compute with reason `RUST_PANIC`; the panic hook printed a
diagnostic, but no exception escaped Python and the test continued.

## 12. Performance Receipt

Receipt values carry `MEASURED`, `STRUCTURAL_ZERO`, `UNKNOWN`, or
`NOT_EXECUTED`. This distinguishes unavailable values from real zeros. Fixed
fields cover module loading, process spawning, all call granularities,
evidence size, conversion/Rust/FFI/serialization times, metadata and tensor
transfer, CUDA synchronization, selected payload, planned/actual cache
transfer, estimate error, fallback, partial-to-full recovery, and overhead.

The frozen 72-record batch is 18,488 bytes. The 203-record 29-region batch is
52,024 bytes. Single release-build observations recorded 81,600 ns and
176,400 ns Rust planning time respectively; these are functional samples, not
a benchmark or p95 claim. Process spawn, serialization, block/region/row calls,
and tensor bytes per call are zero. CUDA and actual transfer are not executed.

## 13. Frozen Evidence Results

| Fixture | Selected bytes | Planned Q | Full Q | Reduction | Decision |
|---|---:|---:|---:|---:|---|
| PR #101 frozen safe set | 805,195,776 | 157,398 | 15,424,000 | 10,204 ppm | Full Compute |
| model-free 29-region contract fixture | 1,399,810,048 | 473,193 | 15,424,000 | 30,679 ppm | Plan Ready |

The first result preserves PR #101's failure. The second proves only ABI
representability and deterministic profile admission. It does not supply the
missing row-level CONTROL evidence or prove GPU omission, quality, or speedup.

## 14. Verification

| Check | Result |
|---|---|
| Rust V2 focused | 12 passed |
| New Python/PyO3 focused | 8 passed |
| New plus existing G1-related Python | 70 passed |
| Rust workspace tests | 50 passed |
| `cargo fmt --all -- --check` | passed |
| workspace release build | passed |
| workspace Clippy with two documented baseline lint allowances | passed |

The first Rust focused run failed six fixture assertions because the test
fixture declared candidate planned Q larger than its per-record Full Q. The
implementation was not relaxed; the fixture Full Q was corrected to a valid
value, after which all tests passed.

Strict `cargo clippy --workspace --all-targets --all-features -- -D warnings`
still reports three pre-existing findings: two `manual_div_ceil` findings in
`locality.rs` and one `too_many_arguments` finding in the existing PyO3
`run_candidate`. Neither file area is part of V2, so unrelated code was not
changed. The same workspace Clippy command passed when only those two lint
classes were explicitly allowed.

## 15. Gate Decision

| Gate | Result |
|---|---|
| CACHE_PLAN_ABI_V2 | PASS |
| ABI_SIZE_VERSION_GUARD | PASS |
| GENERATION_EVIDENCE_BATCH | PASS |
| BATCH_OVERFLOW_FULL_COMPUTE | PASS |
| CACHE_LINEAGE_V2 | PASS |
| HARD_BUDGET_PROFILE_DRIVEN | PASS |
| TRANSFER_BUDGET_PROFILE_DRIVEN | PASS |
| EFFECT_PER_BYTE_ADMISSION | PASS |
| DETERMINISTIC_EVICTION | PASS |
| RUST_TENSOR_TRANSFER_BYTES | 0 |
| PER_BLOCK_RUST_CALLS | 0 |
| PER_REGION_RUST_CALLS | 0 |
| PER_ROW_RUST_CALLS | 0 |
| FAIL_OPEN_FULL_COMPUTE | PASS |
| BALANCED_12GB_FIXTURE | PASS |
| QUALITY_24GB_PLUS_FIXTURE | PASS |
| PERFORMANCE_RECEIPT_CONTRACT | PASS |
| FOCUSED_TESTS | PASS |
| EXISTING_RELEVANT_TESTS | PASS |

Final decision: `H3_RUST_REGION_SPARSE_CACHE_PLAN_ABI_V2_READY`.

This is a contract-readiness result. Actual GPU acceleration, actual cache
hits, real Q omission, quality parity, the full compound-eye runtime, patch
scheduler completion, and boundary-bus completion are not claimed.

## 16. Changed Files

- `crates/hive-retina-runtime/src/cache_plan_v2.rs`
- `crates/hive-retina-runtime/src/lib.rs`
- `crates/hive-retina-python/src/lib.rs`
- `python/hive_product/rust_cache_plan_v2.py`
- `python/tests/test_h3_rust_region_sparse_cache_plan_v2.py`
- `docs/design/h3-rust-region-sparse-cache-plan-abi-v2.md`
- `docs/worklogs/2026-08-19-h3-rust-region-sparse-cache-plan-abi-v2.md`
- `docs/WORKLOG.md`

Diagram impact is `none`: no runtime, product, or GPU execution flow was
connected.

## 17. Commits and Remote State

Commit 1 contains the ABI, bridge, tests, and design contract. Commit 2
contains the final receipt correction and immutable verification record. Both
commits are pushed to the dedicated branch. Draft PR #103 remains Draft; no
ready or merge action was performed.

## 18. Next Approval

A separate approval is required to gather fresh row-level H3 CONTROL evidence
for enough safe regions and to connect a selected plan to the exact Attention
executor with cache-hit, lineage, partial/full XOR, actual-transfer, quality,
and timing receipts. This task does not automatically start that work.
