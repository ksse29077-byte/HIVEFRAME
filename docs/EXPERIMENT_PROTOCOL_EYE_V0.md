# Experiment Protocol — Eye v0

## Objective

Test whether compound-eye contracts produce correct, deterministic,
provenance-preserving observations and plans before integrating a model.
This protocol does not measure generation quality or speed.

## Reference input

The default synthetic tensor has:

- shape `[4, 16, 16, 3]`;
- seed `101`;
- a static low-amplitude background;
- a deterministic 4×4 intensity change crossing the vertical 2×2 ownership
  boundary in the upper half.

Custom small NumPy tensors are accepted when they contain at least two frames.

## Eye set

1. One whole-scene eye at 0.25 spatial scale.
2. Four non-overlapping 2×2 regional eyes with bounded write scopes.
3. One read-only boundary eye with vertical and horizontal overlap windows.
4. One read-only full-frame frame-difference motion eye.

## Run

From the repository root in an environment with NumPy:

```bash
PYTHONPATH=python python -m hive_probes.compound_eye_v0 \
  --seed 101 \
  --output-dir reports/compound-eye-v0
```

The output directory must be new or empty. The probe emits:

- `eye_contracts.json`;
- `eye_observations.json`;
- `shared_visual_state.json`;
- `compute_plan.json`;
- `observation_receipt.json`.

## Required checks

- same tensor and seed produce identical artifact hashes;
- every observation exactly repeats its eye's receptive field and write policy;
- global context covers the full canvas;
- regional reported regions stay within bounded write scopes;
- boundary local-to-global transforms match source coordinates;
- the motion eye finds the oracle change box;
- fused regions preserve observation IDs, reported states, and confidence;
- dirty, stable, and uncertain states are all represented by the synthetic
  boundary-crossing input;
- compute decisions map dirty to an active candidate requiring backend
  admission, stable to a frozen candidate requiring safe-reuse evidence, and
  uncertain to full-compute fallback;
- no observation-only candidate carries backend selector or skip authority;
- unmeasured speedup and GPU metrics remain `null` with reason and method.

## Model-free receipt

The observation receipt is deterministic and contains no timestamp or measured
runtime. It records input, contract, observation, state, and plan SHA-256
digests. This is separate from the M0 `RunReceipt`; it must not be accepted as
a backend benchmark receipt.

## Follow-on recorded-input experiment

After v0 passes, use a small, rights-cleared clip set with oracle change masks.
Measure detection precision/recall, false-stable rate, observation bytes, fusion
bytes, CPU wall time, and memory. Still do not claim model speedup.

## Stop conditions

Stop before backend integration if deterministic behavior fails, coordinates
do not round-trip, regional writes escape scope, provenance is lost, or false
stable regions exceed the predeclared threshold.
