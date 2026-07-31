# Compound-Eye Hypothesis

Status: architecture RFC; not a product fact

## Claim under test

HIVEFRAME may reduce real video-processing time and GPU cost when it observes
the input through multiple small, purpose-specific logical eyes before asking a
generation backend to compute. An eye sees only the spatial, temporal,
resolution, and semantic field needed for its role. Its result is an
`EyeObservation`, not a full input copy and not a generated patch.

Sensory Fusion combines observations into a provenance-preserving
`SharedVisualState`. A deterministic compiler then produces a `ComputePlan`
whose selectors can target backend patches, tokens, blocks, timesteps,
resolution levels, and cache operations.

The hypothesis succeeds only if:

```text
observation + fusion + planning + selective generation
+ boundaries + evaluation + repair
<
same-condition single-eye baseline total cost
```

Quality, constraint compliance, and failure behavior must remain non-inferior.

## Why this differs from output-only patching

Output-side patching starts after the whole input has already been represented
as one scene. Compound-eye observation attempts to avoid creating equally rich
representations for every place and time. Patches remain one possible backend
selector, but they are no longer the product definition or the only scheduling
unit.

## Falsifiable sub-hypotheses

H1. A low-resolution global eye can retain enough scene context to prevent
regional observations from becoming semantically isolated.

H2. Regional and motion eyes can identify stable input regions with a false
skip rate low enough to justify selective generation.

H3. Overlap eyes can expose ownership-boundary ambiguity before local writes,
reducing downstream seam and repair work.

H4. `SharedVisualState` can preserve observation source, confidence, coordinate
transforms, and uncertainty without becoming a new full-frame bottleneck.

H5. A backend-neutral `ComputePlan` can express useful patch, token, block,
timestep, resolution, and cache candidates on at least two backends.

H6. Saved generation cost exceeds observation, fusion, planning, boundary,
evaluation, and repair overhead on representative scenes.

## Immediate counterexamples

The hypothesis is weakened or rejected when:

- global context must be reconstructed at full fidelity for every eye;
- observation tensors collectively approach or exceed a full input copy;
- motion or semantic change misses create unacceptable false skips;
- coordinate transforms or overlap reconciliation create persistent defects;
- the backend cannot turn selectors into fewer kernels, tokens, or operations;
- orchestration and repair consume the saved compute;
- benefits appear only on curated static clips;
- measured wall time or total GPU work does not improve.

## Evidence levels

1. **Contract evidence:** schemas and deterministic reference behavior.
2. **Detection evidence:** synthetic and recorded inputs identify change safely.
3. **Planning evidence:** selectors agree with an oracle change mask.
4. **Backend feasibility:** a pinned backend accepts selectors without parity
   loss.
5. **Economic evidence:** real wall time and GPU work decrease including all
   overhead.
6. **Product evidence:** gains repeat across prompts, edits, scenes, and
   supported backends.

This RFC supplies only level 1 evidence. It makes no sparse speedup claim.

## Invariants inherited from M0

- The existing Wan M0 artifacts and receipt semantics are immutable evidence.
- CUDA event span remains distinct from actual profiler kernel duration.
- Unsupported values are `null` with status, reason, and method.
- Admission probes are not quality or speed baselines.
- Any selective result must use the same checkpoint, resolution, frames,
  steps, scheduler, precision, seed policy, and VAE scope as its comparator.
