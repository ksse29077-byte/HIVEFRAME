# M1-P0-R1 Same-run Mono Normalization Decision

Decision: **REFINE_COST_MODEL**

Paired prediction error or ranking still fails the predeclared rule.

This is a backend-neutral model-free pre-gate refinement. It does not close M0 or M1 and is not a model, GPU, quality, product, or commercial speedup claim.

## Paired delta validation

| Candidate | Predicted delta ms | Measured p50 ms | Measured p95 ms | Relative error |
|---|---:|---:|---:|---:|
| T1 | 3.249300 | 8.512000 | 15.568300 | 61.83% |
| T2 | 4.455100 | 10.265000 | 11.993200 | 56.60% |

Predicted ranking: `T0 < T1 < T2`.

Measured ranking: `T0 < T1 < T2`.

Ranking match: `true`.

Dirty recall minimum: `1.000000`.

False-stable maximum: `0.000000`.

Amdahl status: `partially_available`; no end-to-end bound is asserted.

H3 API calls: 0.

Paid API runs: 0.

Model downloads: 0.

Model loads: 0.

CUDA runs: 0.
