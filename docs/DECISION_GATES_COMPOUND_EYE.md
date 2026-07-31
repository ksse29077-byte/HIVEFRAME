# Compound-Eye Decision Gates

These gates prevent an architecture sketch from becoming an unsupported product
claim.

## G0 — Contract integrity

Required:

- all four schemas are versioned and parse as Draft 2020-12 JSON Schema;
- deterministic reference validators pass;
- receptive fields, write scopes, and transforms agree;
- unsupported values are never fabricated.

Failure: fix or reject the contracts. Do not integrate a model.

## G1 — Synthetic observation correctness

Required:

- global context exists;
- 2×2 ownership is complete and non-overlapping;
- boundary overlap maps correctly;
- motion detection matches the synthetic oracle;
- fusion preserves provenance and confidence;
- identical input and seed are bitwise deterministic.

Failure: reject the eye or fusion implementation.

## G2 — Recorded-input detection safety

Predeclare thresholds for:

- dirty-region precision and recall;
- false-stable rate;
- uncertainty coverage;
- observation/fusion bytes;
- CPU wall time and host memory.

The false-stable threshold must be stricter than the downstream false-skip
threshold. Failure means no backend skipping.

## G3 — Single-backend feasibility

Against M0 Single-Eye Cost Truth:

- add capability reporting without changing pinned baseline behavior;
- translate at least one selector into demonstrably fewer backend operations;
- preserve full-compute parity before enabling skip;
- record promotion and unsupported selectors.

Failure may pivot selector granularity from patch to token, block, timestep, or
resolution. It does not permit a speedup claim.

## G4 — Net compute economics

Required:

- same checkpoint and complete same-condition comparison;
- observation, fusion, planning, boundary, evaluation, and repair included;
- actual wall time decreases;
- GPU kernel or operation/token work decreases;
- quality and constraint metrics remain non-inferior;
- benefits repeat beyond static scenes.

Failure: optimize the measured overhead or reject the selective path.

## G5 — Backend independence

Run compatible contracts on at least two backends. Backend-specific selectors
may differ, but state and receipt meanings must not.

Failure: classify the runtime as backend-specific rather than claiming a
backend-independent architecture.

## Claim policy

| Gate reached | Allowed statement |
|---|---|
| G0 | Contracts are internally consistent |
| G1 | Model-free reference behavior is deterministic |
| G2 | Eyes detect change on the evaluated input suite |
| G3 | A pinned backend can execute at least one selector |
| G4 | Selective execution reduces measured total cost on the evaluated suite |
| G5 | The architectural benefit survives a second backend |

No earlier gate implies a later statement.
