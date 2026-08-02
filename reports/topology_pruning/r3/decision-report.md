# M1-P0-R3 In-process Shared-buffer Decision

Decision: **RUST_CONTROL_PLANE_ADMITTED**

All predeclared latency, boundary, copy, and semantic safety gates passed.

This model-free control-plane result does not claim real-video or model speedup.
Compound Perception First remains the product direction; Mono remains only the comparator and safety fallback.

| Candidate | Python p50 | Rust boundary p50 | p50 change | Python p95 | Rust p95 | boundary fraction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T0 | 0.018802600s | 0.014891200s | +20.80% reduction | 0.023665200s | 0.017290500s | 0.19% |
| T1 | 0.027280300s | 0.018765800s | +31.21% reduction | 0.037660300s | 0.021741700s | 0.16% |
| T2 | 0.028724800s | 0.018389700s | +35.98% reduction | 0.032949000s | 0.021484400s | 0.16% |

The run used 5 warm-ups and 30 same-process paired blocks per candidate.
Input copies, subprocesses, temporary files, model loads, and CUDA runs were zero.
