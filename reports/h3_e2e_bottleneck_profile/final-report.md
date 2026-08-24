# H3 End-to-End Bottleneck Profile Final Report

1. **Starting and final work HEAD.** The stacked task started from exact PR
   #138 HEAD `6747e96a6ca94cdb4f137aebc36b86eb4b5b08b4`. The profile ran from clean
   local/origin HEAD `7615ce512df8a37c906a9479ca12f317308edc6e`; the final evidence commit is
   reported by Git after this document is committed.
2. **Issue, branch, Draft PR.** Issue #139; branch
   `codex/h3-e2e-bottleneck-profile-plan`; stacked Draft PR #140.
3. **PR #138 preservation.** PASS. PR #138 remains OPEN/DRAFT and unchanged.
4. **Existing-only analysis.** P1-A2, C4-S0, final V4, runtime logs, CUDA
   timing, allocator, and VRAM evidence were reused. C4-S0 closed only 91.253%
   of sampler detail, so one bounded Standard profile was necessary.
5. **New Formal Profile submitted.** Yes, exactly once. No second execution.
6. **Submission/GPU/completion.** `1/1/1`; retry/fallback `0/0`; SELECTIVE,
   partial-Q, and omission `0/0/0`.
7. **Runtime/model load.** Process-to-ready 10.617s; loader nodes 0.992s.
   First progress interval was 65.718s versus 24.431s median, a 41.287s excess
   consistent with lazy first-step materialization but not separately traced.
8. **Sampler and steps.** Sampler wall 530.496s; CUDA span 529.617s. Twenty
   observed intervals: mean 26.286s, median 24.431s, p90 24.464s, first
   65.718s, last 24.427s.
9. **Attention total.** 386.568s including Attention norm/modulation and
   residual: 72.869% of sampler and 60.780% of submit-to-output.
10. **QKV/out projection.** QKV 43.739s; QK norm/RoPE 5.041s; kernel
    314.552s; out projection 16.906s. The selected fusion surface is 380.238s.
11. **MLP/FFN.** 100.812s including FF norm and residual; FC1 56.841s and
    activation+FC2 38.126s. This is 19.003% of sampler and 15.851% E2E.
12. **Norm/RoPE/conditioning.** Attention norm 4.634s, QK norm/RoPE 5.041s,
    FF norm 4.132s, modulation projection 0.105s; external input/prompt
    conditioning 38.719s.
13. **Offload H2D/D2H.** Exact transfer-stream time is
    `NOT_COLLECTED_BY_CONTRACT`; profiler trace, tensor payload D2H, and
    per-call sync were forbidden. Model pre/post/offload residual is 37.787s.
14. **CPU wait/synchronization.** Sampler wall minus CUDA span is 0.879s.
    Hot-path forced CPU sync is zero. One finalize sync took 0.0000385s.
15. **Allocator/VRAM.** Torch max allocated/reserved 2.332/3.590 GB;
    ComfyUI/NVIDIA sampled peak 12.458/11.724 GB; physical headroom by the
    ComfyUI sample 406.4 MiB; process-tree RSS peak 44.959 GB. Sampler mean GPU
    utilization 94.72%, idle sample ratio 3.16%.
16. **VAE decode.** Video 62.207s; audio 1.210s.
17. **Encode/mux/output.** Encode/mux/save 1.603s; retrieval/decode/receipt
    0.762s. Output PASS: H.264, 864x480, 124 frames, 24 FPS, audio, zero black,
    corrupted, or exact-adjacent-duplicate frames.
18. **Accounted/unaccounted.** Submit-to-output 636.011s, fully represented by
    mutually exclusive top-level spans. Sampler and transformer parents are
    nested and excluded from child sums. Accounted 100%; unaccounted 0s.
19. **Profile overhead.** Exact overhead is `UNKNOWN_FROM_AVAILABLE_SAME_INPUT_STANDARD_RECEIPT`.
    Versus C4-S0 sampler the delta is +41.648s (+8.520%), but C4-S0 did not use
    the same first-frame path; versus V4 it is -7.159s (-1.331%), but V4 carried
    19.646 GB of evidence transfers. Neither comparison isolates profiler cost.
20. **V4 Rust rejection.** Candidate/selected/rejected `13/0/13`. Every grouped
    candidate had reason 1, `CACHE_REJECT_NOT_STABLE`; first rejection was
    block 0/region 0. Zero selected rows then caused final reason 9,
    `PRE_GATE_BELOW_THREE_PERCENT`. Row evidence 3.007449% therefore became
    Rust planned reduction 0%.
21. **Amdahl ceilings.** Attention fusion: 11.957% expected E2E, 1.1358x;
    VAE pipeline: 3.067%, 1.0316x; MLP fusion: 2.986%, 1.0308x; offload:
    2.971%, 1.0306x. These are planning estimates, not measured speedups.
22. **Tier classification.** Attention fusion `TIER_B`; VAE pipeline `TIER_C`;
    MLP and offload `AUXILIARY`; V4 `AUXILIARY/FROZEN`; no admitted TIER_A.
23. **Compatibility.** The full matrix is in
    `knowledge/h3/h3_end_to_end_bottleneck_profile.yaml`. Attention fusion is
    compatible with unchanged offload and VAE, requires A/B with Compile/Graph
    or step/distill, and is exclusive with alternative Attention backends.
24. **Selected next implementation.** `H3_TIER_B_EXACT_ATTENTION_BACKEND_QKV_ROPE_OUT_FUSION_AB`.
25. **Single and combined expected gain.** Selected-only estimate saves
    76.048s and projects 559.963s submit-to-output. Benefits must not be added
    to Compile/Graph without removing overlapping Attention time.
