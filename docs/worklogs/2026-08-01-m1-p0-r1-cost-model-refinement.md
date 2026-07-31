# 2026-08-01 — M1-P0-R1 Same-run Mono Cost Normalization

Status: model-free refinement verified; Draft PR review pending

## Repository and publication state

- PR #38: merged;
- PR #38 merge commit and R1 base `main`:
  `ad091add498e5c8ec68b4cc5a03937c4d3d3cb62`;
- Issue #37: closed through PR #38;
- R1 Issue:
  [#40](https://github.com/ksse29077-byte/HIVEFRAME/issues/40);
- branch: `agent/m1-p0-r1-cost-model-refinement`;
- Draft PR:
  [#41](https://github.com/ksse29077-byte/HIVEFRAME/pull/41), open, Draft,
  and not merged;
- original predeclaration commit:
  `885a3b6d27cc5514920928a90bb049c7ff66b4c7`;
- corrected final pre-measurement commit:
  `0236aa9a5be64896676f6e2b68cafc53e4c646c9`;
- R1 result commit:
  `2897124a7434f7d5df4109698c508e69bcd025e4`;
- evidence documentation: this commit.

## Preserved v1 evidence

The seven v1 config, design, worklog, and report files were verified against
predeclared SHA-256 values before and after R1. No v1 report, receipt,
threshold, or `REFINE_COST_MODEL` decision was modified.

R1 retained exactly A/T0, B/T0, B/T1, B/T2, and C/T0. A/T1, A/T2, C/T1, and
C/T2 remain analytically pruned. No topology, case, or corpus was added.

## Predeclared model and coefficient source

```text
C_observed(T) =
  C_session_fixed
  + C_case_shared
  + C_topology_variable(T)
  + C_measurement_noise

Delta_C_measured(T, i) =
  C_measured(T, i) - C_measured(T0, paired_i)

Delta_C_predicted(T) =
  C_predicted(T) - C_predicted(T0)
```

Topology-variable cost includes Eye setup, routing, coordinate transform,
observation, overlap, Fusion, planning, logical bytes, copied bytes, and
temporary bytes. Prediction coefficients are the immutable v1 Case B
`S_required` values, derived from merged Rust I/O p50 and stage means.

Generation, audit, recovery, H3, GPU-kernel, complete process/FFI, and
end-to-end product costs remain unavailable. They were not replaced with
zero.

## Pairing and execution

- one Python process;
- one prepared NumPy sequence object per case reused throughout;
- deterministic seed 101;
- five warm-up blocks;
- twenty measured blocks;
- one sample for each retained combination per block;
- Case B order selected by SHA-256 of seed, phase, block, and candidate;
- every B/T1 and B/T2 sample paired to the B/T0 sample in the same block;
- 100 final measured samples;
- independent median subtraction forbidden.

## Failure and correction

Attempt 1 completed 20 measured blocks but stopped before result publication.
The unavailable-metric validator treated the Amdahl aggregate status
`partially_available` as a leaf metric. The failed predeclared model and error
receipt are preserved in `reports/topology_pruning/r1-failures/attempt-001/`
and are ineligible as R1 results.

The correction recognizes unavailable leaf metrics only when the object has a
`value` field. It did not change the cost equation, coefficient sources,
paired method, execution order, 35% threshold, or Gate rules. Nineteen R1
tests and all 107 Python tests passed before the final attempt.

## Final paired result

| Candidate | Predicted delta | Measured p50 | Measured p95 | Absolute error | Relative error |
|---|---:|---:|---:|---:|---:|
| B/T1 | 3.2493 ms | 8.5120 ms | 15.5683 ms | 5.2627 ms | 61.83% |
| B/T2 | 4.4551 ms | 10.2650 ms | 11.9932 ms | 5.8099 ms | 56.60% |

For comparison, the v1 absolute-total relative errors were 31.03% for B/T1
and 35.36% for B/T2. The v1 and R1 errors target different quantities, so the
increase does not mean total execution regressed. It shows that same-block
normalization alone does not calibrate the Rust-derived incremental prediction
to the locally paired Python topology delta.

Predicted and measured rankings both equal `T0 < T1 < T2`. Dirty recall is
1.0, maximum false-stable is 0.0, semantic hashes are deterministic and equal
to v1, and copied bytes are 0 for every retained combination.

## Amdahl and break-even status

Amdahl remains `partially_available`. The M0 input/orchestration fraction and
end-to-end upper bound are unavailable. Measured model-free Case B additional
cost is 8.5120 ms p50 for T1 and 10.2650 ms p50 for T2. No admitted backend
generation saving exists to establish realized break-even or product speedup.

## Decision

**`REFINE_COST_MODEL`**

Both decision-bearing paired relative errors exceed the unchanged 35% limit.
Ranking and safety pass, but `PROCEED_TO_COST_SURFACE` is blocked. The result
does not close M0, M1-P0, or M1.

## Verification

- Python compile: passed;
- Python unittest: 107 passed;
- Rust format check: passed;
- Rust locked workspace check: passed;
- Rust locked workspace tests: passed, including 8 runtime tests;
- all repository JSON files parse: passed;
- `git diff --check`: passed;
- v1 SHA-256 invariance: passed;
- public-path and credential-pattern scan: passed.

H3 API calls: 0.

API-key uses: 0.

Paid API runs: 0.

Model downloads: 0.

Model loads: 0.

CUDA runs: 0.

Wan evidence changes: 0.

LTX activation changes: 0.

## Unproven and next action

Still unproven:

- attributable missing Python topology-variable stages;
- process/FFI/shared-buffer cost;
- backend generation savings;
- quality parity;
- rights-cleared corpus behavior;
- complete-cost break-even and end-to-end gain;
- H3 runtime admission or capability.

Do not expand to the M1 Cost Surface from this result. A further refinement
requires a separate predeclared hypothesis that isolates the missing Python
topology-variable cost instead of refitting R1 after observing its result.
