# M1-P0-R2 Python Attribution and Rust Compound Runtime

Status: model-free evidence complete; decision `REFINE_RUST_BOUNDARY`

Issue: [#42](https://github.com/ksse29077-byte/HIVEFRAME/issues/42)

Base and PR #41 merge commit:
`e5bbaa751d7c449dd0c5a7ad3b7fff18bd661388`.

## Purpose and product direction

R2 attributes removable implementation overhead in the current Python
Compound I/O control plane and tests whether a coarse Rust-first boundary can
recover it. Compound Perception First remains the product direction. Mono is
the same-condition comparator and safety fallback, not the default product
decision and not an R2 Gate outcome.

This is a CPU-only, model-free M1-P0 refinement. It does not close M0 or M1,
admit or invoke H3, modify Wan, reactivate LTX, load a model, use CUDA, or
claim backend, quality, end-to-end, product, or commercial speedup.

## Immutable evidence and bounded scope

The sixteen v1/R1 config, design, worklog, success-report, decision, and failed
attempt Git blobs are fixed by SHA-256 in
`configs/m1-p0-r2.rust-compound-runtime.json`. Validation normalizes checkout
CRLF to Git's LF form before comparison with the merged `main` blob hashes, so
newline conversion cannot rewrite the evidence contract.

R2 measures only Case B:

- B/T0 (`mono_1x1`);
- B/T1 (`uniform_2x2`);
- B/T2 (`motion_focused`).

No new topology or corpus is added. A/T1, A/T2, C/T1, and C/T2 remain
analytically pruned and are not executed.

The executable profile ID and single declared change region are the exact R1
Case B contract, not the older three-region Rust-admission profile named
`high`.

## Python stage taxonomy and timing

The fixed taxonomy is input validation, Eye contract construction, Eye setup,
routing, coordinate transform, mask construction, crop/view construction,
array allocation, explicit copy, observation, overlap handling, Fusion input
conversion, Fusion, SharedVisualState construction, ComputePlan construction,
receipt construction, JSON serialization, and garbage collection.

Nested spans use `time.perf_counter_ns`. Inclusive time is span end minus span
start. Exclusive time is inclusive time minus the union of direct child spans.
The empty span tree is calibrated separately; overhead is reported and never
silently subtracted. Official Python/Rust comparison uses a separate
uninstrumented Python execution before the attributed execution for every
deterministically interleaved candidate.

The block-level identity is:

```text
C_paired_delta(T, i)
  = sum(C_exclusive_stage(T, i) - C_exclusive_stage(T0, paired_i))
  + C_unattributed(T, i)
```

Negative per-run unattributed duration is rejected. The same-block
candidate-minus-Mono unattributed remainder may be signed, because the
candidate's instrumentation remainder can be smaller than the paired Mono
remainder. Independent median subtraction is forbidden. Each phase uses five
warm-up and twenty measured T0/T1/T2 blocks in one Python process with one
prepared Case B NumPy object.

## Copy and allocation accounting

- NumPy receptive-field crops are views and count zero copied pixel bytes.
- Motion difference and mask arrays count as allocated and temporary bytes.
- An absent explicit-copy operation has call count zero and copied bytes zero;
  it is not an unsupported timing value disguised as zero.
- Python writes the packed input once for the coarse Rust process boundary.
- Rust reads the packed input once. Both full-buffer copies are counted.
- Rust JSON bytes and the temporary input/output files are recorded separately.
- Unsupported FFI time remains `null` with status, reason, and method.

## Coarse Rust boundary

The bounded v0 transport is one subprocess batch:

```text
one packed Case B buffer handoff
  -> one Rust process
  -> internally run complete T0/T1/T2 topology blocks
  -> return semantic results, ComputePlans, timing, counters, and receipt metadata
```

There is no per-Eye Python/Rust round trip. The Rust scope includes Eye
contract/routing/coordinate work, mask/view metadata, observation
orchestration, Fusion, SharedVisualState, ComputePlan, and receipt metadata.
Python/PyTorch retains model tensors, VAE, denoising, attention/scheduler
hooks, and model evaluation. Those model-plane components are not executed in
R2.

The process transport measures Rust core, external process call, Python input
write and output parse, Rust input read and serialization, copied bytes, and
temporary bytes. Boundary-inclusive time contains the full Python input-write
and output-parse wrapper scope as well as process scope. PyO3/C-ABI FFI is deliberately not introduced; its time is
`null/not_collected`. Benchmark-suite amortized boundary time is labeled as
such and is not a single-call product latency claim.

## Fixed thresholds and decisions

- Python attributed percentage: at least 80%;
- Python unattributed percentage: at most 20%;
- Rust T1 and T2 core reduction: strictly greater than 0%;
- boundary-inclusive T1 and T2 reduction: strictly greater than 0%;
- exact semantic parity and deterministic hashes required;
- total boundary copies: at most two packed input-buffer equivalents;
- collected FFI timing required for `RUST_RUNTIME_VIABLE`;
- unavailable values must remain `null`.

Exactly one decision is allowed:

- `RUST_RUNTIME_VIABLE`;
- `REFINE_RUST_BOUNDARY`;
- `OPTIMIZE_COMPOUND_RUNTIME`;
- `PAUSE_CURRENT_IMPLEMENTATION`.

`MONO_FIRST` is not an R2 decision. `PAUSE_CURRENT_IMPLEMENTATION` stops the
current implementation shape, not Compound Perception First.

The taxonomy, equation, instrumentation, boundary, copy policy, thresholds,
and decision tree are committed before measurement and may not be changed in
response to results.

## Planned evidence

R2 writes only new files under `reports/topology_pruning/r2/`:

- `predeclared-attribution-model.json`;
- `python-stage-attribution.json`;
- `rust-boundary-results.json`;
- `parity-report.json`;
- `decision-report.md`.

Existing output causes a pre-execution failure; overwrite is unsupported.

## Measurement provenance and preserved failures

- original predeclaration commit:
  `f5b333dc716ec3175cc6601c255660c95a25affd`;
- exact Case B corrective commit:
  `dc1656ae088377206043444d58ef2d49297c5c99`;
- rewritten boundary-accounting and public-serialization commit:
  `bf1b90d6c0b35a5aad3a72d6f9f3534a9792b973`.

The original commit was replaced because it first introduced attempt-002
artifacts containing private execution paths and repeated invariant semantic
payloads. The predeclared equations, Case B input, taxonomy, pairing, Rust
boundary, thresholds, and decision conditions are logically unchanged.

Attempt 001 stopped before measured blocks because the runner used the older
three-change-region `high` calibration profile instead of the exact R1 Case B
identity. Attempt 002 completed 60 Python and 60 Rust samples but was rejected
after review because its boundary aggregate omitted Python input-write/output-
parse time and its Gate implementation did not evaluate the already-declared
unattributed maximum. Both attempts are preserved under
`reports/topology_pruning/r2-failures/` and are ineligible evidence. Neither
correction changed the taxonomy, equation, numeric thresholds, transport, or
decision outcomes.

## Python attribution result

| Candidate | Uninstrumented p50 | p95 | Same-block delta p50 | delta p95 |
|---|---:|---:|---:|---:|
| B/T0 | 19.1860 ms | 24.1589 ms | comparator | comparator |
| B/T1 | 28.0736 ms | 29.5925 ms | 8.5101 ms | 9.8610 ms |
| B/T2 | 29.2718 ms | 36.2261 ms | 9.6737 ms | 16.7763 ms |

The instrumented paired p50 was 8.4180 ms for T1 and 9.8115 ms for T2.
Exclusive stage attribution was 8.4231 ms and 9.8000 ms. The signed
unattributed remainder was -0.0028 ms and 0.0052 ms. This corresponds to
100.0606% and 99.8828% attributed, with -0.0333% and 0.0530% signed
unattributed ratios. Component p50s can exceed 100% or not add to exactly
100% because signed block components are aggregated independently; the exact
identity holds for every one of the twenty paired records.

The dominant exclusive stage deltas were:

| Candidate | Observation | Eye setup | Next material stage |
|---|---:|---:|---:|
| B/T1 | 8.4582 ms | 0.0173 ms | JSON serialization 0.0187 ms |
| B/T2 | 7.6614 ms | 2.1263 ms | receipt construction 0.0345 ms |

The empty instrumentation tree cost 21.6 microseconds p50 and 22.2
microseconds p95 and was not subtracted. Each candidate allocated and retained
16,588,800 temporary motion bytes per attributed call. Explicit pixel-copy
calls and bytes were zero. Logical reads were 45,619,200 for T0, 62,208,000
for T1, and 62,304,512 for T2. Receipt construction has two calls because the
input digest is created before observations and the final semantic receipt is
constructed afterward; every other active taxonomy stage has one call and
the explicit-copy stage has zero.

## Rust coarse-boundary result

| Candidate | Python p50 | Rust core p50 | Rust core p95 | Boundary-inclusive p50 | Boundary change |
|---|---:|---:|---:|---:|---:|
| B/T0 | 19.1860 ms | 14.7987 ms | 16.3705 ms | 15.1676 ms | 20.94% lower |
| B/T1 | 28.0736 ms | 18.6532 ms | 20.2405 ms | 19.0221 ms | 32.24% lower |
| B/T2 | 29.2718 ms | 18.3120 ms | 19.9366 ms | 18.6809 ms | 36.18% lower |

The one Rust subprocess call took 1.3868794 seconds; its internal suite took
1.3630698 seconds. Python wrapper time was 0.0049642 seconds, comprising a
0.0043158-second input write and 0.0006484-second output parse. Rust input read
was 0.0057260 seconds and its serialization probe was 0.0001190 seconds. Full
wrapper/process overhead amortized across the declared 78 baseline, warm-up,
and measured internal executions was 0.368895 ms per execution. That
amortization is benchmark infrastructure evidence, not single-call product
latency.

The 16,588,800-byte packed input was written once and read once, for
33,177,600 explicitly accounted boundary-copy bytes, exactly the fixed 2.0x
limit. The Rust output file was 61,178 bytes. Boundary temporary storage was
16,649,978 bytes. Core Rust pixel copies were zero and its dominant temporary
motion buffer was 2,073,600 bytes for T0, T1, and T2.

Python, Rust, and the immutable R1 evidence produced identical T0/T1/T2
semantic hashes. All twenty samples per candidate were deterministic.

## Decision

**`REFINE_RUST_BOUNDARY`**

Rust core and benchmark-amortized boundary-inclusive T1/T2 control-plane p50
are lower than Python, and semantic, deterministic, and copy gates pass.
However, the fixed `RUST_RUNTIME_VIABLE` rule also requires a collected
in-process FFI measurement. R2 intentionally used a subprocess transport, so
FFI duration remains `null/not_collected`. The next bounded step is one
in-process shared-buffer boundary that keeps the same Case B, topology,
semantic, copy, and threshold contracts. This result does not authorize a
model integration or a backend/product speedup claim.

## Explicit zero-execution boundaries

- H3 API calls: 0;
- API-key use: 0;
- paid API runs: 0;
- model downloads: 0;
- model loads: 0;
- CUDA runs: 0.

## Final model-free validation

- Python compile: passed;
- Python unit tests: 119 passed;
- Rust format and locked workspace check: passed;
- Rust locked workspace tests: passed, including 9 runtime tests;
- repository JSON parsing: 34 files passed;
- immutable v1/R1 Git-blob checks: 16 passed;
- evidence sample, paired-equation, parity, unsupported-FFI, and decision
  regression checks: passed;
- `git diff --check`: passed.
