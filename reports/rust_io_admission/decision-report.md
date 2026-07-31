# Rust I/O Admission Decision

Decision: **CONDITIONAL_ADMIT**

This is a model-free control-plane admission result. It is not a Wan, GPU, quality, or commercial speedup claim.

## Execution contract

- warm-ups: 5
- measured repetitions: 30
- input generation and process startup: excluded from core spans
- Python/Rust process startup: reported separately
- model loads: 0
- CUDA runs: 0

## Core comparison

| Profile | Topology | Python p50 (ms) | Rust p50 (ms) | p50 reduction | p95 reduction | Temporary reduction |
|---|---|---:|---:|---:|---:|---:|
| high | mono_1x1 | 18.238 | 14.364 | 21.24% | 35.56% | 87.50% |
| high | motion_focused | 30.587 | 18.819 | 38.47% | 59.05% | 87.50% |
| high | overlap_2x2 | 26.786 | 17.900 | 33.17% | 34.54% | 87.50% |
| high | uniform_2x2 | 26.006 | 17.613 | 32.27% | 36.24% | 87.50% |
| high | uniform_4x4 | 26.691 | 17.600 | 34.06% | 40.96% | 87.50% |
| low | mono_1x1 | 3.950 | 3.203 | 18.91% | 43.29% | 93.75% |
| low | motion_focused | 5.617 | 3.807 | 32.22% | 33.50% | 93.75% |
| low | overlap_2x2 | 5.963 | 3.897 | 34.64% | 34.87% | 93.75% |
| low | uniform_2x2 | 5.647 | 3.810 | 32.53% | 33.60% | 93.75% |
| low | uniform_4x4 | 5.895 | 3.860 | 34.51% | 41.55% | 93.75% |
| medium | mono_1x1 | 15.375 | 11.832 | 23.04% | 39.55% | 93.75% |
| medium | motion_focused | 22.651 | 14.760 | 34.83% | 42.05% | 93.75% |
| medium | overlap_2x2 | 22.208 | 14.460 | 34.89% | 49.25% | 93.75% |
| medium | uniform_2x2 | 21.341 | 14.517 | 31.97% | 32.91% | 93.75% |
| medium | uniform_4x4 | 22.523 | 14.440 | 35.89% | 46.84% | 93.75% |

## Gate rationale

Core orchestration parity and at least one performance admission threshold passed, but PyO3/FFI, shared-buffer, backend, and end-to-end impact remain unmeasured.

The result cannot become `ADMIT` until process/FFI overhead and the candidate pipeline's attributable share of accepted-result end-to-end cost are measured.
