# H3 C3 Selective Compute Handoff

## Selected hook

`h3.transformer_block_wrapper` is the sole C3 design candidate after C2-R2.
It is not implemented or authorized for execution. The initial C2 and C2-R1
sections below remain chronological evidence; the C2-R2 update is the current
handoff contract.

## Actual source call location

The inspected ComfyUI 0.30.2 path calls `callback(step, denoised, x, total_steps)` from the sampler and receives it through `latent_preview.prepare_callback`. In the one C2 run, the callback's first data argument did not satisfy the required `torch.Tensor` contract. The public location is recorded only as `<comfyui-root>/comfy/samplers.py` and `<comfyui-root>/latent_preview.py`.

## Selection rationale

C2 was required to use only the callback `x0` signal. All 20 callbacks returned `x0_not_tensor`; no substitution with `x`, a nested payload, an RGB preview, or another internal tensor was allowed. Consequently no 48-value sketch, regional shadow state, or counterfactual next-step validation was admitted.

## C2 stable coverage

Stable candidates: 0. Validated stable candidates: 0. Eligible regional coverage: unavailable because the source signal was not admitted.

## Shadow contradiction

Contradicted stable candidates: 0. This is not positive evidence: there were no admitted stable candidates to validate.

## Actual compute unit to reduce

None is admitted. The sampler remains the economically relevant 486-second-scale phase, but C2 provides no safe regional signal that could authorize reducing one of its model calls or blocks.

## C3 actual decision

Do not implement `sampler.pre_step_model_call_gate`, `h3.transformer_block_wrapper`, patch/tile recompute, or attention-level control from this evidence.

## Cache or skip contract

Unavailable. C2 performed zero skip, zero cache reuse, zero partial compute, and issued no selective directive.

## Invalidation

The only valid current rule is immediate Full Compute fallback whenever the callback signal is not a plain admitted tensor, its spatial axes are not provable, the sketch is non-finite, provenance differs, or any ABI/receipt check fails.

## Full Compute fallback

The unchanged Standard H3 sampler is mandatory and was exercised successfully for all 20 callbacks. Fail-open did not alter the workflow's actual computation.

## Tensor ownership

ComfyUI retains all tensor ownership. No raw tensor, CUDA pointer, full latent, or sketch payload crossed Rust FFI; no full tensor was copied to host.

## Rollback

Remove the repository-owned C2 sampler wrapper and restore the unmodified `SamplerCustomAdvanced` API workflow copy. No model, workflow source, or ComfyUI core rollback is needed.

## C3 paired-run design

Not admitted. A future separately approved signal-admission study must first establish an explicit, fixed-size view of the actual callback object without changing the C2 source after seeing results. Only then may a new predeclared paired Full Compute versus selective run be designed.

## Unsupported items

- Exact GPU kernel time: `null/not_collected`; no profiler was run.
- C2 x0 shape, dtype, and device: `null/not_collected`; the object failed the tensor admission check.
- Rust shadow timing: `null/not_collected`; Rust was never called.
- Stable coverage, safe skip, cache key, invalidation completeness, speedup, and product value: unsupported.

This hook cannot yet reduce the observed sampler phase, does not let Rust control actual GPU computation, and has no partial-repair connection. Standard rollback remains immediate, but no RTX 3060 or cross-backend C3 trial is authorized from this result.

## C2-R1 update

C2-R1 admitted the source-proven `x0.tensors[0]` structural path for all 20
callbacks and counterfactually validated 25/25 stable candidates with zero
contradiction. This does not supersede the no-admission decision. The actual
callback video tensor was CUDA float32, while the committed source gate required
BF16, and the adapter allowed Rust calls before that mismatch was applied. The
post-run result is therefore `C2_SHADOW_REVISE_ONCE`, not an admitted signal.

The GPU-to-host transfer of only 48 floats still blocked for about 7.14 seconds
per callback, producing 7.147004-second total-shadow p95 and 135.699001 seconds
cumulative overhead. Rust boundary p95 itself was only 37.6 microseconds, so
the current bottleneck is the synchronizing tensor-to-host boundary rather than
metadata evaluation.

The selector's `h3.transformer_block_wrapper` result is retained as a
counterfactual candidate only. It is not a C3 authorization because the signal
contract and overhead gates failed. The effective C3 selection remains
`no_c3_admission`; Full Compute fallback and wrapper removal are the rollback.

## C2-R2 current handoff

C2-R2 fixed the source contract at the exact float32 CUDA video tensor
`x0.tensors[0]` and passed all predeclared admission, bounded-transfer,
readiness, overhead, integrity, and lagged counterfactual-validation gates.
This supersedes `no_c3_admission` as the current design-selection result, but
does not supersede or rewrite the initial and R1 evidence above.

### Candidate execution hook

The sole candidate is `h3.transformer_block_wrapper`. The prospective compute
unit is one H3 transformer-block invocation, controlled by backend-owned
metadata while raw tensors and CUDA pointers remain in the Python/PyTorch
backend. Rust receives only fixed-size observation metadata and returns a
bounded directive. This is a C3 design input, not an implemented hook.

### Lag and evidence contract

The fixed shadow horizon is 2. Callback N enqueues sketch N, callback N+1
consumes it, and the delta from N-1 to N predicts the state at callback N+2.
The prediction is validated only against the later unchanged Full Compute
observation. C2-R2 produced 23 validated stable candidates from 72 eligible
eye-steps, with zero contradiction and zero unvalidated stable candidates.
These facts establish shadow-signal viability only; they do not establish safe
compute omission.

### Prospective cache and invalidation contract

If separately approved, the cache source is the prior Full Compute output of
the same transformer block. A cache key must include workflow and model logical
revision, fixed generation settings, sampler step, transformer-block identity,
and region identity. Any global-eye invalidation, overlap conflict, uncertainty,
contract mismatch, missing cache entry, non-finite observation, ABI failure, or
backend error must select Full Compute. No cache is created or reused by C2-R2.

### Ownership, bounds, and rollback

The proven C2 boundary uses three fixed pinned slots, 576 bytes of persistent
host sketch storage, and at most 576 bytes of in-flight reduced GPU state. It
retains no source tensor and copies no full latent to host. A future C3 wrapper
must preserve these coarse ownership and bounded-state properties on the RTX
3060 12 GB target. Rollback is removal of the repository transformer-block
wrapper and immediate restoration of the unchanged Standard Full Compute path;
no model asset, source workflow, or ComfyUI core change is required.

### Authorization boundary

C2-R2 performed zero skip, cache reuse, partial compute, regional compute
omission, speedup measurement, or product promotion. Implementing or executing
the candidate hook requires a separate C3 approval with predeclared parity,
quality, safety, memory, and rollback gates.
