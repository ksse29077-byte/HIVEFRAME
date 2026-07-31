# M1-P0 Analytical Topology Pre-Gate

Status: model-free probe complete; decision `REFINE_COST_MODEL`

This probe is a pre-gate. It does not close M0 or M1, replace the
rights-cleared M1 Cost Surface, or claim model, GPU, quality, product, or
commercial speedup.

MiniMax H3 is now the primary product backend target, but this probe remains
backend-neutral. It does not admit, invoke, integrate, or benchmark H3. Wan is
the frozen historical M0 comparator, and LTX is inactive.

## Provenance

- base and Rust Probe merge commit:
  `a71eea742f5a804c30f6f095c1a256ee2d2561a6`;
- Rust Probe Issue #35: closed through merged PR #36;
- Rust decision: `CONDITIONAL_ADMIT`;
- Analytical Issue:
  [#37](https://github.com/ksse29077-byte/HIVEFRAME/issues/37);
- run kind: `analytical_topology_pruning_probe`;
- model loads: 0;
- CUDA runs: 0.

No pre-existing Analytical implementation was found in local or remote
branches, registered worktrees, stash, reflog, repository files, or known
workspaces. The implementation therefore starts from the post-PR36 `main`.

## Bounded candidates

| ID | Topology | Runtime topology |
|---|---|---|
| T0 | Mono Eye | `mono_1x1` |
| T1 | Global + Fixed 2×2 | `uniform_2x2` |
| T2 | Global + Motion-focused Eye | `motion_focused` |

Fixed 4×4, object-centered, temporal compound eyes, learned planners, model
hooks, and backend execution are excluded.

## Synthetic cases

| Case | Shape | Declared change | Expected analytical behavior |
|---|---|---|---|
| A — Low-resolution Simple | 640×384×16 | 24×32 local region | split management should lose |
| B — High-resolution Local Change | 1920×1080×8 | 72×84 local region | T1/T2 remain plausible |
| C — Global Motion | 1280×720×16 | full canvas | Mono should dominate |

Inputs are deterministic packed `uint8` grayscale sequences using seed `101`.
The exact dirty mask is frame difference against the declared sequence.

## Cost model

```text
C_total(T) =
  C_scout
  + C_route(T)
  + C_observe(T)
  + C_overlap(T)
  + C_fusion(T)
  + C_plan(T)
  + C_generation(T)
  + C_audit(T)
  + E[C_recovery | T]
```

Merged Rust p50 and stage means calibrate the available model-free
input/orchestration components. `C_generation`, `C_audit`, and recovery are
`null/unavailable`. Motion detection is included in routing and cannot be
reported as an isolated scout cost. Overlap time is not separately
instrumented.

The break-even requirement is:

```text
S_required(T) =
  C_input_and_orchestration(T)
  - C_input_and_orchestration(Mono)
```

Negative cost inputs are rejected. Missing measurements are never replaced
with zero.

H3 generation, queue, model compute, GPU kernel, VRAM, latent/token/block,
selector, partial denoising, repair/fallback, API unit cost, and quality values
were not measured and do not participate in this decision. Their contract is:

```json
{
  "value": null,
  "unit": "ms",
  "scope": "minimax_h3_generation",
  "status": "unavailable",
  "reason": "H3 has not passed the separate HIVEFRAME API or open-weight admission gate",
  "method": "not measured"
}
```

## Amdahl status

`partially_available`.

- merged local control-plane factor `s_control`: 1.2331–1.6253×;
- M0 attributable input/orchestration fraction `f_input`:
  `null/unavailable`;
- end-to-end Amdahl upper bound: `null/unavailable`.

The unavailable optimized fraction prevents a Wan or product end-to-end
bound.

## Predeclared pruning

Thresholds are versioned in
`configs/m1-p0.analytical-topology-pruning.json`.

- Case A T1/T2: `analytically_pruned` by the declared small-input rule.
- Case C T1/T2: `analytically_pruned` because change is global, generation
  scope is full canvas, and observation is at least 2× Mono.
- Case B T0/T1/T2 and the Case A/C Mono comparators were retained.

Pruned candidates remain in the receipt with reason and evidence.

## Measurement contract

- analytical combinations: 9;
- pruned before timing: 4;
- measured combinations: 5;
- warm-ups per measured combination: 5;
- measured repetitions: 20;
- total final runner wall: approximately 2.19 seconds;
- copied bytes: 0 in every measured reference path;
- overlap time: `null/unavailable`, not zero.

## Predicted versus measured

Merged Python reference p50 is the absolute timing prediction. Rust p50 is
used separately for break-even calibration.

| Case | Candidate | Predicted ms | Measured p50 ms | p95 ms | Relative error |
|---|---|---:|---:|---:|---:|
| A | T0 | 3.950 | 2.788 | 2.936 | 41.66% |
| B | T0 | 18.238 | 14.232 | 15.506 | 28.15% |
| B | T1 | 26.006 | 19.848 | 20.627 | 31.03% |
| B | T2 | 30.587 | 22.596 | 23.749 | 35.36% |
| C | T0 | 15.375 | 13.890 | 14.638 | 10.69% |

Case B predicted and measured rankings both equal `T0 < T1 < T2`.
Case A and C retain only the mandatory Mono comparator, so multi-candidate
ranking is unavailable rather than reported as a pass.

## Break-even and safety

For Case B:

| Candidate | Rust-calibrated required savings | Measured required savings | Potential generation-scope reduction |
|---|---:|---:|---:|
| T1 | 3.249 ms | 5.616 ms | 75.00% |
| T2 | 4.455 ms | 8.365 ms | 99.42% |

The potential generation-scope reduction is geometry only. No backend
generation time was measured, so it is not a realized saving.

All measured combinations produced dirty recall 1.0 and false-stable 0.0.
Case B dirty precision was 0.0029 for T0, 0.0117 for T1, and 0.5013 for T2.

## Decision

**`REFINE_COST_MODEL`**

The selected absolute calibration missed the current p50 by more than the
35% threshold twice. This is repeated error even though the Case B ranking is
correct and false-stable is controlled.

Do not grow the corpus yet. The next exact work is:

1. normalize topology prediction to a same-run Mono anchor;
2. isolate motion detection from routing when feasible;
3. add an explicit overlap timer or keep it unavailable;
4. rerun only the same five retained combinations under the same 5/20
   contract;
5. reconsider the M1-P0 decision only after prediction error is within the
   declared rule.

This decision is not H3 backend admission, proof of H3 API or open-weight
support, or proof of H3 speedup. It does not close M0 or M1. H3 is only the
highest-priority target for a separate admission gate in Issue #39.

## Artifacts

- `reports/topology_pruning/analytical-model.json`;
- `reports/topology_pruning/candidate-pruning-report.json`;
- `reports/topology_pruning/minimal-probe-results.json`;
- `reports/topology_pruning/decision-report.md`.