26. **RTX 3060 fit.** Conditionally feasible with no persistent cache, at most
    256 MiB incremental VRAM, at least 128 MiB remaining reserve, and at most
    512 MiB incremental host RAM. Admission uncertainty selects Standard.
27. **Quality risk.** Low but nonzero due kernel/fusion arithmetic ordering;
    same-input paired A/B, unchanged automatic thresholds, technical integrity,
    and human visual review are required.
28. **Product integration.** H3 adapter capability selected through existing
    `GenerationContext` and runtime profile; original `attention_pytorch` Full
    Compute remains the independent fallback; receipt and cleanup remain common.
29. **Exact next instructions.** See
    `docs/design/h3-tier-b-attention-backend-fusion-ab-work-order.md`: CONTROL 1,
    candidate at most 1, retry 0, both sampler and submit-to-output at least 10%
    faster, unchanged quality, no automatic follow-up.
30. **Two-minute realism.** Current E2E must fall 81.132%. If 105.515s
    non-sampler time stays fixed, sampler must fall 97.270%. The selected Tier-B
    task projects about 560s, not 120s. A credible two-minute target requires
    several non-overlapping gains plus a model/scheduler/hardware architecture
    change; current quality-preserving Standard-H3 tuning alone is insufficient.

```text
H3_HIGH_IMPACT_PROFILE_COMPLETE_READY_FOR_IMPLEMENTATION
```

## Quality-Preserving Candidate Ledger

`Upper` is the affected E2E surface, not attainable speedup. `Expected` applies
the stated removable fraction and subtracts no unmeasured overhead, so every
candidate still requires a real paired benchmark.

| Candidate | Surface | Upper | Expected | Tier | Added memory | Difficulty | Quality/license/distribution | Overlap and fallback |
|---|---:|---:|---:|---|---|---|---|---|
| Attention backend + QKV/RoPE/out fusion | 380.238s | 59.785% | 11.957% at 20% removal | TIER_B | <=256 MiB VRAM, <=512 MiB RAM | high | arithmetic-order A/B; no new model/license; original PyTorch path ships | overlaps Compile/Graph; exact Standard fallback |
| VAE decode + encode/mux pipeline | 65.020s | 10.223% | 3.067% at 30% removal | TIER_C | bounded frame staging | medium | exact decode and codec unchanged | overlaps offload scheduling; serial fallback |
| MLP projection/activation fusion | 94.967s | 14.932% | 2.986% at 20% removal | AUXILIARY | small temporary workspace | high | arithmetic-order A/B; no new model | overlaps Compile/Graph; original MLP fallback |
| Offload overlap/rearrangement | 37.787s | 5.941% | 2.971% at 50% removal | AUXILIARY | must stay inside existing peak | high | exact values/order | conflicts with V4 transfers; current offload fallback |
| Norm/RoPE/modulation fusion | 13.912s | 2.187% | 0.437% at 20% removal | AUXILIARY | negligible to small | medium | arithmetic-order A/B | overlaps selected Attention task; original ops fallback |
| CPU sync removal | 0.879s | 0.138% | <=0.138% | AUXILIARY | none | low | none | no meaningful 2-minute contribution |
| Encode/mux overlap only | 1.603s | 0.252% | <=0.126% | AUXILIARY | bounded frame staging | medium | codec unchanged | overlaps VAE pipeline; serial fallback |
| Persistent model residency | 37.787s residual ceiling | 5.941% | not admitted | NOT_VIABLE | only 406.4 MiB sampled headroom | high | none | VRAM reserve Gate fails for broad residency |
| Persistent CUDA graph | broad transformer | unknown | not admitted | NOT_VIABLE | unknown capture pools | high | exact path intended | prior live H3 capture failed; Standard fallback |
| `torch.compile` | up to 525.271s parent | 82.588% | unknown | UNKNOWN | unknown compile workspace | high | backend parity A/B | overlaps Attention and MLP; separate admission required |
| Allocator/buffer reuse | unisolated | unknown | unknown | UNKNOWN | may reduce reserve | medium | none | no isolated stall evidence; Standard allocator fallback |

## Quality-Risk Candidate Ledger

| Candidate | Measured bound or evidence | Classification | Why it is not the selected next task |
|---|---|---|---|
| Step reduction | one observed median step is 24.431s, about 3.84% E2E; three steps could cross 10% before overhead | TIER_C per step / REQUIRES_AB | direct temporal and denoising quality risk |
| Distilled scheduler/model | no admitted local same-input result | UNKNOWN / REQUIRES_AB | model and quality contract change, rights and distribution review required |
| Quantization | no same-input H3 result | UNKNOWN / REQUIRES_AB | quality and kernel compatibility risk |
| Sage Attention | existing F0 measured only 1.207x against a 1.3x Gate and reported no gain | NOT_VIABLE for current promotion | below its fixed admission Gate and quality review remains separate |
| V4/cache expansion | executable plan 0%; all 13 candidates not stable | AUXILIARY/FROZEN | no executable work-reduction plan |
| Block/step skipping | no admitted quality-preserving policy | UNKNOWN / REQUIRES_AB | direct quality risk and overlaps step/distill |
| Alternate checkpoint/model | no admitted local result | UNKNOWN / REQUIRES_AB | changes quality, rights, packaging, and product identity |

## Combination Rule

Do not add reductions that touch the same measured surface. Attention fusion,
Compile/Graph, MLP fusion, and broad step/model changes overlap. VAE pipeline
is mostly independent from transformer compute; offload overlap can interact
with both transformer and VAE scheduling. Combined estimates must subtract the
shared affected time before applying Amdahl's formula.
