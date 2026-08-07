# C4-S0 H3 Sub-Block Cost Surface Contract

Status: frozen before Generation

Base: `main@e78416691f115710a00e4735c0dc981a8bcfee42`

Issue: [#74](https://github.com/ksse29077-byte/HIVEFRAME/issues/74)

## Product question

Which source-backed component inside the installed MiniMax H3 `DiTBlock`
accounts for the largest useful cost surface, and which one should become the
single next quality-preserving compute-lever candidate?

This stage measures, classifies, ranks, and selects. It performs no selective
execution. Full Compute remains the default and safe fallback. C3-R2/R3/R4
residual-predictor evidence is immutable and remains fallback-only.

## Source admission

The only admitted source is the installed logical path
`<comfyui-root>/comfy/ldm/minimax/model.py` with SHA-256
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`.
The actual `DiTBlock.forward` order, rather than generic Transformer naming,
defines the groups below.

| Order | Logical group | Exact source boundary | Coupling |
|---:|---|---|---|
| 1 | `modulation_parameter_projection` | `self.adaln_proj(t_emb)` producing shift, scale, and gate tensors | `REDUCTION_OR_BROADCAST` |
| 2 | `attention_norm_modulation` | `self.norm1(x)` then `_mod_scale_shift` over `mod_segments` | `POSITIONWISE_OR_LOCAL` |
| 3 | `attention_global_mixing` | `self.attn`, including QKV, RMS/RoPE, optimized attention, and output projection | `GLOBAL_MIXING` |
| 4 | `attention_residual_update` | `_mod_gate` of attention output into the packed stream | `POSITIONWISE_OR_LOCAL` |
| 5 | `feed_forward_positionwise` | `self.norm2`, `_mod_scale_shift`, and `self.mlp` | `POSITIONWISE_OR_LOCAL` |
| 6 | `feed_forward_residual_update` | `_mod_gate` of MLP output into the packed stream | `POSITIONWISE_OR_LOCAL` |

The classification is structural evidence only. It does not authorize token,
region, attention, or residual omission.

## Instrumentation

The repository-owned H3 adapter temporarily replaces the admitted class's
`forward` method with the same six operation groups in the same order. Each
group and the enclosing block receives deferred `torch.cuda.Event` pairs. A
separate event pair encloses the sampler. No per-group synchronization is
allowed; exactly one synchronization occurs after sampler completion before
durations are read. The original class method is restored in `finally`.

For 50 blocks and 20 model forwards, the maximum is 7,001 event pairs or
14,002 event objects: six group pairs plus one enclosing-block pair for each
of 1,000 calls, plus one sampler pair. PyTorch profiler, CUPTI/Nsight, and
kernel-by-kernel profiling remain disabled. CUDA event spans are not reported
as GPU-kernel-duration sums.

Logical-group spans are non-overlapping children of each block span. The
report keeps the enclosing block total, the six child sums, and their signed
remainder. It does not normalize the groups to force a 100 percent breakdown.

Deterministic buckets are fixed before Generation:

- blocks: early `0..16`, middle `17..33`, late `34..49`;
- steps: early `0..6`, middle `7..13`, late `14..19`.

## Comparability Gate

The immutable same-profile Full Compute sampler spans are C0 `486.603692`,
C3-R2 `488.459651`, C3-R3 `488.710265`, and C3-R4 `488.865380` seconds. Their
median, `488.584958` seconds, is the predeclared reference. The instrumented
WebSocket sampler-node wall span must remain within ±5 percent. This is a
comparability check, not a speedup benchmark and not GPU-kernel time.

If the Gate fails, the structural coupling map remains evidence but absolute
cost attribution cannot be promoted. No automatic rerun is allowed.

## Candidate selection

Candidates are ordered by measured sampler CUDA-event share. A primary local
candidate must also be structurally subset-capable, compatible with future
observation metadata, adapter-isolated, and able to restore original Full
Compute. If global attention is dominant while a lower-cost local group is
eligible, the decision is `MIXED_SUBBLOCK_SELECTIVE`: global attention remains
Full Compute and only the highest-cost structurally local group advances as a
separate future candidate. If no local group is eligible and attention is
dominant, select `ATTENTION_COMPUTE_REDUCTION`. Otherwise select the measured
dominant component as `OTHER_COST_DOMINANT_COMPONENT`.

Every ideal elimination ceiling is `THEORETICAL_ONLY`. It assumes zero
dependency closure, verification, orchestration, and fallback cost and is not
an attainable reduction or speedup claim. Isolated 2.0x is not required;
multiple independent quality-preserving components may accumulate toward the
product target `Quality >= Standard Full Compute` and End-to-End ≥2.0x.

## Run and claim budget

- fixed Local H3 Standard profile; seed 101, 864×480, 124 frames, 24 FPS,
  20 steps, `simple`, `res_multistep`, denoise 1.0, native audio, H.264;
- one fresh owned loopback ComfyUI process;
- Generation maximum 1, retry 0;
- all model operations Full Compute;
- skip, reuse, prediction, regional execution, token omission, attention
  omission, Rust ABI change, and selective Generation: zero;
- speedup, quality, and product promotion claims: zero.

## Diagram impact before measurement

`blocked_pending_measurement`: C4-S0 is not drawn as verified until the one
bounded measurement selects a candidate. A successful bounded decision will
update the Living System Map in the evidence commit.
