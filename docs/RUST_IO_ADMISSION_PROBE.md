# Rust I/O Admission Probe

Status: model-free evidence complete; decision `CONDITIONAL_ADMIT`

## Research question

Does a Rust implementation of Compound I/O input profiling, Eye routing,
coordinate transforms, observation, Sensory Fusion, and backend-neutral
ComputePlan construction preserve Python semantics while reducing
orchestration cost?

This probe does not replace the Python reference or M0 RunReceipt. It does not
execute Wan/LTX, a backend selector, PyO3, CUDA, or a model.

## Compared paths

| Path | Responsibility |
|---|---|
| `python/hive_probes/rust_io_reference.py` | NumPy/Python semantic and timing reference |
| `python/hive_benchmarks/rust_io_admission.py` | isolated-process runner, parity comparison, gate decision |
| `crates/hive-retina-runtime` | Rust routing, observation, fusion, plan, and receipt candidate |

Both implementations create and reuse the same deterministic packed `uint8`
grayscale sequence. Input generation is outside the core pipeline span. Exact
integer fields must match; floating-point fields use tolerance `1e-9`.
Semantic SHA-256 values matched exactly in the measured suite.

## Benchmark environment

- Windows 11 Pro `10.0.26200`, 64-bit;
- AMD Ryzen 5 9600X, 6 cores / 12 logical processors;
- approximately 61.6 GiB visible system RAM;
- Python 3.12.9 and NumPy 2.4.4;
- Rust/Cargo 1.97.1;
- Rust binary built with the `release` profile;
- one Python worker process and one Rust worker process, executed
  sequentially;
- model loads: 0;
- CUDA runs: 0.

No CPU affinity or exclusive-host reservation was applied. These results are
admission evidence on this environment, not universal product performance.

## Inputs and topology

| Profile | Resolution | Frames | Packed input |
|---|---:|---:|---:|
| Low | 640×384 | 16 | 3,932,160 bytes |
| Medium | 1280×720 | 16 | 14,745,600 bytes |
| High | 1920×1080 | 8 | 16,588,800 bytes |
| Extended | 3840×2160 | 4 | skipped; optional and not needed for the default decision |

Every measured profile used seed `101` and:

- `mono_1x1` — one full-scene writable Eye;
- `uniform_2x2` — one global context Eye plus four regional Eyes;
- `uniform_4x4` — one global context Eye plus sixteen regional Eyes;
- `overlap_2x2` — one global Eye plus four halo-expanded regional Eyes;
- `motion_focused` — global, motion detector, and focused regional Eyes.

The overlap topology uses bounded write scopes inside larger receptive fields.
Motion-focused routing includes the frame-difference scan in routing cost.

## Method

- warm-up runs per case: 5;
- measured repetitions per case: 30;
- total measured cases: 15;
- p50/p95: nearest-rank latency;
- Python interpreter and Rust process startup: outside core spans and measured
  separately;
- compilation: completed before the benchmark and recorded as `uncollected`;
- input generation: outside core spans;
- each measured repeat validates the deterministic semantic hash.

Command:

```powershell
cargo build -p hive-retina-runtime --release --locked
python python/hive_benchmarks/rust_io_admission.py `
  --rust-binary target/release/hive-retina-runtime.exe `
  --output-dir reports/rust_io_admission `
  --profiles low medium high `
  --topologies mono_1x1 uniform_2x2 uniform_4x4 overlap_2x2 motion_focused `
  --seed 101 --warmups 5 --repetitions 30
