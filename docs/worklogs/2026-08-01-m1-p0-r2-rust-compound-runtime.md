# 2026-08-01 — M1-P0-R2 Python Attribution and Rust Compound Runtime

Status: model-free refinement verified; Draft PR publication pending

## Repository and GitHub state

- PR #41: merged;
- PR #41 merge commit and R2 base `main`:
  `e5bbaa751d7c449dd0c5a7ad3b7fff18bd661388`;
- Issue #40: closed as completed;
- R1 report, failed attempt evidence, and worklog: present on `main`;
- R2 Issue:
  [#42](https://github.com/ksse29077-byte/HIVEFRAME/issues/42);
- branch: `agent/m1-p0-r2-rust-compound-runtime`;
- original predeclaration commit:
  `f5b333dc716ec3175cc6601c255660c95a25affd`;
- exact Case B corrective commit:
  `dc1656ae088377206043444d58ef2d49297c5c99`;
- rewritten measurement-accounting and public-serialization commit:
  `bf1b90d6c0b35a5aad3a72d6f9f3534a9792b973`.

## Boundary and preserved evidence

Compound Perception First remains the product direction. Mono is the Case B
control and fallback only. R2 is not a decision to abandon compound input.

Sixteen v1/R1 config, design, worklog, success, failure, and Gate artifacts
are pinned by normalized Git-blob SHA-256 and validated before and after the
run. No historical report, receipt, threshold, or Gate was rewritten.

The only measured combinations were B/T0, B/T1, and B/T2. Each path used seed
101, one prepared Case B input, five warm-up blocks, and twenty measured
blocks. No new corpus, topology, or previously pruned combination was run.

## Predeclared attribution

The fixed stage taxonomy contains input validation, Eye contract, Eye setup,
routing, coordinate transform, mask and view work, allocation/copy,
observation, overlap, Fusion conversion/Fusion, SharedVisualState,
ComputePlan, receipt, JSON, and garbage collection.

Nested `time.perf_counter_ns` spans report inclusive and exclusive time. The
empty instrumentation tree is measured separately. No timing is silently
subtracted. Independent median subtraction is forbidden; every candidate uses
the Mono sample in the same deterministic block.

The per-block equation is:

```text
paired delta
  = sum(exclusive stage candidate-minus-Mono deltas)
  + signed unattributed candidate-minus-Mono remainder
```

All twenty records per candidate satisfied the identity. Per-run
unattributed duration was nonnegative. The paired remainder may be signed.

## Python result

| Candidate | p50 | p95 | paired delta p50 | paired delta p95 |
|---|---:|---:|---:|---:|
| T0 | 19.1860 ms | 24.1589 ms | comparator | comparator |
| T1 | 28.0736 ms | 29.5925 ms | 8.5101 ms | 9.8610 ms |
| T2 | 29.2718 ms | 36.2261 ms | 9.6737 ms | 16.7763 ms |

Instrumented paired p50 was 8.4180 ms and 9.8115 ms. The exclusive attributed
component was 8.4231 ms and 9.8000 ms; signed unattributed remainder was
-0.0028 ms and 0.0052 ms. Attribution ratios were 100.0606% and 99.8828%.
The component medians need not sum to exactly 100%, although each raw block
identity is exact.

Dominant p50 stage deltas:

- T1 observation: 8.4582 ms;
- T2 observation: 7.6614 ms;
- T2 Eye setup: 2.1263 ms;
- every other absolute p50 stage delta: below 0.035 ms.

Instrumentation calibration was 21.6 microseconds p50 and 22.2 microseconds
p95. Each candidate allocated 16,588,800 motion-temporary bytes. Explicit
pixel-copy call count and bytes were zero. JSON output was 1,847 bytes for T0,
6,083 for T1, and 3,491 for T2. Receipt construction was called twice; all
other active stages once.

## Rust coarse-boundary result

| Candidate | Rust core p50 | Rust core p95 | boundary p50 | Python-relative boundary change |
|---|---:|---:|---:|---:|
| T0 | 14.7987 ms | 16.3705 ms | 15.1676 ms | 20.94% lower |
| T1 | 18.6532 ms | 20.2405 ms | 19.0221 ms | 32.24% lower |
| T2 | 18.3120 ms | 19.9366 ms | 18.6809 ms | 36.18% lower |

One Python wrapper handed one 16,588,800-byte packed buffer to one Rust
subprocess. Rust internally executed all baseline, warm-up, and measured
topologies and returned small semantic/plan/receipt JSON. There were no
per-Eye round trips.

- external process call: 1.3868794 seconds;
- Rust internal suite: 1.3630698 seconds;
- Python input write: 0.0043158 seconds;
- Python output parse: 0.0006484 seconds;
- Python wrapper total: 0.0049642 seconds;
- Rust input read: 0.0057260 seconds;
- Rust serialization probe: 0.0001190 seconds;
- full wrapper/process amortization: 0.368895 ms per 78 internal executions;
- FFI: `null/not_collected` with reason and method.

The amortization is benchmark-suite scope, not a single product call.

Boundary copy accounting:

- Python full-buffer write: 16,588,800 bytes;
- Rust full-buffer read copy: 16,588,800 bytes;
- total: 33,177,600 bytes, exactly 2.0 input-buffer equivalents;
- Rust core pixel copies: 0;
- Rust dominant temporary motion buffer: 2,073,600 bytes per candidate;
- Rust output file: 61,178 bytes;
- boundary temporary files: 16,649,978 bytes.

## Parity and decision

T0/T1/T2 Python and Rust semantic hashes exactly matched the immutable R1
hashes. All candidate hashes were deterministic. Copy accounting passed the
fixed 2.0x maximum.

Decision: **`REFINE_RUST_BOUNDARY`**.

Rust core and suite-amortized boundary results are favorable for T1 and T2,
but `RUST_RUNTIME_VIABLE` predeclared collected FFI evidence as mandatory.
The current subprocess probe cannot supply it. The exact next runtime step is
a bounded in-process shared-buffer transport under the same Case B, semantic,
copy, and threshold contract. This is not permission to integrate a model or
claim backend/product speedup.

## Preserved ineligible attempts

Attempt 001 stopped during Python warm-up before measured blocks because the
old three-region `high` calibration identity was used. Attempt 002 produced
60+60 samples but its aggregate omitted Python wrapper time and did not apply
one declared threshold. Both are preserved and marked `results_eligible=false`.
The fixes changed no taxonomy, equation, numeric threshold, transport, or
allowed decision set.

## Verification and execution counts

Final model-free validation:

- Python compile: passed;
- Python unit tests: 119 passed;
- Rust formatting check: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 9 runtime tests;
- all 34 repository JSON files parsed;
- all sixteen immutable v1/R1 Git-blob checks passed;
- all forty paired T1/T2 equations and both 60-sample evidence sets passed
  the committed evidence regression test;
- `git diff --check`: passed;
- local-path and credential-pattern scan of the new public artifacts: passed.

The first sandboxed Python validation attempts collected all 119 tests but
could not write inside dynamically created temporary directories. The same
unchanged suite passed outside that filesystem sandbox. This was a validation
environment permission failure, not a repository test failure.

- H3 API calls: 0;
- API-key uses: 0;
- paid API runs: 0;
- model downloads: 0;
- model loads: 0;
- CUDA runs: 0;
- Wan changes: 0;
- LTX activation: 0.

## Next action

Review this evidence in a Draft PR. Do not advance M0, M1, H3 admission, or
backend integration from R2. If separately approved, predeclare one in-process
shared-buffer boundary and replace the missing FFI metric without changing the
Case B semantic and copy controls.
