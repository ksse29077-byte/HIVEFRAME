# C0-H3 Execution Phase and Runtime Hook Map

Date: 2026-08-06
Issue: [#57](https://github.com/ksse29077-byte/HIVEFRAME/issues/57)
Branch: `core/c0-h3-execution-phase-map`
Base main: `2faa8a7040f0a3d7c855d0bea5d1db1495de6564`
Status: published through PR #58
Decision: `C0_H3_PHASE_MAP_READY`

Publication: PR [#58](https://github.com/ksse29077-byte/HIVEFRAME/pull/58) was merged by normal merge commit `3d6728d3c1826c4171130816c382c5ecec444f43` at `2026-08-06T02:40:41Z`; Issue [#57](https://github.com/ksse29077-byte/HIVEFRAME/issues/57) was completed and the source branch was preserved. The final pre-merge commit changed only three approved whitespace defects and did not alter any C0 text, measurement, YAML value, or claim.

## Product question and boundaries

C0 asks where the shipped Local MiniMax H3 Standard path spends time, which runtime boundaries are observable or controllable, and which single boundary should be handed to a future Rust implementation first. It does not implement Rust acceleration, Compound Eye execution, selective compute, cache reuse, a product Fast Mode, or model training.

The preceding F0 SageAttention result was first published to main through PR #56. That evidence remains `F0_SAGE_NO_GAIN`; SageAttention is dropped as a product accelerator and kept only as optional repository evidence. C0 used the unchanged Standard workflow and zero Sage nodes.

## Repository and implementation sequence

1. PR #56 was reviewed, moved from Draft, and merged with a normal merge commit. Issue #55 was completed, local main was fast-forwarded, and the F0 branch was preserved.
2. A duplicate search found no existing C0 issue, branch, or PR. Issue #57 and this branch were created from the merged main.
3. Model-free telemetry fixtures were implemented before GPU execution. They cover WebSocket lifecycle parsing, progress semantics, non-overlapping phase attribution, resource-to-node association, public sanitization, hook status validation, Standard profile invariants, unsupported metrics, and output collision protection.
4. The first focused run failed six fixture setups because the managed system temp directory denied child writes. Moving only the test temp root to the approved external validation area removed that environmental failure. Nine new C0 tests then passed. An additional unchanged backend focused suite produced one Windows/Python 3.13 SQLite handle-cleanup error after the product assertions; it was not hidden or counted as a product pass.
5. Exactly one fixed Standard H3 generation was submitted. No retry, profiler run, alternate profile, Sage mode, or accelerator exploration occurred.
6. The final changed-surface suite, including public YAML contract validation, passed 10/10 tests.

## Fixed execution profile

- Workflow: `video_minimax_h3_t2v@31ab33fdb053`
- RTX 3060 12 GiB, ComfyUI 0.30.2
- 864x480, 124 frames, 24 FPS, 20 steps
- `simple` scheduler, `res_multistep` sampler, denoise 1.0, seed 101
- native audio, Standard full compute, Sage nodes 0

The result decoded as H.264 at 864x480, 124/124 frames, 24 FPS, with one audio stream. It is 262,576 bytes with SHA-256 `f9654b8b...640998`. Output media, raw WebSocket events, resource samples, prompt, runtime log, and the complete private receipt remain outside Git.

## Phase measurement

| Phase | Seconds | Runner share | Confidence and boundary |
|---|---:|---:|---|
| Runtime startup | 11.627416 | 1.940% | high; runner launch to API ready |
| Loader nodes | 0.745318 | 0.124% | medium; loader-node WebSocket spans only |
| Prompt conditioning and AV latent | 33.672949 | 5.619% | medium; node boundaries |
| Sampler/denoising node | 486.603692 | 81.196% | medium; includes lazy model initialization and orchestration |
| Audio VAE decode | 1.256777 | 0.210% | medium; node boundary |
| Video VAE decode | 63.162271 | 10.539% | medium; node boundary |
| Video assembly and MP4 encode | 1.540392 | 0.257% | medium; node boundaries |
| Result collection/decode gate | 0.131205 | 0.022% | high; terminal event to verified result |
| Runtime shutdown | 0.001268 | <0.001% | high; owned process stop |
| Unattributed | 0.556859 | 0.093% | high; total minus non-overlapping union |

Submit-to-terminal was 586.986496 seconds and runner entry-to-stop was 599.298147 seconds. The historical Standard submit span was 586.972500 seconds; the instrumented run changed it by +0.002385%, within the fixed 5% comparison bound. This is a one-run comparability check, not a new performance benchmark.

Twenty progress intervals were observed. Their median was 22.353163 seconds and P90 was 22.361236 seconds. The first interval was 62.018464 seconds while the runtime log reported model initialization inside the sampler. These are client-observed progress intervals, not exact denoising-step GPU durations. Independent model materialization time and GPU-kernel duration remain `null/unavailable` or `null/not_collected` with reasons.

## Resource observation

The observer collected 540 one-second samples in a parallel thread. Its queries consumed 44.805064 seconds of observer-thread wall time; this value was not subtracted from the official runner time. Peak values were:

- ComfyUI system-reported VRAM: 12,481,828,788 bytes;
- NVIDIA system-sampled VRAM: 11,956,912,128 bytes;
- GPU utilization: 100%;
- ComfyUI process-tree RSS: 47,271,677,952 bytes;
- system-wide used RAM: 61,114,191,872 bytes.

These are sampled system/process values, not allocator peaks. The exact PyTorch allocator peak was unavailable from the external process and remains null.

## Hook map and selected target

The public hook map classifies node execution boundaries, conditioning, sampler boundaries, progress callbacks, model calls, transformer blocks, attention/QKV, latent access, patch/tile recompute, cache reuse, residency/offload, VAE decode, and the Standard fallback. Every entry states whether it is observable now, controllable now, needs a runtime wrapper/custom node/core patch, was not found, or is unsafe.

Exactly one target is selected: `sampler.progress_callback`. The future Rust boundary is coarse and metadata-only. Python/ComfyUI retain tensors and GPU work; Rust receives one `StepObservation` and returns a deterministic directive. The first implementation must always preserve `FULL_COMPUTE` or escalate to it. No tensor round trips, per-eye calls, cache reuse, or selective execution are admitted by C0.

## Verification and cost receipt

- Final C0 model-free and public-contract tests: 10/10 passed (the initial code-only set was 9/9).
- Python compile for changed modules: passed.
- `git diff --check`: passed before the instrumentation commit.
- Actual H3 generations: 1.
- Generation retries: 0.
- Sage nodes and Sage generations: 0.
- Model downloads: 0.
- External API and paid calls: 0.
- Rust code, Compound Eye runtime, selective compute, cache reuse, Fast Mode, and model training: 0.

## Claim boundary and next action

`C0_H3_PHASE_MAP_READY` means that one Standard run produced a usable phase map, source-backed hook map, and a bounded Rust handoff target. It does not mean any Core acceleration exists or that selective computation is safe or faster.

The next approved implementation should be a parity-only Rust sampler-step policy bridge with zero tensor bytes across FFI, deterministic receipts, bounded overhead, and mandatory Standard full-compute fallback. That work requires a new issue, branch, and approval.
