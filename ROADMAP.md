# HIVEFRAME Compound I/O Roadmap

Status: research roadmap

Architecture: compound-eye input observation and selective generation

Evidence policy: no speedup claim before same-condition end-to-end proof

## Backend target policy

- **MiniMax H3:** highest-priority product backend target. Official API
  documentation exists, but HIVEFRAME admission is pending Issue #39 and no
  integration or speedup is claimed.
- **MiniMax H3 open weights:** future white-box candidate, blocked until the
  official weights, source, license, immutable digest, and runtime are
  verified. A publication plan is not a released checkpoint.
- **Wan 2.1 T2V 1.3B:** frozen legacy comparator. Its M0 code, pins, receipts,
  reproducibility evidence, fingerprints, and reports remain immutable.
- **LTX:** inactive and removed from active development scope. Historical
  assets remain preserved.

M0 is not retroactively converted into an H3 baseline. A future H3 admission
baseline must be a separate approved stage or profile after admission.

## Product objective

HIVEFRAME does not optimize for the largest number of eyes. It chooses the
safest Eye Topology with the lowest accepted-result cost, including a valid
non-split `1×1 Mono Eye`.

```text
T* = argmin_T (
  C_scout
  + C_eyes(T)
  + C_fusion(T)
  + C_generation(T)
  + C_boundary(T)
  + C_audit(T)
  + E[C_repair_and_fallback | T]
)
```

Topology `T` may choose eye count, receptive fields, spatial resolution,
temporal windows and stride, semantic roles, overlap, activation policy,
backend selectors, and fallback scope.

The cheapest candidate is admissible only when it satisfies declared quality,
identity, geometry, constraint, memory, false-stable, license, and failure
safety limits. The initial false-stable target remains at or below 0.5% and
relative quality loss at or below 2%; later changes require recorded evidence.

## Non-negotiable principles

- **Mono is valid.** Do not split when 1×1 is safer or cheaper.
- **Measure before learning.** Build cost and safety ground truth before
  training a topology planner.
- **No fake speedup.** Include scout, observation, fusion, planning, boundary,
  audit, repair, fallback, VAE, and output costs.
- **Global safety path.** Retain low-cost whole-scene awareness.
- **Uncertainty blocks skip.** Promote or recompute uncertain work.
- **Reversible topology.** Every choice can escalate to a safer topology or
  full computation.
- **Backend truthfulness.** Unsupported selectors remain `unsupported`.
- **M0 is immutable evidence.** Compound-eye work cannot weaken or reinterpret
  the pinned baseline.
- **Every decision has provenance.** Record why work was observed, selected,
  skipped, promoted, repaired, or failed.

Detailed execution rules are normative in
[`docs/ROADMAP_EXECUTION_RULES.md`](docs/ROADMAP_EXECUTION_RULES.md).

## M0 — Single-Eye Cost Truth

**Status: `in_progress`.** Preserved successful probes are component evidence,
not milestone closure.

### Question

What does the complete pinned Wan path cost when the input is handled as one
whole-scene observation and one full generation path?

### Preserved evidence

- official Wan 2.1 T2V 1.3B code, checkpoint, and license pins;
- validated RTX 3060 WSL CUDA/BF16/FlashAttention environment;
- Smoke and regression Smoke;
- cold/warm and same-seed reproducibility;
- Receipt 0.2.0 measurement-scope corrections;
- 49-frame memory-admission safety result.

### Remaining work

- complete the eligible canonical same-condition baseline;
- add input decode, resize/crop/normalization, input bytes, conditioning,
  host-to-device transfer, and input-side peak memory scopes;
- publish a Single-Eye Cost Table by resolution, frames, and scene class.

### Exit gate

All costs from input through output are attributable and reproducible. No
compound-eye optimization is mixed into the baseline.

## M1-P0 — Analytical Topology Pre-Gate

**Status: `verified` and completed; final bounded decision
`RUST_CONTROL_PLANE_ADMITTED`.**

This is a bounded preparation step, not M1 entry or an M1 exit gate. It may
draft analytical cost equations, schemas, synthetic cases, tests,
unavailable-metric semantics, and topology pre-rejection rules.

The Rust I/O Admission Probe is merged into `main` at
`a71eea742f5a804c30f6f095c1a256ee2d2561a6`. Its `CONDITIONAL_ADMIT`
measurements may calibrate model-free orchestration, but M0 input share and
end-to-end Amdahl gain remain unavailable.