```

## Parity result

All 15 cases passed:

- Eye count and IDs;
- receptive and write-scope coordinates;
- overlap and local-to-global transforms;
- motion bounds and changed-pixel summaries;
- checksums and dirty/stable/uncertain classification;
- observation provenance and Fusion sources;
- ComputePlan actions and scopes;
- unsupported metric null/status/reason/method semantics;
- deterministic semantic SHA-256.

See
[`parity-report.json`](../reports/rust_io_admission/parity-report.json).

## Core latency result

Positive reduction means the Rust core span was lower.

| Profile | Topology | Python p50 ms | Rust p50 ms | p50 reduction | p95 reduction | temporary reduction |
|---|---|---:|---:|---:|---:|---:|
| Low | mono_1x1 | 3.950 | 3.203 | 18.91% | 43.29% | 93.75% |
| Low | uniform_2x2 | 5.647 | 3.810 | 32.53% | 33.60% | 93.75% |
| Low | uniform_4x4 | 5.895 | 3.860 | 34.51% | 41.55% | 93.75% |
| Low | overlap_2x2 | 5.963 | 3.897 | 34.64% | 34.87% | 93.75% |
| Low | motion_focused | 5.617 | 3.807 | 32.22% | 33.50% | 93.75% |
| Medium | mono_1x1 | 15.375 | 11.832 | 23.04% | 39.55% | 93.75% |
| Medium | uniform_2x2 | 21.341 | 14.517 | 31.97% | 32.91% | 93.75% |
| Medium | uniform_4x4 | 22.522 | 14.440 | 35.89% | 46.84% | 93.75% |
| Medium | overlap_2x2 | 22.208 | 14.460 | 34.89% | 49.25% | 93.75% |
| Medium | motion_focused | 22.651 | 14.760 | 34.83% | 42.05% | 93.75% |
| High | mono_1x1 | 18.238 | 14.364 | 21.24% | 35.56% | 87.50% |
| High | uniform_2x2 | 26.006 | 17.613 | 32.27% | 36.24% | 87.50% |
| High | uniform_4x4 | 26.691 | 17.600 | 34.06% | 40.96% | 87.50% |
| High | overlap_2x2 | 26.786 | 17.900 | 33.17% | 34.54% | 87.50% |
| High | motion_focused | 30.587 | 18.819 | 38.47% | 59.05% | 87.50% |

The Low Mono p50 improvement did not reach 20%, although its p95 and temporary
buffer gates passed. Rust is not forced for Mono or low-cost inputs; topology
and runtime selection remain evidence-driven.

External worker time was 9.994 seconds for Python and 6.430 seconds for Rust.
These are whole-suite process measurements, not product end-to-end latency.

## Representative stage and memory accounting

Medium `uniform_2x2`, mean per measured repeat:

| Metric | Python | Rust |
|---|---:|---:|
| Total core wall | 21.518 ms | 14.592 ms |
| Routing | 0.026 ms | 0.002 ms |
| Coordinate transform | 0.003 ms | <0.001 ms |
| Observation | 14.063 ms | 8.830 ms |
| Fusion | 0.022 ms | 0.003 ms |
| Compute plan | 0.008 ms | 0.002 ms |
| Logical bytes read | 54.49 MiB | 54.49 MiB |
| Explicit pixel-buffer copies | 0 | 0 |
| Dominant temporary buffers | 14.06 MiB | 0.88 MiB |

Python peak RSS is a process high-water mark, not a per-case isolated peak.
Rust peak RSS is `uncollected`; allocation count is `unsupported`. Rust process
CPU time and sampled thread count are also `uncollected`. No unsupported value
is represented as zero.

## Dependencies

The workspace previously had no JSON or digest dependency suitable for this
crate.

| Direct dependency | Purpose | License |
|---|---|---|
| `serde` | typed deterministic interchange structures | MIT OR Apache-2.0 |
| `serde_json` | benchmark and semantic JSON | MIT OR Apache-2.0 |
| `sha2` | deterministic semantic SHA-256 | MIT OR Apache-2.0 |

`Cargo.lock` records direct and transitive versions. No async framework, video
codec, GPU, or model dependency was added.

## Admission decision

**`CONDITIONAL_ADMIT`**

Required parity and determinism gates passed. At least one representative
workload exceeded the p50 or p95 threshold, and every case reduced dominant
temporary-buffer accounting by more than 25%.

The result is conditional because the probe did not measure:

- PyO3 or other FFI process/buffer cost;
- DLPack or zero-copy tensor exchange;
- the candidate pipeline's attributable share of M0 end-to-end time;
- backend selector execution or reduced model work;
- GPU kernels, Wan speed, quality, or commercial value.

M0 lacks an eligible isolated input-orchestration span, so estimated Wan
end-to-end gain remains `null/uncollected`.

## Next exact step

Do not rewrite the Python model plane. First complete the M1 rights-cleared
clip/oracle cost surface. In parallel, a separate approved probe may add one
bounded shared-buffer/PyO3 boundary for this crate and measure:

1. Python→Rust call and buffer handoff;
2. semantic parity on recorded M1 inputs;
3. process/FFI overhead;
4. whether the core gain survives in the attributable end-to-end control-plane
   span.

Only that evidence can decide whether Rust becomes the production control
plane.
