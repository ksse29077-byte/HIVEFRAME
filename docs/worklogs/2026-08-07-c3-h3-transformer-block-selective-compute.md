# C3 H3 Transformer Block Selective Compute

Date: 2026-08-07
Status: Draft RFC evidence; pre-run opportunity Gate stopped execution
Final decision: `C3_POLICY_OPPORTUNITY_TOO_LOW`

## Product question

Can the C2-R2 lagged Compound Eye signal omit selected MiniMax H3 transformer
block invocations, reduce actual computation and elapsed time against a matched
Full Compute control, and retain a conservative output-integrity floor?

This work answered the required pre-run question first. The fixed signal did
not offer enough theoretical opportunity under the fixed safety policy, so no
runtime implementation or generation was authorized by the protocol.

## Repository state and coordination

- Source `main`: `e7bae9070318872f535f2351f6942ccb40cfa75c`
- Issue: [#63](https://github.com/ksse29077-byte/HIVEFRAME/issues/63)
- Branch: `accel/c3-h3-transformer-block-selective-compute`
- Draft PR: created after the evidence commit; it remains Draft
- C2 branch and all prior C0/C1/C2 evidence remain unchanged

The task reused the merged C2-R2 receipt. It did not repeat C2 generation,
alter the C1/C2 ABI, modify installed ComfyUI, or inspect a different model.

## Reused evidence

C0 measured the sampler at approximately 486.604 seconds and 81.196 percent
of runner time. C1 verified one metadata-only Rust callback per sampler
callback with 20 callbacks, 20 Rust calls, and a 38.1 microsecond boundary
p95. C2-R2 admitted `x0.tensors[0]` as a float32 CUDA tensor with shape
`[1,24,37,30,54]`, generated a non-blocking 48-scalar sketch, and returned 23
validated Stable candidates with zero contradiction. C2-R2 actual execution
remained Full Compute with zero skip, cache reuse, partial compute, or speedup
claim.

## H3 block source admission

The read-only source audit used ComfyUI 0.30.2 at commit
`dec5d9450a5290bcf63430409ea41018e67f41c3`. The public logical model path is
`<COMFYUI_ROOT>/comfy/ldm/minimax/model.py`; its SHA-256 is
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`.

`MiniMaxH3Model` owns a `ModuleList` named `self.blocks`. The checkpoint-key
detection supplies `num_layers`; the inspected H3 contract and source default
are 50 blocks, enumerated deterministically from 0 through 49. The block class
is `DiTBlock`, with the exact signature:

```text
forward(self, x, t_emb, mod_segments, rope_freqs, transformer_options={})
```

The input is the joint packed video/audio/text residual stream. The normal
block updates that stream in place through gated attention and MLP residual
adds, then returns the tensor. The model loop exposes an explicit repository-
owned replacement boundary at
`transformer_options.patches_replace['dit'][('double_block', index)]`.
A replacement may call `original_block` for Full Compute or return
`{'img': args['img']}` without calling it. The latter preserves the required
output container and performs an identity bypass without clone, host copy,
cache, or Rust tensor transfer. The wrapper is removable, so Standard Full
Compute is restored without changing installed source or model assets.

The source contract therefore admits `SELECTIVE_BLOCK_BYPASS_IDENTITY` as a
mechanism. This admission says the hook is structurally possible; it does not
authorize a run when the separate opportunity Gate fails.

## Immutable C2-R2 replay

The replay used only the existing private receipt under logical
`C2_ARTIFACT_ROOT`. Its SHA-256 is
`d54693ab2fa10717e1aaa22c56bb4c3aaa17f9d4579c9b1f4a3ffb67734b46df`.
The receipt was not rewritten, and no model was loaded.

The fixed block set preserves blocks 0 through 11 and block 49 as Full
Compute. Candidate indices are 12 through 48 inclusive: 37 candidates per
selective execution step. With 20 execution steps and 50 blocks, the
predeclared denominator is 1,000 theoretical block calls.

The predeclared anchors force steps 0, 1, 18, and 19 to Full Compute. Every
selective step is followed by two Full Compute cooldown steps. Global
invalidation, overlap conflict, an Active region outside the chosen Gate,
missing prediction, unknown state, contract mismatch, or error also forces
Full Compute.

| Gate | Raw eligible target steps | Selected after anchors/cooldown | Bypass calls | Theoretical reduction |
|---|---|---|---:|---:|
| G4 | none | none | 0 | 0.0% |
| G3 | none | none | 0 | 0.0% |
| G2 | 5, 6, 8, 13, 16, 17, 18, 19 | 5, 8, 13, 16 | 148 | 14.8% |

G4 and G3 provide no eligible target. G2 is the least conservative permitted
Gate, but `4 * 37 / 1000 = 14.8%`, below the immutable 18 percent threshold.
No Gate was selected. The threshold, block set, anchors, cooldown, signal, and
pairing were not changed after the replay.

## Consequence for C3 implementation and runs

The protocol explicitly requires `C3_POLICY_OPPORTUNITY_TOO_LOW` and no actual
generation when G2 cannot reach 18 percent. Therefore:

- `C3BlockPlanObservation`, `C3BlockPlanDirective`, and the PyO3 C3 ABI were
  not implemented;
- no repository-owned runtime wrapper was installed;
- CONTROL generation count is 0;
- SELECTIVE generation count is 0;
- actual block bypass, compute reduction, cache reuse, and tensor transfer to
  Rust are all 0;
- performance, resource, SSIM, MAE, motion-energy, and visual-equivalence
  comparisons are `null/not_collected`, not zero-valued successes;
- no output video or visual-review artifact was created.

Because execution never started, step-to-block runtime mapping was not tested.
It is `not_collected`, not admitted or rejected. The source-level ordering is
deterministic, but that is not presented as runtime mapping evidence.

## Validation and safety

Only model-free, task-relevant checks were used: source hashes and signatures,
the immutable receipt replay, arithmetic assertions, YAML/JSONL parsing, public
path and secret inspection, and `git diff --check`. The task did not run full
Rust or Python suites because no runtime code changed. Model loads, CUDA
execution, external API calls, model downloads, H3 generations, retries, and
binary additions were all zero.

The source admission assertions passed 10/10 checks. Five changed H3 YAML
documents parsed successfully, all 15 Knowledge Flywheel JSONL records parsed,
and the C3 decision assertions passed. The arithmetic audit independently
confirmed 37 candidate blocks, four selected steps, 148 bypass calls, a 1,000-
call denominator, and 0.148 reduction. The nine changed public documents had
zero prohibited absolute-path, credential, private-key, or bearer-token hits;
no media, model, executable, DLL, or PDB was added. `git diff --check` passed.

## Claim boundary and next action

This result does not show that identity block bypass is unsafe, slow, or low
quality. It shows only that this one fixed C2-R2 signal, fixed 50-block/20-step
profile, fixed candidate block set, and fixed safety anchors cannot meet the
predeclared opportunity floor. There is no speedup claim, product promotion,
cache-reuse claim, partial-repair claim, or cross-profile conclusion.

A next experiment requires separate approval and a predeclared source of
greater opportunity or a different product question. It must not retroactively
relax the 18 percent threshold, G4/G3/G2 semantics, anchors, cooldown, or block
set used here.
