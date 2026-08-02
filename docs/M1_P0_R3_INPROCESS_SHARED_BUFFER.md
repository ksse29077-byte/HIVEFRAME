# M1-P0-R3 In-process Shared-buffer Boundary

Status: predeclared; measurement pending

## Purpose

R2 showed lower Rust core cost but used a subprocess and two full input-buffer
copies. Its Gate was `REFINE_RUST_BOUNDARY`. R3 replaces only that transport
with one bounded in-process call. It does not add a corpus, topology, backend,
model, CUDA path, or speedup claim.

Compound Perception First remains the product direction. Mono is the T0
comparator and safety fallback, not the default product architecture.

## Fixed experiment

- existing synthetic Case B only: packed uint8 `[8, 1080, 1920]`;
- T0 Mono, T1 global plus fixed 2x2, T2 global plus motion-focused;
- seed 101;
- 5 warm-up blocks and 30 measured paired blocks;
- one Python reference execution and one Rust in-process execution per
  candidate in deterministic rotating order;
- same process, same NumPy sequence object, same block;
- no independent median subtraction.

The predeclared contract is
[`../reports/topology_pruning/r3/predeclared-boundary-contract.json`](../reports/topology_pruning/r3/predeclared-boundary-contract.json).

## Python and Rust compatibility

The adapter is pinned to PyO3 0.29.0 and `abi3-py312`. PyO3 0.29.0 requires
Rust 1.83; the checked toolchain is Rust 1.97.1. The measurement runtime must
be CPython 3.12. The adapter does not use the NumPy C API, so its Rust boundary
depends only on the Python buffer protocol.

PyO3 and its PyO3 subcrates are dual-licensed MIT or Apache-2.0. Every new
direct/transitive version and license is recorded in the R3 config and locked
in `Cargo.lock`. `target-lexicon` uses Apache-2.0 with LLVM exception;
`unicode-ident` additionally carries Unicode-3.0 terms. No alternate FFI
technology is admitted in R3.

## Buffer and lifetime contract

Python creates the existing Case B NumPy array, marks it non-writeable, and
exports one read-only C-contiguous memory view. The PyO3 adapter checks:

- three dimensions and exact shape `[8, 1080, 1920]`;
- uint8-compatible item size and exact byte length;
- C contiguity and read-only status;
- candidate is exactly T0, T1, or T2.

The exporting object and `PyBuffer` remain alive for the whole call. The GIL
is held throughout; neither side mutates the input. The adapter uses one
audited representation cast after all buffer checks. It does not allocate or
copy an input buffer, create a file, start a subprocess, or invoke Python per
Eye. No address is serialized.

## Ownership boundary

Rust owns input validation after buffer acquisition, Eye contract
construction, routing, coordinates, observation, Fusion, SharedVisualState,
ComputePlan, semantic hashing, and compact receipt counters. Python owns the
benchmark loop and reference implementation. Model tensors, VAE, denoising,
attention/scheduler hooks, model evaluation, and every backend remain outside
R3.

The hot path returns a compact Python mapping: semantic and input hashes,
Eye/region/plan counts, copy and temporary counters, and timing spans. It does
not return pixels or the complete repeated semantic payload. JSON is used only
after the measured suite to write public reports.

## Timing and accounting

Python measures the outer reference call. The Rust side separates buffer
acquisition, argument validation, Rust core, output marshal, and complete Rust
function span. Python also records the complete extension wrapper span. The
signed FFI enter/exit residual is the wrapper span minus the Rust function
span; it is never silently removed.

An empty extension call is measured separately and never subtracted. Input
copy bytes, subprocesses, temporary files, FFI call count, and dominant Rust
pixel-temporary bytes are explicit. Allocation count is `null/not_collected`
with a reason because the global allocator is not instrumented.

## Predeclared Gate

`RUST_CONTROL_PLANE_ADMITTED` requires all of the following:

- T1 and T2 p50 at least 20% below Python;
- T1 and T2 p95 no worse than Python;
- T0 p50 regression no more than 5%;
- FFI residual plus buffer acquisition plus output marshal no more than 10%
  of Rust boundary time;
- zero input-copy bytes, subprocesses, and temporary files;
- exact R1/Python/Rust semantic parity and deterministic hashes;
- no unsupported value treated as zero.

Other allowed decisions are `REFINE_SHARED_BUFFER_BOUNDARY`,
`OPTIMIZE_OUTPUT_MARSHAL`, and `PAUSE_CURRENT_INPROCESS_ADAPTER`. None means
abandoning Compound Perception First or selecting Mono first. No R4 follows
without separate approval.

## Evidence boundary

The measurement has not yet run. H3 API calls, API-key uses, paid runs,
customer data uses, model downloads, model loads, CUDA runs, Wan runs, and LTX
runs are zero. R3 cannot claim official product or model speedup.
