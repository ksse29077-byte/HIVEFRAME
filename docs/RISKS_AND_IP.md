# Risks, Pivots, and IP Candidates

## Risk register

| Risk | Observable symptom | Response |
|---|---|---|
| Global attention prevents patch independence | Patch execution is slower than full-frame | Measure sparsity by head/layer; try previous-step context, mixed resolution, or another backend |
| Boundary communication explodes | GPU transfer costs exceed saved compute | Reduce latent strips, communicate asynchronously, use position-aware reconstruction, cap rounds |
| Central commands are not enforced | Eye size or object count repeatedly fails | Enforce masks/depth/pose, then measured adapters and local repair |
| Cache drift | Scene slowly melts or flickers | Use uncertainty, periodic refresh, object anchors, and drift evaluation |
| Patches are too small | Scheduling overhead rises | Adaptive patches, minimum work size, merge stable patches |
| Patches are too large | Sparse benefit disappears | Subdivide only complex regions |
| Worker results disagree | Style or lighting changes at boundaries | Shared seed/conditioning, scene contract, neighbor packet |
| Director becomes a bottleneck | It performs every numeric detail | Director emits relationships; deterministic compiler emits numbers |
| Model updates break hooks | Backend version change silently alters results | Pin versions, adapter contract tests, compatibility matrix |
| Data rights block commercialization | A model or dataset cannot ship | Direct contracts, data ledger, hard admission gate |
| Acceleration masks degradation | Faster output is visibly worse | Same-condition baseline, separate evaluators, blind review |

## Stop criteria

Deep patch integration for a backend stops after repeated evidence of mandatory global attention, net-negative communication economics, persistent degradation at practical patch sizes, uncontrolled cache drift, or speedups no better than 1.2×. See the roadmap for pivot paths.

## Candidate inventions

Patentability requires separate prior-art and counsel review. Candidate protection is in the coupled system, not generic patch parallelism:

- compiling a central scene contract into patch geometry and write permissions;
- scheduling logical visual workers that share base-model weights;
- typed neighbor boundary packets with semantic conflict escalation;
- patch freeze using warped prior state, latent delta, semantic delta, and uncertainty;
- affected closure derived from object, lighting, and motion dependencies;
- closed-loop repair that expands strip → patch → object → frame by defect type;
- a shared `SceneContract` and visual state across perception, generation, and correction.

## Invention-record policy

Before public code disclosure:

- record the problem, hypothesis, authors, date, alternatives, and novelty claim;
- attach experiment receipts and source revision;
- preserve prior-art searches and known related work;
- separate conceived ideas from implemented and validated claims;
- obtain legal review before patent or freedom-to-operate statements.

Candidate prior work to review includes DistriFusion, Partially Conditioned Patch Parallelism, Latent Parallelism for Video Diffusion, Sparse VideoGen, Foveated Diffusion, and FAST-AR.
