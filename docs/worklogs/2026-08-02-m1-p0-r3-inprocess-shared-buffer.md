# 2026-08-02 — M1-P0-R3 In-process Shared-buffer Boundary

Status: verified; decision `RUST_CONTROL_PLANE_ADMITTED`

## Verified predecessor state

- PR #43 merged into `main` at
  `77cd34d3958bef28bfa6e3b8da1b03df2e44c503`;
- Issue #42 closed through the merge;
- sanitized R2 reports, both ineligible failed attempts, logical-equivalence
  evidence, worklog, and regression tests are present on `main`;
- R2 decision remains `REFINE_RUST_BOUNDARY`;
- Compound Perception First remains explicit and Mono remains only comparator
  and safety fallback.

R3 uses Issue [#44](https://github.com/ksse29077-byte/HIVEFRAME/issues/44)
and branch `agent/m1-p0-r3-inprocess-shared-buffer`. Main was not edited
directly.

## Predeclared implementation

The adapter is one PyO3 0.29.0 `abi3-py312` extension call per Case B
candidate. It borrows one read-only, packed, C-contiguous uint8 buffer. Rust
performs the whole Eye topology, Fusion, SharedVisualState, ComputePlan, hash,
and compact receipt path. Per-Eye calls, input copies, subprocesses, temporary
files, input JSON, repeated semantic payloads, and public addresses are
forbidden.

The checked environments are CPython 3.12.9 with NumPy 2.4.4 and Rust 1.97.1.
PyO3 requires Rust 1.83. Direct and transitive versions and licenses are
recorded in the committed config and lock file. No system Python, WSL,
driver, model, or CUDA environment was changed.

Measurement is fixed at synthetic Case B T0/T1/T2, seed 101, five warm-ups,
and thirty same-process paired blocks. Candidate and implementation order are
deterministic and rotating. The Gate thresholds and four allowed decisions
are fixed before results.

## Premeasurement boundary

Commit `3abbbeafd370bd176472aaf7f506dee1bec4ee79` bound the config,
adapter, runner, tests, and predeclared receipt before measurement. Its
contract SHA-256 was
`f0d7b85df9bbc7d8381d5b6b493fe6765f2f7b15b95abf1e1c76642987b688e2`.
The model-free plan returned `execution_started=false` before the exact hash
was supplied.

## Measured result

The measurement command ran once. It produced 90 pairs: 30 each for Case B
T0/T1/T2 after five warm-up blocks. All executions stayed in one CPython
3.12.9 process and shared the same read-only NumPy 2.4.4 sequence object.

| Candidate | Python p50/p95 | Rust boundary p50/p95 | p50 reduction | boundary fraction |
|---|---:|---:|---:|---:|
| T0 | 18.8026 / 23.6652 ms | 14.8912 / 17.2905 ms | 20.80% | 0.189% |
| T1 | 27.2803 / 37.6603 ms | 18.7658 / 21.7417 ms | 31.21% | 0.165% |
| T2 | 28.7248 / 32.9490 ms | 18.3897 / 21.4844 ms | 35.98% | 0.164% |

Semantic parity and deterministic R1 hashes passed for every pair. Input-copy
bytes, subprocesses, temporary files, and per-Eye FFI calls were zero; there
was exactly one FFI call per candidate. Dominant Rust motion-temporary storage
was 2,073,600 bytes per candidate. Allocation count is explicitly
`null/not_collected` with reason and method.

The empty boundary calibration measured 0 seconds p50 and 0.4 microseconds
p95 at clock resolution and was never subtracted. JSON was absent from the hot
path. The independent audit recomputed 1,348 assertions with zero failures.

Gate: **`RUST_CONTROL_PLANE_ADMITTED`**. This closes the bounded runtime
question and makes M1-P0 closable. It is not a real-video or product speedup
claim; the next separately approved research step is M1 Eye Topology Ground
Truth Lab, not R4.

## Final validation

- CPython 3.12 extension release build and import: passed;
- PyO3 version/ABI: `0.29.0` / `abi3-py312`;
- Python compile: passed;
- full Python tests: 140 passed;
- Python 3.12 R3 tests: 14 passed;
- Rust formatting: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 10 runtime tests;
- all 40 repository JSON files parsed;
- independent R3 arithmetic/evidence audit: 1,348 assertions, 0 failures;
- v1/R1/R2 immutable evidence tests: passed;
- public absolute-path, credential-pattern, address, and repeated semantic
  payload scans: passed;
- `git diff --check`: passed.

## Execution boundary

- H3 API calls: 0;
- API-key uses: 0;
- paid runs: 0;
- customer data uses: 0;
- model downloads: 0;
- model loads: 0;
- CUDA runs: 0;
- Wan runs: 0;
- LTX runs: 0.
