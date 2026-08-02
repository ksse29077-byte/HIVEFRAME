# M1-P0-R2 Rust Compound Runtime Decision

Decision: **REFINE_RUST_BOUNDARY**

Rust core improves T1/T2, but FFI or boundary evidence is incomplete or offsets the gain.

Compound Perception First remains the product direction. Mono is the comparator and safety fallback, not the R2 product decision.

| Candidate | Python p50 ms | Rust core p50 ms | Boundary-inclusive p50 ms | Core change | Boundary change |
|---|---:|---:|---:|---:|---:|
| T0 | 19.186000 | 14.798700 | 15.167595 | 22.87% | 20.94% |
| T1 | 28.073600 | 18.653200 | 19.022095 | 33.56% | 32.24% |
| T2 | 29.271800 | 18.312000 | 18.680895 | 37.44% | 36.18% |

Semantic parity: `true`.

Deterministic hashes: `true`.

FFI collected: `false`; the v0 transport is one coarse subprocess batch.

H3 API calls: 0. API-key uses: 0. Paid runs: 0. Model downloads: 0. Model loads: 0. CUDA runs: 0.

This is model-free CPU control-plane evidence, not backend, quality, end-to-end, or commercial speedup evidence.