The first bounded probe analytically pruned four of nine combinations and
measured five. Case B ranking matched, dirty recall was 1.0, and false-stable
was 0.0, but absolute p50 prediction exceeded its 35% threshold twice.

Do not enlarge the corpus. Refine same-run Mono normalization and missing
stage attribution, then rerun the same five combinations. M1-P0 still cannot
close M0 or M1.

### M1-P0-R3 bounded runtime refinement

PR #43 merged R2 with decision `REFINE_RUST_BOUNDARY`. R3 tests exactly one
in-process PyO3 shared-buffer boundary on the existing synthetic Case B and
T0/T1/T2 only. It uses one Rust call per candidate, no per-Eye round trips,
no input-buffer copy, no subprocess, and no temporary file. Five warm-ups and
thirty paired measured blocks compare the unchanged Python reference with the
Rust in-process control plane.

R3 is not a real-video M1 experiment and does not alter M0. Only
`RUST_CONTROL_PLANE_ADMITTED` can make M1-P0 closable; any other declared R3
decision records one bounded implementation blocker and requires separate
approval before further refinement. H3 admission and every model/CUDA path
remain separate.

R3 passed as `RUST_CONTROL_PLANE_ADMITTED`: T1/T2 boundary p50 was 31.21% and
35.98% below the Python reference, p95 did not regress, T0 improved, boundary
overhead stayed below 0.2%, and semantic/copy safety passed. PR #45 merged at
`156d955fa8edfbcb6157ef6e130454da0b165daf` and Issue #44 closed. M1-P0 is
complete. Do not create an R4; proceed only through the separately approved,
rights-cleared real-video M1 protocol.

## M1 — Eye Topology Ground Truth Lab

### M1-A — Rights-cleared corpus and oracle admission

**Status: `verified`; decision `CORPUS_ACQUISITION_REQUIRED`.** This metadata-
only stage predeclares rights, consent, deterministic derivative, human-oracle,
topology-candidate, measurement, validation, coverage, and safety-Gate
contracts. The task-scoped repository and supplied-artifact review found zero
eligible actual clips, so all twelve required scene classes remain missing. It
performed no topology measurement and cannot close M1. Later measurement stays
blocked until a newly reviewed corpus passes `M1_CORPUS_AND_ORACLE_READY` under
the unchanged predeclared contract.

### Question

Which topology is safest and cheapest for each input class?

### Experiment

Admit at least 12 small rights-cleared clips covering:

- static background and local face/hand motion;
- pan, zoom, shake, and scene cut;
- multiple objects, occlusion, reflection, hair, smoke, and lighting change.

Create oracle dirty masks and scene-cut labels. Compare at least:

- T0: 1×1 Mono Eye;
- T1: global low-resolution + fixed 2×2 regional eyes;
- T2: global + fixed 4×4 regional eyes;
- T3: adaptive quadtree eyes;
- T4: object-centered eyes;
- T5: motion-centered eyes;
- T6: multi-resolution eyes;
- T7: mixed spatial and temporal topology.

Measure observation/fusion/coordinate time, bytes, active eyes, overlap,
dirty precision/recall, false-stable rate, uncertainty coverage, process-tree
RAM, and complete topology cost.

A model-free Python/Rust I/O admission probe may run as a supporting M1
experiment after semantic contracts stabilize. It may compare routing, Fusion,
planning, copies, temporary buffers, and core latency. It does not replace the
rights-cleared clip/oracle suite, complete M1, or prove model/backend speedup.
Rust remains optional when Mono or Python is cheaper after process/FFI cost.

### Exit gate

Produce a Topology Cost Surface and oracle topology label per input. Evidence
must show that 1×1 wins where splitting is wasteful and that another topology
wins safely on at least one declared class. No model speedup claim is allowed.

## M2 — Scout Eye and Adaptive Topology Planner

### Question

Can a cheap scout choose near-oracle topology without executing every
candidate?

### Work

Start with deterministic rules using resolution, frames, thumbnail, motion
concentration, camera motion, texture, object candidates, scene cuts, user
intent, hardware memory, load, and backend capabilities.

Only after sufficient M1 receipts may a small cost predictor be evaluated.
Measure topology regret:

```text
Topology Regret = Cost(selected topology) - Cost(oracle topology)
```

### Exit gate

- median topology regret at or below 15%;
- p90 regret at or below 30%;
- scout and planning cost do not consume expected savings;
- conservative choice under uncertainty;
- reliable 1×1 selection on simple or low-resolution inputs.

## M3 — Sensory Fusion and Dynamic Eye Activation

