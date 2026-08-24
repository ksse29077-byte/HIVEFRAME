# H3 End-to-End Bottleneck Profile Contract

## Scope

This task measures the unchanged Standard MiniMax H3 image-to-video path. It
does not implement an optimization, execute SELECTIVE or partial-Q work, or
authorize Attention omission. V4 remains frozen as
`EXPERIMENTAL_AUXILIARY_FROZEN`, disabled by default, with no executable plan
and zero product performance contribution.

## Why One Profile Is Required

The immutable C4-S0 run attributes 446.077 seconds, or 91.253 percent of its
488.847-second sampler, to the 1,000 H3 DiT block calls. That evidence is
comparable and already shows global Attention at 70.224 percent and the FF
surface at 19.494 percent of the sampler. It does not separate QKV, QK
normalization and RoPE, the Attention kernel, output projection, the MLP
projections, or model pre/post/offload work. It also does not close the entire
submit-to-terminal ledger at the required 95 percent threshold.

The bounded profile is therefore admitted exactly once. Its fixed input,
prompt, seed, dimensions, frame count, FPS, steps, scheduler, sampler,
precision, offload policy, checkpoint, native audio, and Standard Attention
backend match P1-A2. Sage and every V4 observer/evidence path are disabled.

## Instrumentation Boundary

The repository-owned sampler wrapper records CUDA events around:

- each complete `MiniMaxH3Model._forward`;
- modulation projection and both norm/modulation groups;
- QKV projection, QK normalization plus RoPE, Attention kernel, and output
  projection;
- both residual updates; and
- MLP FC1 and activation plus FC2.

The leaf groups are sequential and mutually exclusive. They are nested inside
the model-forward spans, which are nested inside the sampler span. The ledger
adds only the leaves, model residual, and sampler residual. Parent spans are
never added to their children.

The hot path records events only. One bounded finalize synchronization resolves
all timings. The profiler transfers no tensor payload to the host, stores no
Attention result, emits no row or region records, uses no per-call CPU
synchronization, and enables no PyTorch/CUPTI/Nsight trace. Event objects are
bounded at 22,042.

## Admission And Failure

The runner blocks before submission unless the branch and remote HEAD match,
the worktree is clean, the P1-A2 receipt and private input identities match,
the installed H3 and workflow hashes match, no external product job or runtime
exists, the dedicated port is free, and the fresh runtime process tree passes
the established ownership contract.

After execution, the run requires 20 model forwards, 1,000 block calls, exactly
one finalize synchronization, zero omission/reuse/SELECTIVE counters, zero V4
evidence bytes, at least 95 percent sampler and submit-to-terminal accounting,
and a valid 864x480, 124-frame, 24 FPS H.264 output with native audio. There is
no retry or automatic fallback generation.

## Candidate Decision

Measured surfaces are ranked with an explicit single-factor Amdahl estimate.
The next implementation task must project at least 10 percent end-to-end
reduction, fit RTX 3060 12 GB, preserve exact Standard output semantics or have
a clear A/B quality gate, retain Full Compute fallback, and remain isolated in
the H3 adapter. This profile does not start that implementation.
