# H3 C3 Selective Compute Handoff

## Selected hook

`no_c3_admission` (candidate C). No C3 execution hook is selected for implementation.

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