### Question

Can multiple observations preserve global relationships without becoming a
new full-frame bottleneck?

### Work

- normalize spatial and temporal coordinates;
- preserve observation provenance;
- calibrate confidence and propagate uncertainty;
- reconcile object identity and global/local conflicts;
- activate neighbors as objects cross boundaries;
- reduce observation frequency for proven-stable regions;
- invalidate topology and cache safely on scene cuts.

### Exit gate

Dirty recall targets at least 99.5%, false-stable remains at or below 0.5%,
canonical scene cuts are not missed, provenance is complete, and fusion cost
does not erase the measured opportunity.

## M4 — Perception-to-Compute Compiler

### Question

Can observations be compiled into safe backend work and write permissions?

```text
InputProfile
  → EyeTopology
  → EyeObservation[]
  → SharedVisualState
  → ComputePlan
  → Backend selector adapter
```

### Work

Classify patch, latent, VAE tile, token, block, timestep, resolution,
attention, and cache selectors as `supported`, `experimental`, or
`unsupported` per backend. Preserve full-compute fallback and full-compute
parity before enabling skip.

The first product-oriented experiment is directed local editing that changes
only an authorized region while preserving the remainder.

### Exit gate

At least one selector maps to demonstrably less backend work in a diagnostic
run, unsupported selectors promote or fail explicitly, and M0 regression
fingerprints remain intact. This is feasibility, not an official speed claim.

## M5 — Compound I/O Net Gain

### Question

Does better observation produce real generation savings after every added
cost?

### Required comparison

Use the same checkpoint, resolution, frames, FPS, steps, scheduler, precision,
seed policy, VAE scope, hardware class, and eligibility rules as M0.

### Provisional exit gate

- median end-to-end improvement of at least 1.2× on the eligible suite;
- at least 1.5× on the declared static/local-motion subset;
- actual GPU-kernel time or token/block operations decrease;
- relative quality loss stays within 2% or blind-test non-inferiority;
- false skips stay at or below 0.5%;
- repair and fallback costs are included;
- gains repeat outside curated static scenes.

If orchestration exceeds savings, quality degrades, fallback dominates, or
global attention prevents locality, stop deep integration for that backend or
pivot the selector granularity.

## M6 — Closed-Loop Adaptive Retina

### Question

Can output evidence safely change the next observation and compute scope?

```text
observe
→ compute
→ audit output
→ adapt topology
→ reobserve/recompute the smallest safe closure
```

Promote through reobservation, boundary refresh, region, object, larger
closure, and full-frame computation. Track accepted-edit cost, first-pass
acceptance, silent-failure rate, repair overhead, fallback rate, and operator
minutes saved.

### Exit gate

Accepted-result cost is lower than the full path with bounded retries,
explicit terminal failure, and no unauthorized regional change.

## M7 — Temporal Eye Swarm and Backend Independence

### Work

- immediate motion, object history, drift, scene transition, and predictive
  temporal eyes;
- online but reversible topology adaptation;
- common `EyeContract`, `EyeObservation`, `SharedVisualState`, `ComputePlan`,
  and receipt semantics on at least two backends;
- backend-specific selector adapters only at the integration boundary.

### Exit gate

The same topology principles and failure semantics work on two backends.
Backend differences are explicit and the benefit is not dependent on a hidden
Wan-only shortcut.

## M8 — Commercial Compound Visual Engine

### Delivery order

1. Python SDK and CLI;
2. REST API;
3. production-tool or node integration;
4. minimal audit UI;
5. creator or B2B product surface.

### Product gate

- at least one paid pilot;
- at least 100 real customer videos processed;
- target first-pass acceptance of 70% or better;
- measurable operator-time or total-cost reduction of 30% or better;
- known cost per accepted edit and positive GPU-inclusive margin;
- repeat use intent and bounded customer-specific support.

## Preserved legacy mapping

| Legacy asset | Compound I/O role |
|---|---|
| Reproducible Baseline | M0 Single-Eye Cost Truth |
| Directed Regional Repair | M4 local-edit track and M6 repair |
| Patch Runtime Parity | M4 full-compute parity |
| BoundaryPacket and halo | M3/M4 overlap reconciliation |
| Temporal cache and false skip | M5–M7 selective reuse evidence |
| Patch-centric architecture | preserved comparison design |

The complete pre-rebase design remains in
[`docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md`](docs/legacy/PATCH_CENTRIC_ARCHITECTURE_V0.md)
and tag `pre-compound-eye-v1`.
