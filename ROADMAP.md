# Roadmap

The roadmap advances only when the prior milestone's evidence is recorded. M0 is the first implementation priority.

## Milestones

### M0 — Reproducible Baseline

Run the same pinned base model under identical conditions and record all cost and quality dimensions.

Exit criteria:

- Wan 2.1 1.3B checkpoint and code/license records admitted and pinned;
- ten deterministic prompts run with fixed seeds and settings;
- environment fingerprint and output hashes emitted;
- wall time, GPU time, denoising step time, VAE time, peak VRAM, and host RAM recorded;
- repeatability report distinguishes deterministic hashes from tolerated numeric variation;
- no patch, cache, or training optimization mixed into baseline.

### M1 — Directed Regional Repair

Modify only a centrally specified region while preserving the remainder.

Exit criteria:

- scene graph and box/mask/depth contract validated;
- target patch write permission enforced;
- non-target change measured and below the declared threshold;
- one-object deletion, clothing change, background replacement, and face-preserving lip edit evaluated.

### M2 — Patch Runtime Parity

When every patch executes, match full-frame quality.

Exit criteria:

- full-vs-patch parity under the same backend, resolution, steps, and seed;
- patch and boundary costs separated;
- no meaningful increase in global quality loss, flicker, geometry errors, or seams.

### M3 — Neighbor-Sealed Patches

Resolve seams through bounded neighbor communication and central escalation.

Exit criteria:

- `BoundaryPacket v0` and receipt implemented;
- halo-width study completed;
- two-round reconciliation works;
- unresolved semantic conflicts promote safely.

### M4 — Constraint-Compliant Generation

Numerically obey object size, placement, landmarks, count, depth, distance, and symmetry commands.

Exit criteria:

- synthetic constraint suite passes at least 95%;
- mask, depth, and pose enforcement measured independently;
- failed local repairs promote scope rather than corrupting other regions.

### M5 — Temporal Sparse Gain

Skip unchanged work and obtain real end-to-end acceleration.

Exit criteria:

- at least 1.5× end-to-end speedup against the identical backend baseline;
- no more than 2% relative quality loss or blind-test non-inferiority;
- at least 50% average interior skip on the static suite;
- false skips at or below 0.5%;
- no meaningful seam increase;
- scene-cut invalidation and periodic refresh verified;
- orchestration and communication included in wall time.

### M6 — Closed-loop Local Repair

Automatically locate errors and regenerate the smallest safe scope.

Exit criteria:

- evaluator routes defects by type;
- scope expands strip → patch → object → frame;
- repair overhead and non-target change are recorded;
- max rounds and terminal failure are explicit.

### M7 — Backend-Independent Runtime

Run one control plane on at least two backends, selected from Wan and LTX.

Exit criteria:

- common backend capability contract and compatibility matrix;
- the same scene contract and receipt semantics on both backends;
- architecture benefit persists or its backend-specific limits are documented.

### M8 — Creator MVP

Allow a user to create a scene, correct a selected region, and export the result.

Exit criteria:

- minimal creator workflow over stable CLI/runtime primitives;
- generation, targeted correction, progress, receipt, and export;
- explicit license provenance and failure messages.

## First execution backlog

### Sprint A — Repository and baseline → M0

- [ ] Create independent repository.
- [ ] Define project name and scope.
- [ ] Install and pin Wan 2.1 1.3B only after license admission.
- [ ] Run ten deterministic prompts.
- [ ] Emit latency and VRAM receipts.
- [ ] Create model/license manifest.
- [ ] Record output hashes and environment fingerprint.

### Sprint B — External supervision → M1

- [ ] Define scene graph schema.
- [ ] Compile box, mask, and depth contract.
- [ ] Render a 2×2 patch overlay.
- [ ] Apply video-to-video modification to one patch.
- [ ] Measure non-target region change.
- [ ] Implement seam detector v0.

### Sprint C — Denoising hook → M2

- [ ] Add scheduler-step callback.
- [ ] Save latent snapshots.
- [ ] Run patch-freeze experiment.
- [ ] Compare full path and hook parity.
- [ ] Analyze change by timestep.
- [ ] Identify reusable feature candidates.

### Sprint D — Workers and boundaries → M3

- [ ] Implement logical worker queue.
- [ ] Define `BoundaryPacket v0`.
- [ ] Study halo width.
- [ ] Implement two-round neighbor reconciliation.
- [ ] Add central escalation.
- [ ] Emit boundary receipt.

### Sprint E — Temporal sparse MVP → M5

- [ ] Warp previous latent.
- [ ] Measure patch delta.
- [ ] Freeze static patches.
- [ ] Support boundary-only dirty state.
- [ ] Invalidate on scene cuts.
- [ ] Publish baseline speed and quality report.

M4 constraint work proceeds from the contract foundations in Sprints B–D and must be satisfied before M5 is declared complete.

## Development order

### Must happen first

1. Baseline reproduction.
2. Model license pinning.
3. Scheduler-step hook.
4. Patch and boundary quality measurement.
5. Proof that actual computation decreases.
6. Central contract schema.
7. Synthetic constraint tests.
8. Temporal cache.

### Later

Polished GUI, broad large-model support, worker conversation, feature-film generation, foundation pretraining, mobile deployment, and wholesale custom kernels.

## Stop and pivot rules

Stop deep patch integration for the current backend when repeated evidence shows:

- global attention is mandatory across major layers and patch-local work cannot reduce computation;
- communication plus coordination exceeds saved compute;
- quality remains degraded even at practical grids of 4×4 or coarser;
- temporal drift cannot be controlled for stable patch skips;
- speedups repeatedly remain at or below 1.2×.

Pivot instead of ending the project when:

- only multi-GPU improves → define a server parallel runtime;
- generation acceleration is weak but repair is strong → become an AI video editor;
- constraint compliance is strong but speedup is weak → become a precision-control creator;
- Wan hooks are difficult while LTX control is accessible → change backend priority;
- token/head sparsity beats spatial patching → schedule semantic token groups.
