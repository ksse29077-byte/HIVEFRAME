# H3 Tier-B Attention Fusion Final Report

The exact BF16 product-shape Admission Gate was evaluated before any H3
Generation. Standard `attention_pytorch` and the bounded direct cuDNN
candidate were bitwise identical, used the same two CUDA kernels, and measured
270.982 ms versus 270.990 ms warm p50. The only distinct installed exact SDPA
alternative measured 411.512 ms p50.

The direct candidate predicts `-0.001793%` sampler reduction and `-0.001495%`
submit-to-output reduction against the prior live profile. Both required 10
percent Gates failed. Baseline and candidate Generation submissions therefore
remain `0/0`, with retry zero.

Full public evidence:

- `artifacts/h3-tier-b-attention-ablation-20260824.json`
- `docs/worklogs/2026-08-24-h3-tier-b-exact-attention-fusion-ab.md`
- `knowledge/h3/h3_tier_b_attention_backend_ablation.yaml`

```text
H3_TIER_B_FUSION_KERNEL_NOT_VIABLE
```
