# H3 Tier-B Exact Attention Backend Fusion A/B

## Decision

`H3_TIER_B_FUSION_KERNEL_NOT_VIABLE`

The bounded product-shape kernel Admission Gate failed before any H3 model
load or Generation. Baseline and candidate submissions are `0/0`, retry is
zero, and the fixed paired A/B was not started.

## Scope And Repository Isolation

- Task: `H3_TIER_B_EXACT_ATTENTION_BACKEND_QKV_ROPE_OUT_FUSION_AB`
- Exact base: PR #140 HEAD
  `c996d73233ed1a64eb3e1b1e04fe084390c19f32`
- Issue: #141
- Branch: `codex/h3-tier-b-exact-attention-fusion-ab`
- Draft PR: #142, stacked on PR #140
- PR #138 and PR #140 changes: zero
- V4 state: `EXPERIMENTAL_AUXILIARY_FROZEN`
- SELECTIVE, partial-Q, cache reuse, and Attention omission: disabled

## Installed Exact Path

The installed H3 source uses one packed QKV projection, split/view packing,
the fused in-place CK RMSNorm plus RoPE operation, ComfyUI
`attention_pytorch`, and a separate output projection. ComfyUI gives PyTorch
SDPA the priority order Flash, cuDNN, memory-efficient, then math. This Windows
PyTorch build has no compiled Flash Attention kernel for the product shape, so
the baseline resolves to cuDNN SDPA.

Installed public source digests:

| Source | SHA-256 |
|---|---|
| H3 model | `882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024` |
| Comfy Attention dispatch | `a540a0b487eb5979c4dbc38c72926e3a38b5e41480a038a98707e2eef7e038d9` |
| Comfy operations | `aa6dc3dd7f2d6b04f9e3f5df949348a4734f5f9af4d08891c57c8a64986d3782` |

## Capability Contract

The new registry declares `attention_pytorch` and the bounded
`h3_exact_fused_v1` candidate. Unsupported device, dtype, shape, layout,
mask, causal mode, dropout, mismatched Q/K/V, or native failure immediately
uses Standard Full Compute. The receipt records backend, manifest digest,
fallback reason/count/call position, and the fixed no-omission counters.

The candidate name is retained from the approved work order, but its manifest
sets `fusion_claimed: false`. The installed stack exposes no safe distinct
QKV, RoPE, or output-projection fusion primitive. The implemented candidate
only removes the generic dispatch layer while explicitly invoking the same
cuDNN SDPA and Standard output reshape.

## A0-A5 Ablation

Environment: RTX 3060 12 GiB, compute capability 8.6, PyTorch 2.12.1+cu130,
CUDA 13.0, BF16 shape `[1, 56, 15424, 128]`. Warm results use two warmups and
eight interleaved repeats. The sequential cold values are retained in the
JSON but are not compared because the first call pays shared cuDNN
initialization.

| ID | Surface | Result |
|---|---|---|
| A0 | installed `attention_pytorch` | p50 270.982 ms; p95 271.190 ms; two CUDA kernels |
| A1 | QKV projection and packing | no distinct candidate; one packed projection already exists and split/views launch no kernels |
| A2 | Q/K RoPE | no distinct candidate; fused in-place CK RMSNorm plus RoPE already exists |
| A3 | Attention backend | direct cuDNN p50 270.990 ms, p95 271.135 ms; memory-efficient alternative p50 411.512 ms, p95 411.618 ms |
| A4 | output transform/projection | no safe distinct fused projection kernel in the installed stack |
| A5 | combined candidate | not a fusion candidate; only direct cuDNN dispatch is implemented |

Profiler inventory proves that A0 and the candidate both execute the same
cuDNN SDPA kernel followed by the same direct-copy reshape kernel. Both use
four allocations and the same 442,236,928-byte incremental allocated peak in
the model-free fixture. The memory-efficient alternative uses one kernel and
less temporary allocation, but is about 51.9 percent slower.

## Parity And Fallback

- Shape, dtype, and device parity: PASS
- Bitwise equality: PASS
- Maximum and mean absolute error: `0.0 / 0.0`
- Candidate nonfinite values: zero
- Q and KV work: `100% / 100%`
- Omission, SELECTIVE, and partial-Q: zero
- Candidate fallback in admitted measurement: zero
- Forced native-error fallback regression: PASS
- Unsupported-contract silent execution: zero

## Performance Admission

The candidate-to-baseline warm p50 ratio is `1.000030237`. Applied only to the
previously measured 314.552-second Attention kernel surface, it predicts a
small regression:

- predicted sampler reduction: `-0.001793%`
- predicted submit-to-output reduction: `-0.001495%`
- required sampler reduction: at least `10%`
- required submit-to-output reduction: at least `10%`

All parity, fallback, nonfinite, p95, workspace, and physical-headroom checks
passed. Both required performance checks failed. Planned or speculative gains
from QKV, RoPE, and output projection were not added because no real fused
implementation exists.

## Generation Stop

The pre-Generation Admission Gate failed. Per the approved contract:

- H3 model loads: 0
- CONTROL submissions/GPU starts/completions: `0/0/0`
- candidate submissions/GPU starts/completions: `0/0/0`
- retry: 0
- quality threshold changes: 0
- product UI/default changes: 0

No output-quality comparison was manufactured because no paired output was
generated. The existing Standard quality contract remains unchanged.

## Verification

- focused capability/fallback tests: 7 PASS
- adjacent H3 E2E profile tests: 7 PASS
- Python compile: PASS
- `cargo fmt --all -- --check`: PASS
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: PASS
- `cargo test --workspace --all-features`: 50 PASS
- `cargo build --workspace --all-features --release`: PASS; MSVC emitted its
  existing import-library linker message
- architecture diagram impact: none; the candidate was not admitted into the
  product path

## Conclusion

The original profile's 20 percent removable-fusion assumption does not exist
in the installed backend stack. Standard H3 already uses a fused RoPE
primitive and cuDNN SDPA, while packing is view-only. A direct exact backend
adapter reproduces the same two kernels and cannot produce the required 10
percent E2E gain. The fixed A/B was correctly blocked without spending two
full Generations.

The largest unresolved bottleneck remains the 314.552-second cuDNN Attention
kernel surface itself. A future task would need a materially different exact
kernel implementation or a separately approved strategy change; wrapping the
installed backend again is not a credible next experiment. No follow-up is
started by this result.

```text
H3_TIER_B_FUSION_KERNEL_NOT_VIABLE
```
