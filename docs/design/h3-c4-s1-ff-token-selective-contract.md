# C4-S1 H3 feed-forward token-selective contract

Status: predeclared, not product-promoted

## Product question

Can HIVEFRAME keep MiniMax H3 global attention at Full Compute while omitting
only causally admitted, very-low-impact target-video token rows from the
positionwise feed-forward sub-block, using previous actual Full Compute
evidence and current pre-MLP signals, without lowering the fixed Quality-First
gates?

## Immutable source and row identity

The admitted installed H3 source SHA-256 is
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`.
It constructs a contiguous packed sequence whose target audio and target video
are the final two segments, with target video last. `patchify_video` orders rows
as batch, latent time, patch height, patch width (`nthw`). The fixed observed
video latent `[1,24,37,30,54]` therefore maps to 14,985 target-video rows. The
hidden width is 5,376. Any hash, layout, segment, shape, dtype, device, or token
identity mismatch fails open to the original full MLP.

The H3 MLP is positionwise `Linear -> SwiGLU -> Linear`, so an arbitrary row
subset is structurally executable. This source fact is admission to one bounded
probe, not evidence that row omission preserves quality.

## Fixed selector

`FF_POSITIONWISE_LOW_IMPACT_TOKEN_SKIP_V1` uses only current pre-MLP `h` norm,
current gate norm, and previous **actual Full Compute** per-row history:
`prev_h_norm`, `prev_ff_delta_ratio`, `prev_gate_norm`, and `history_valid`.

`prev_ff_delta_ratio = ||prev_ff_delta||2 / max(||prev_x_after_attention||2,
1e-6)`. Current MLP output and current FF delta are prohibited from the live
selector. CONTROL may observe the current actual delta only after the decision,
for shadow validation. The three policies are frozen in
`configs/c4_s1_ff_token_selective.json`; results cannot change them.

Steps 0, 1, 18, and 19 are Full Compute anchors. Audio, text, conditioning,
references, and unknown rows are always Full Compute. A skipped row becomes
history-invalid immediately and cannot skip again until an actual Full Compute
refresh. If a block would omit less than 10% of its target-video rows, the
original full MLP executes to avoid a gather/scatter loss.

## Execution and memory

Attention is always the installed full global attention. For an admitted
SELECTIVE block, all non-video rows plus active video rows are gathered, the
MLP is called at most once, and gated contributions are scattered only to those
rows. A skipped video row receives zero FF contribution. Applying a mask after
running the full MLP is prohibited.

Persistent state contains scalar metadata only and is capped at 64 MiB. There
is no full activation/residual cache, host full-tensor copy, tensor-to-Rust
transfer, or Rust ABI change. Invalid or non-finite state, segment ambiguity,
mapping errors, selector errors, runtime errors, and global invalidation all
restore Full Compute.

## Measurement and gates

CONTROL is compared with the immutable C4-S0 sampler span `488.847320 s` and
must remain within plus or minus 5%. CONTROL executes all FF rows and evaluates
P0/P1/P2 counterfactually. The admission and quality thresholds are frozen in
the config. If no policy passes, SELECTIVE is prohibited. If admitted, exactly
one SELECTIVE generation may execute with that frozen policy.

CUDA events are deferred and synchronized once after the sampler. Event spans
cover sampler, full FF group, actual MLP, gather/mask, and scatter/residual.
They are not GPU kernel-duration sums. Profiler and Nsight are disabled.

One pair can verify a component mechanism only. It cannot establish general
speedup, visual equivalence, product promotion, or cumulative end-to-end 2x.
Automatic objective quality passage still requires private human visual review.
