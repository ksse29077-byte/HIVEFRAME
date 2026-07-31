# M1-P0 Analytical Topology Pre-Gate Decision

Decision: **REFINE_COST_MODEL**

This is a model-free pre-gate. It closes neither M0 nor M1 and is not a model, GPU, quality, or product-speed claim.

## Result

Prediction error repeatedly exceeded the predeclared refine limit.

- analytical combinations: 9
- analytically pruned: 4
- measured combinations: 5
- warm-ups per measured combination: 5
- measured repetitions per combination: 20
- maximum false-stable: 0.000000

## Amdahl status

`partially_available`. The local Rust control-plane factor is available, but the M0 input/orchestration fraction and end-to-end upper bound are unavailable.

## Interpretation

The current multi-eye reference retains a dirty full-scene generate candidate while observing at least twice the unique input. Those candidates are preserved as analytically pruned evidence rather than deleted or measured repeatedly.

Model loads: 0.

CUDA runs: 0.
