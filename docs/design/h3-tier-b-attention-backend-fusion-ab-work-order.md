# H3 Tier-B Exact Attention Backend Fusion A/B Work Order

## Exact Task

`H3_TIER_B_EXACT_ATTENTION_BACKEND_QKV_ROPE_OUT_FUSION_AB`

This is the only next implementation candidate selected by the H3 end-to-end
profile. It must not start automatically from the profiling task.

## Modules

Implement an H3-adapter-owned Attention capability around the installed
`DiTBlock.attn` path. Keep ComfyUI core, the H3 checkpoint, scheduler, sampler,
steps, precision, and offload policy unchanged. The adapter may replace the
exact QKV, QK norm/RoPE, Attention kernel, and output-projection execution
boundary only. It must not add cache reuse, token omission, step skipping,
quantization, Sage, V4 evidence, or a persistent CUDA graph.

## Input And Output

Input is the same H3 hidden tensor, RoPE table, transformer options, model
weights, dtype, device, and shape accepted by the installed Standard Attention
method. Output shape, dtype, device, finite-value contract, and residual update
order must match Standard Full Compute. The original `attention_pytorch` call
is the independent fallback.

## Admission Budgets

- Incremental peak VRAM: at most 256 MiB.
- Remaining physical VRAM reserve: at least 128 MiB.
- Incremental host RAM: at most 512 MiB.
- Tensor payload D2H in the hot path: zero.
- Per-call CPU synchronization: zero.
- Runtime compilation or graph capture during the measured generation: zero.

The profile observed only 406.4 MiB of ComfyUI-reported physical VRAM
headroom. Any admission uncertainty or workspace allocation above the fixed
budget selects Standard Full Compute before submission.

## Performance Gate

Use the fixed P1-A2 input and prompt, seed 101, 864x480, 124 frames, 24 FPS,
20 steps, `res_multistep`, `simple`, native audio, existing precision/offload,
and Sage disabled.

- CONTROL submissions: exactly 1.
- CANDIDATE submissions: at most 1 and only after CONTROL passes.
- Retry: 0.
- Automatic Standard rerun after candidate failure: 0.
- Sampler reduction: at least 10 percent versus CONTROL.
- Submit-to-output reduction: at least 10 percent versus CONTROL.
- Attention candidate surface reduction: measured, not inferred from a
  microbenchmark.
- Incremental overhead and VRAM: within the fixed budgets.

The profile's planning estimate is 76.048 seconds, or 11.957 percent E2E, from
a 20 percent reduction of the measured 380.238-second QKV/RoPE/kernel/out
surface. This is an implementation admission target, not a speedup claim.

## Quality Gate

CONTROL and CANDIDATE use identical generation settings. Both outputs must pass
the existing fixed automatic product quality and technical integrity Gates.
The candidate must not score below Standard. Any nonfinite result, shape or
dtype mismatch, frame corruption, black output, missing audio, new duplicate
frames, or automatic quality regression fails the candidate. Human visual
review is required before promotion even when automatic Gates pass.

## Fallback And Stop Conditions

Any unsupported backend, source-hash mismatch, workspace admission failure,
compile/capture attempt, allocation failure, CUDA error, nonfinite value,
quality failure, performance below 10 percent, or receipt inconsistency keeps
the original `attention_pytorch` Full Compute path selected. Never compute both
paths and discard one with a mask.

Stop after the paired result. Do not combine Compile/Graph, offload changes,
VAE changes, V4, step reduction, distillation, or other model work in this
task.

## Product Integration Position

Declare the capability through the existing `GenerationContext` and runtime
profile adapter boundary:

```text
Product Request
-> GenerationContext
-> Runtime Profile
-> H3 Attention Capability Admission
-> H3 Runtime (candidate or exact Full Compute fallback)
-> Output
-> Receipt
-> Cleanup
```

The capability receipt records name/version, backend identity, input contract
digest, VRAM and RAM budget result, Attention surface timing, sampler and
submit-to-output time, quality result, fallback reason, and cleanup result.
