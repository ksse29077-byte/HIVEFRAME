# M1-P0-R1 Same-run Mono Cost Normalization

Status: model-free measurement complete; decision `REFINE_COST_MODEL`

Issue: [#40](https://github.com/ksse29077-byte/HIVEFRAME/issues/40)

Base and PR #38 merge commit:
`ad091add498e5c8ec68b4cc5a03937c4d3d3cb62`.

## Purpose and boundary

R1 tests one explanation for the v1 absolute timing error: independently
measured topology and Mono medians may contain different fixed, shared, and
warm-state costs. R1 pairs every retained Case B topology sample with the T0
Mono sample from the same process, prepared input, and repetition block.

This is still a model-free M1-P0 pre-gate. It does not close M0 or M1, admit
H3, alter Wan evidence, reactivate LTX, or claim model, GPU, quality, product,
commercial, or end-to-end speedup.

## Immutable v1 evidence

The v1 reports, receipts, threshold, and `REFINE_COST_MODEL` Gate remain
unchanged. Their SHA-256 values are fixed in
`configs/m1-p0-r1.same-run-mono-normalization.json` and are validated before
and after R1 measurement.

R1 retains exactly:

- A/T0;
- B/T0;
- B/T1;
- B/T2;
- C/T0.

A/T1, A/T2, C/T1, and C/T2 remain analytically pruned. No topology or corpus
is added.

## Predeclared cost model

```text
C_observed(T) =
  C_session_fixed
  + C_case_shared
  + C_topology_variable(T)
  + C_measurement_noise
```

`C_topology_variable` includes Eye setup, routing, coordinate transform,
observation, overlap, Fusion, planning, logical bytes, copied bytes, and
temporary bytes. Generation, audit, recovery, H3, GPU-kernel, and complete
end-to-end costs remain unavailable.

```text
Delta_C_measured(T, i) =
  C_measured(T, i) - C_measured(T0, paired_i)

Delta_C_predicted(T) =
  C_predicted(T) - C_predicted(T0)
```

The prediction coefficients are the immutable Case B T1/T2 `S_required`
values in the v1 analytical model. Those values derive from the merged Rust
I/O p50 and stage means. R1 does not refit them after observing R1 results.

## Pairing and execution order

- one process for the entire R1 run;
- one generated NumPy sequence object per case, reused throughout;
- five warm-up blocks;
- twenty measured blocks;
- exactly one A/T0, B/T0, B/T1, B/T2, and C/T0 execution per block;
- Case B T0/T1/T2 order is the ascending SHA-256 order of
  `(seed, phase, block, candidate)`;
- each B/T1 and B/T2 delta uses the single B/T0 control in that same block;
- independent median subtraction is forbidden.

This deterministic interleaving makes each compound sample at most two Case B
executions away from its Mono control while preserving exactly twenty samples
per retained combination.

## Statistics

- nearest-rank p50 and p95 for raw combination latency;
- signed paired delta per block;
- nearest-rank paired-delta p50 and p95;
- absolute error against the paired-delta p50;
- relative error with a non-zero measured denominator;
- predicted and measured ranking using T0 delta `0` and T1/T2 paired p50;
- dirty recall, false-stable, deterministic semantic hash;
- logical, copied, and temporary bytes;
- unavailable metrics as `null` with status, reason, and method.

## Fixed threshold and Gate rules

The v1 35% threshold is unchanged.

`PROCEED_TO_COST_SURFACE` requires all of:

- B/T1 and B/T2 paired-p50 relative error at or below 35%;
- predicted and measured ranking match;
- dirty recall 1.0;
- false-stable 0.0;
- deterministic semantic hashes matching v1;
- unavailable values remain `null`.

`REFINE_COST_MODEL` applies when safety holds but paired error or ranking still
fails and a concrete measurable omission remains.

`MONO_FIRST` requires admitted evidence that every compound candidate is
analytically rejected or that required savings exceed an admitted downstream
opportunity. R1 cannot infer this from unavailable backend cost.

`PAUSE_COMPOUND_INPUT` applies when pairing, safety, determinism, or
unavailable-metric semantics fail.

The measurement result must select exactly one of these four decisions. The
formula, coefficient sources, order, threshold, and Gate rules may not be
changed in the evidence commit after results are observed.

## Result

The final measurement ran from pre-measurement commit
`0236aa9a5be64896676f6e2b68cafc53e4c646c9`. The original contract commit is
`885a3b6d27cc5514920928a90bb049c7ff66b4c7`.

| Candidate | Predicted delta | Measured p50 | Measured p95 | Absolute error | Relative error |
|---|---:|---:|---:|---:|---:|
| B/T1 | 3.2493 ms | 8.5120 ms | 15.5683 ms | 5.2627 ms | 61.83% |
| B/T2 | 4.4551 ms | 10.2650 ms | 11.9932 ms | 5.8099 ms | 56.60% |

- predicted ranking: `T0 < T1 < T2`;
- measured paired-delta ranking: `T0 < T1 < T2`;
- ranking match: true;
- dirty recall minimum: 1.0;
- false-stable maximum: 0.0;
- deterministic semantic hashes: stable and equal to v1;
- copied bytes: 0 for every retained combination;
- Amdahl status: `partially_available`; no end-to-end bound;
- final Gate: `REFINE_COST_MODEL`.

Same-block normalization did not explain the v1 calibration gap. For the two
decision-bearing Case B candidates, v1 absolute relative error was 31.03% and
35.36%, while R1 paired-delta error was 61.83% and 56.60%. This comparison
uses different declared targets—absolute total in v1 and paired topology delta
in R1—so it does not mean total runtime regressed. It means the v1 Rust-derived
incremental coefficients underpredict the locally paired Python topology
overhead.

The first R1 attempt completed its measurement loop but failed before result
publication because the validator mistook the aggregate Amdahl
`partially_available` status for a leaf metric. The failed attempt and its
predeclared model are preserved under `reports/topology_pruning/r1-failures/`.
The correction only restricted leaf-metric detection to objects with a
`value` field. It did not change the cost equation, coefficients, execution
order, 35% threshold, or Gate rules.

## Output contract

R1 writes only:

- `reports/topology_pruning/r1/predeclared-model.json`;
- `reports/topology_pruning/r1/paired-normalization-results.json`;
- `reports/topology_pruning/r1/prediction-validation.json`;
- `reports/topology_pruning/r1/decision-report.md`.

The predeclared model is written before warm-up or measured pipeline execution.
Existing output causes a pre-execution failure; overwrite is unsupported.

## Explicit zero-execution boundaries

- H3 API calls: 0;
- API-key use: 0;
- paid API runs: 0;
- model downloads: 0;
- model loads: 0;
- CUDA runs: 0.
