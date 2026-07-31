# Roadmap

The roadmap advances only when the prior gate's evidence is recorded. The
compound-eye structure is a falsifiable hypothesis, not a product fact.

## M0 — Single-Eye Cost Truth

Preserve the existing Wan 2.1 Reproducible Baseline as the same-condition cost
and output truth.

Inherited evidence:

- pinned official Wan code, checkpoint, and license records;
- validated RTX 3060 CUDA/BF16 environment;
- smoke and regression smoke success;
- cold/warm and same-seed reproducibility evidence;
- 49-frame memory-admission safety result;
- RunReceipt 0.2.0 measurement scopes and immutable 0.1.0 compatibility.

Remaining formal-baseline work is governed by the existing M0 documents. No
compound-eye optimization may be mixed into M0 results.

## M1 — Eye Observation Correctness

Prove that logical eyes identify and localize input change safely before any
generation-backend optimization.

Exit criteria:

- deterministic global, regional, boundary, and motion contracts;
- synthetic oracle tests pass;
- rights-cleared recorded clips have oracle change masks;
- dirty-region precision/recall and false-stable rate are measured;
- regional write scopes and coordinate transforms never fail;
- fusion preserves provenance, confidence, and uncertainty;
- observation bytes, CPU wall time, and host memory are recorded;
- no model speedup claim.

Exact next experiment:

1. Create 12 tiny rights-cleared clips: static, local motion, camera motion,
   scene cut, boundary-crossing object, hair/smoke, reflection, and lighting
   change.
2. Store per-frame oracle dirty masks and scene-cut labels.
3. Run the unchanged model-free eyes on every clip.
4. Measure dirty precision/recall, false-stable rate, uncertainty coverage,
   observation bytes, fusion bytes, CPU wall time, and process-tree RAM.
5. Predeclare pass thresholds before inspecting aggregate results.
6. Publish one observation receipt per clip and a suite summary.

## M2 — Selective Plan Oracle Agreement

Compare `ComputePlan` decisions with oracle work labels without executing a
video model.

Exit criteria:

- dirty, stable, and uncertain decisions match policy;
- affected closure includes semantic and motion dependencies;
- no stable plan is emitted for oracle-dirty work;
- plan size and compiler cost remain bounded;
- patch, token, block, timestep, resolution, and cache selectors are explicit
  candidates rather than claims.

## M3 — Single-Backend Selective Feasibility

Add capability reporting to one pinned backend without altering M0 behavior.

Exit criteria:

- regression Smoke preserves M0 fingerprint;
- unsupported selectors fail or promote explicitly;
- one selector demonstrably reduces model operations in a diagnostic run;
- full-compute selective path matches baseline parity;
- no official speedup claim.

## M4 — Boundary, Constraint, and Repair Safety

Integrate preserved patch-centric safety mechanisms with compound-eye state.

Exit criteria:

- box, mask, depth, identity, count, distance, and symmetry constraints compile;
- overlap evidence routes boundary reconciliation;
- writes remain inside permissions;
- non-target change and seam scores are measured;
- repair expands region→patch/token group→object→frame safely.

## M5 — Net Selective Gain

Show real total savings against M0 Single-Eye Cost Truth.

Exit criteria:

- at least 1.5× end-to-end improvement on the declared eligible suite;
- GPU kernels or backend token/operation work actually decreases;
- observation, fusion, planning, boundary, evaluation, and repair are included;
- no more than 2% relative quality loss or blind-test non-inferiority;
- false skips at or below 0.5%;
- no meaningful seam or static-drift increase;
- gains repeat beyond curated static scenes.

## M6 — Closed-Loop Local Repair

Automatically locate defects and regenerate the smallest safe scope with
bounded retries and explicit terminal failure.

## M7 — Backend-Independent Runtime

Run the same state and plan semantics on at least two backends. Architecture
benefit must persist or backend-specific limits must be stated.

## M8 — Creator MVP

Expose generation, targeted correction, progress, receipt, provenance, and
export through stable runtime primitives.

## Architecture RFC backlog

- [x] Preserve pre-compound-eye design and M0 evidence.
- [x] Draft four compound-eye JSON Schemas.
- [x] Implement deterministic NumPy reference eyes.
- [x] Implement provenance-preserving fusion and compute planning.
- [x] Add synthetic contract and behavior tests.
- [ ] Build the rights-cleared M1 oracle clip suite.
- [ ] Add observation cost receipt aggregation.
- [ ] Predeclare M1 thresholds.
- [ ] Run M1 without model integration.

## Stop and pivot rules

Stop or reframe compound-eye integration when repeated evidence shows:

- observations collectively reproduce full input cost;
- false-stable errors cannot meet the declared safety threshold;
- fusion or state becomes a full-frame bottleneck;
- coordinate/ownership errors remain uncontrolled;
- backends cannot translate selectors into less computation;
- orchestration and repair exceed saved work;
- gains remain at or below 1.2× or appear only on easy static scenes.

Possible pivots retain valid evidence:

- patch selectors fail but token/block selectors work;
- generation acceleration is weak but local repair is strong;
- constraint compliance is strong but speed gain is weak;
- only multi-GPU economics work;
- one backend supports selective execution and another does not.
