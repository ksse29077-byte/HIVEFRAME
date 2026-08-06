# C1 Rust Sampler Step Policy Bridge — Full Compute Parity Gate

Date: 2026-08-06
Issue: [#59](https://github.com/ksse29077-byte/HIVEFRAME/issues/59)
Branch: `core/c1-rust-sampler-policy-bridge`
Draft PR: [#60](https://github.com/ksse29077-byte/HIVEFRAME/pull/60)
Base main: `3d6728d3c1826c4171130816c382c5ecec444f43`
Core implementation commit: `2a67be0945529c4b88e0a91bf96902c80a215145`
Status: Draft; one revised runtime validation requires separate approval
Decision: `C1_RUST_POLICY_BRIDGE_REVISE_ONCE`

## Product question and scope

C1 asks whether the shipped Local MiniMax H3 sampler progress callback can transfer one small metadata observation to Rust, receive a deterministic full-compute directive, and preserve the Standard generation path at negligible cost. C1 does not authorize step, block, token, or latent skipping; cache reuse; partial compute; Compound Eye execution; SageAttention; product Fast Mode; or training.

MiniMax H3 remains the production backend and the existing Standard workflow remains the safety fallback. Python, ComfyUI, and PyTorch retain all tensors and GPU work. Rust receives fixed-size scalar metadata and digests only.

## C0 publication prerequisite

The C0 phase map was corrected only for three approved whitespace defects before C1 began. The change preserved all non-whitespace text, values, and line order. Commit `2caaa6eb...` passed the whole-PR `git diff --check`. PR [#58](https://github.com/ksse29077-byte/HIVEFRAME/pull/58) was moved from Draft and merged by a normal merge commit at `2026-08-06T02:40:41Z`; merge commit `3d6728d3c1826c4171130816c382c5ecec444f43` became both local and remote main. Issue [#57](https://github.com/ksse29077-byte/HIVEFRAME/issues/57) was completed. The C0 source branch was preserved.

## Existing workspace and selected bridge

The existing Cargo resolver-2 workspace and the existing `hive-retina-runtime` / `hive-retina-python` crates were reused. No second Rust workspace or per-Eye boundary was introduced.

- Rust: 1.97.1, stable `x86_64-pc-windows-msvc`.
- Cargo: 1.97.1.
- Core policy crate: `hive-retina-runtime`.
- Python extension crate: `hive-retina-python`.
- Boundary: in-process PyO3 0.29, `abi3-py312`.
- ABI version: 1.
- Hook: `sampler.progress_callback`, created by `latent_preview.prepare_callback` inside `SamplerCustomAdvanced`.
- Runtime wrapper: repository-owned `HIVEFRAMERustPolicySampler` custom node.
- Installed ComfyUI source changes: 0.
- Original workflow changes: 0.

The API workflow copy replaces only logical sampler node 10 with the repository wrapper and adds three SHA-256 digests. The wrapper delegates the existing `SamplerCustomAdvanced`, observes at most once per callback, and restores the original callback factory in `finally`.

## ABI contract

`StepObservation` is a `repr(C)`, 184-byte fixed-layout structure. It contains ABI and struct sizes, run/workflow/settings digests, step and total counts, sampler/scheduler enum IDs, optional scalar timestep/sigma bit fields, uncertainty and invalidation flags, and full-compute/fallback/cache/receipt capability flags. It contains no prompt, path, media, tensor, CUDA address, model weight, credential, or variable-length string.

`StepDirective` is a 76-byte fixed-layout structure. Its admitted decisions are exactly `FULL_COMPUTE` and `ESCALATE_FULL_COMPUTE`. It includes a deterministic digest, reason and unsupported flags, and explicit skip/reuse/partial counters that remain zero. Unknown decisions, malformed output, unavailable extensions, nonzero FFI status, Rust panic, ABI mismatch, unsupported metadata, uncertainty, and invalidation all fail open to full compute.

The Rust policy uses no network, file I/O, lock, sleep, random source, or current time. Its panic boundary returns nonzero status rather than unwinding across Python. The policy does not alter scheduler, sigma, latent, or model calls.

## Model-free verification

Before GPU work:

- seven new Python policy/workflow tests passed initially; the corrected suite contains eight;
- the combined C1 and existing ComfyUI-backend focused suite passed 13/13 on the isolated WSL Python 3.12 environment;
- three focused Rust policy tests passed;
- release `hive-retina-python` build and check passed;
- one real extension ABI roundtrip returned `FULL_COMPUTE`;
- the deliberate Rust panic probe was contained;
- the repository custom node registered in ComfyUI 0.30.2 on a separate loopback runtime with queue 0/0 and workflow submissions 0;
- formatter and diff checks passed before the core commit.

The first Windows Python 3.13 invocation of the unchanged backend suite reached all functional assertions but left one SQLite file open during temporary-directory teardown. The same 12-test focused set passed under WSL Python 3.12. This environment-specific cleanup event was not reported as a C1 product pass.

## Exactly one approved runtime attempt

The fixed Standard profile was used: 864x480, 124 frames, 24 FPS, 20 steps, seed 101, `simple`, `res_multistep`, denoise 1.0, native audio, H.264 output, and zero Sage nodes. The private P0 prompt was reused by digest and was not written to Git. GPU preflight observed an RTX 3060 12 GiB with 12,104 MiB free and about 52.0 GB free host RAM. One UI process was listed by NVIDIA with no reported compute memory and total device use was 10 MiB; it was not an active generation workload.

Exactly one workflow was submitted. Private prompt ID: `91b7dc3c-3359-4c81-88ed-508dcd64827f`. The run ended with `execution_error` at the repository sampler wrapper before the first progress callback.

| Observation | Value | Meaning |
|---|---:|---|
| Workflow submissions | 1 | the only authorized C1 generation attempt |
| Retries | 0 | no automatic retry or second generation |
| Callback count | 0 | failure occurred before callback creation completed |
| Rust call count | 0 | no Rust call occurred in the actual H3 attempt |
| FULL_COMPUTE decisions | 0 | unavailable because no callback was reached |
| ESCALATE decisions | 0 | unavailable because no callback was reached |
| Tensor bytes transferred | 0 | no callback boundary was crossed |
| Skipped/reused/partial compute | 0 | no selective directive exists |
| Submit to terminal | 34.443671 s | failed-run diagnostic only, not comparable performance |
| Runner total | 42.639376 s | failed-run diagnostic only |
| Peak ComfyUI sampled VRAM | 12,011,518,624 bytes | sampled, not allocator peak |
| Peak NVIDIA sampled VRAM | 11,623,464,960 bytes | sampled system value |
| Peak process-tree RSS | 19,380,944,896 bytes | sampled process tree |
| Peak system-wide used RAM | 33,749,299,200 bytes | sampled system value |
| OOM | 0 | failure was not memory exhaustion |
| Output video | none | decode and parity gates unavailable |

Boundary p50/p95/max, Rust policy p50/p95/max, cumulative policy time, metadata throughput, video integrity, and C0 parity remain `null/not_collected` because no callback or output existed. The 34.44-second failed submit span must not be presented as a speedup.

## Failure, correction, and evidence boundary

The runtime signature was:

`Cannot modify class attribute '<guard>' on locked ComfyUI V3 node class`

ComfyUI clones and locks V3 node classes. The initial wrapper attempted to mutate a class-level concurrency guard at sampler entry. This was one clear wrapper defect; the Rust ABI and policy were not invoked. After the attempt, the guard moved to module-local state. A model-free direct wrapper call then delegated one callback, performed one Rust call, returned the original result, reset the guard, and transferred zero tensor bytes.

No second H3 generation was run. Therefore the correction is not runtime-parity evidence. The fixed 0.2235-second boundary-P95, 4.866-second cumulative-policy, and 616.336-second submit-to-terminal gates were not changed after seeing the result and remain unpassed.

## Public/private evidence and cost receipt

The generated media count was zero. The full runtime log, raw WebSocket events, raw resource samples, private receipt, actual paths, private prompt, and release build log remain outside Git. Public files contain only logical IDs, sanitized error signatures, aggregate measurements, contracts, and test outcomes. No DLL, PDB, EXE, model, video, credential, token, user path, or prompt is tracked.

- Actual H3 submissions: 1.
- Actual H3 retries: 0.
- Second generation after correction: 0.
- External API calls and paid calls: 0.
- Model downloads: 0.
- Sage generations and alternate accelerator exploration: 0.
- Selective-compute actions: 0.
- Training runs: 0.

## Decision and next action

The bounded decision is **`C1_RUST_POLICY_BRIDGE_REVISE_ONCE`**. The metadata contract, Rust policy, panic containment, custom-node registration, and corrected delegation are model-free verified. A successful full-compute generation, callback/Rust-call counts, timing gates, video integrity, and functional parity are not verified.

The next action requires separate approval for exactly one revised fixed-profile C1 validation using a new collision-free private run root. It must not change the profile, thresholds, policy, model, or workflow; it must not retry on failure. C1 remains Draft and is not eligible for Ready or merge.
