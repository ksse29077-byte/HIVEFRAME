# Evaluation and Canonical Benchmark

## Measurement rule

Speed, resources, sparse behavior, and quality are separate result families. A run cannot substitute one for another, and every comparison uses the same backend, checkpoint, resolution, frames, steps, scheduler, precision, seed policy, hardware class, and VAE scope.

## Required metrics

### Speed

- wall-clock latency;
- GPU kernel time;
- denoising step time;
- VAE encode and decode time;
- communication time;
- scheduler overhead;
- repair overhead.

### Resources

- peak VRAM;
- host RAM;
- GPU utilization;
- transferred bytes;
- cache memory.

### Sparse behavior

- active patch ratio;
- skipped patch ratio;
- boundary-only refresh ratio;
- cache hit rate;
- false skip rate;
- average affected-closure size.

### Quality

- global perceptual quality;
- prompt alignment;
- motion coherence;
- temporal flicker;
- identity persistence;
- geometry compliance;
- boundary seam score;
- static-region drift.

## Canonical benchmark

### A. Static background

- speaking person with a stationary background;
- only mouth and eyes move;
- only a hand moves.

### B. Camera behavior

- slow pan;
- zoom in and out;
- handheld shake;
- scene cut.

### C. Patch-boundary stress

- face center placed on a patch boundary;
- long rod, sword, or cable crossing multiple patches;
- hair and smoke;
- reflection and mirror.

### D. Constraints

- eye size and spacing;
- object count;
- finger count;
- distance between two objects;
- depth ordering;
- left-right symmetry.

### E. Editing

- replace only the background;
- replace only clothing;
- preserve the face while changing lip motion;
- delete one object.

The initial prompt inventory is in [`../benchmarks/prompts/canonical-v0.yaml`](../benchmarks/prompts/canonical-v0.yaml). Canonical clips require approved ledger records before use.

## Sparse MVP success criteria

- ≥1.5× end-to-end speedup versus the same-backend baseline;
- ≤2% relative quality degradation or non-inferiority in blind evaluation;
- no statistically meaningful increase in seam defects;
- ≥50% average interior skip on the static suite;
- ≤0.5% false-skip rate;
- ≥95% central-constraint compliance;
- non-target change below a threshold declared before local-repair evaluation;
- explicit promotion or terminal failure on unsafe work.

## True and false success

True success requires:

- real wall-time reduction;
- fewer GPU kernels or token operations;
- maintained quality and blind-review results;
- repeatability across prompts and scenes;
- architectural benefit after changing models.

False success includes:

- more workers with more total GPU time;
- omitted VAE decode time;
- mismatched resolution;
- selected easy static scenes;
- seam blur that destroys detail;
- model replication per worker;
- evaluator blind spots counted as success.

## Reporting

Reports must show absolute results, deltas, confidence intervals where appropriate, hardware and software fingerprints, failed samples, and promoted repairs. Publish per-category results; do not collapse everything into one score.
