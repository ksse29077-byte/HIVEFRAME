# M1-P0-R2 Rust Compound Runtime Decision

Decision: **REFINE_RUST_BOUNDARY**

Rust core improves T1/T2, but FFI or boundary evidence is incomplete or offsets the gain.

Compound Perception First remains the product direction. Mono is the comparator and safety fallback, not the R2 product decision.

| Candidate | Python p50 ms | Rust core p50 ms | Boundary-inclusive p50 ms | Core change | Boundary change |
|---|---:|---:|---:|---:|---:|
| T0 | 19.072000 | 14.609900 | 18.895418 | 23.40% | 0.93% |
| T1 | 27.822800 | 18.866600 | 23.152118 | 32.19% | 16.79% |
| T2 | 28.886000 | 18.461000 | 22.746518 | 36.09% | 21.25% |

Semantic parity: `true`.

Deterministic hashes: `true`.

FFI collected: `false`; the v0 transport is one coarse subprocess batch.

H3 API calls: 0. API-key uses: 0. Paid runs: 0. Model downloads: 0. Model loads: 0. CUDA runs: 0.

This is model-free CPU control-plane evidence, not backend, quality, end-to-end, or commercial speedup evidence.
