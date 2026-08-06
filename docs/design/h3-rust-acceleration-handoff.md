# H3 Rust Acceleration Handoff Contract

Status: C1 metadata bridge full-compute parity verified once. No selective compute, cache reuse, or product Fast Mode is included.

## Selected boundary

C0 selects exactly one next target: the `SamplerCustomAdvanced` progress/callback and model-wrapper control plane. The observed sampler node occupied 486.604 seconds, or 81.196% of the instrumented runner span. That span includes lazy model initialization and sampler orchestration, so it is not a GPU-kernel duration. Even with that limitation, it is the only dominant phase with an existing callback path and a coarse metadata boundary.

The first Rust work must not receive CUDA tensors, QKV buffers, latents, model weights, or prompts. Python/ComfyUI/PyTorch retain all model tensors and GPU execution. Rust receives a small, versioned `StepObservation` and returns a deterministic `StepDirective`. The initial implementation is parity-only and must return `FULL_COMPUTE` for every step.

```text
ComfyUI sampler callback
    -> Python adapter builds StepObservation
    -> one coarse Rust FFI call
    -> Rust validates state and returns StepDirective
    -> Python executes full H3 step or immediately falls back
```

## Input contract

`StepObservation` contains only:

- schema version, run ID digest, workflow revision, and settings digest;
- repeat-safe step index, total step count, and scheduler/sampler logical IDs;
- scalar timestep/sigma metadata if available without synchronization;
- `SharedVisualState` and `ComputePlan` digests, not their private payloads;
- capability flags for full-frame compute, cache availability, and fallback;
- uncertainty, invalidation, and receipt flags;
- optional device-resident buffer handle metadata only after a separate zero-copy admission gate.

Prompt text, user paths, media, credentials, model filenames, host tensor copies, CUDA tensor contents, and model weights are forbidden at this boundary.

## Output contract

`StepDirective` contains:

- decision: `FULL_COMPUTE`, `ESCALATE_FULL_COMPUTE`, or a future separately admitted selective action;
- deterministic decision digest;
- reason code and unsupported-capability list;
- cache key and invalidation metadata only when a later cache gate admits them;
- receipt fields for Rust core time, Python wrapper time, FFI time, bytes copied, and fallback use.

For the first implementation, only `FULL_COMPUTE` and `ESCALATE_FULL_COMPUTE` are valid. Unknown schema versions, missing fields, timeouts, Rust failures, uncertainty, or unsupported capabilities must fail open to the unchanged Standard H3 path.

## C1 implementation and observed boundary

C1 uses the existing Cargo workspace rather than creating a new runtime. `hive-retina-runtime` owns the deterministic policy and fixed-layout structs; `hive-retina-python` exposes one in-process PyO3 0.29 call through the existing `abi3-py312` extension. ABI version 1 uses a 184-byte `StepObservation` and a 76-byte `StepDirective`. Each normal callback may issue at most one Rust call. The declared transferred metadata is the two struct sizes per call, and tensor bytes are always zero.

The repository-owned `HIVEFRAMERustPolicySampler` delegates the installed `SamplerCustomAdvanced` implementation. It temporarily wraps `latent_preview.prepare_callback` in the owned process, calls the Rust policy before delegating the original callback arguments unchanged, and restores the original function in `finally`. The installed ComfyUI source and the original workflow remain unchanged. Removing the custom-node search path restores the Standard node immediately.

Model-free verification covered deterministic full-compute directives, explicit escalation, malformed/unknown response fallback, ABI roundtrip, a contained Rust panic, original-callback delegation, fixed digests, zero tensor transfer, and actual ComfyUI custom-node registration. The single approved runtime submission then failed at wrapper entry before the first callback because ComfyUI V3 locks its cloned node class and the first wrapper version attempted to mutate a class-level concurrency guard. Therefore callback count, Rust-call count, policy timing, transferred bytes for the actual run, and video parity are unavailable rather than zero-valued performance evidence.

The guard was moved to module-local state after the failed attempt and the corrected delegation path passed a model-free direct-call check with one callback and one Rust call. A separately approved regression then submitted the unchanged Standard profile exactly once. It observed 20 callbacks, 20 Rust calls, and 20 `FULL_COMPUTE` directives with zero escalation, fallback, skip, reuse, partial compute, or tensor transfer. Boundary p95 was 38.1 microseconds, the predeclared conservative cumulative policy span was 2.592 milliseconds, and submit-to-terminal was 556.433128 seconds. All fixed gates passed.

The 864x480 H.264 output decoded all 124 frames at 24 FPS and contained one audio stream. OOM, retry, black-frame, corrupted-frame, CUDA-error-signature, and NaN-signature counts were zero under their recorded checks. The bounded result is `C1_RUST_POLICY_BRIDGE_READY`, verified once and not promoted to a product default. Full compute remains the mandatory fallback. The next separate handoff is a shadow-only Compound Eye policy that changes no H3 computation and reports zero skipped work.

## Acceptance gates for the first implementation

1. Exact output and execution parity with the Standard full-compute path.
2. One FFI call per sampler callback at most; no per-eye or per-block language ping-pong.
3. Zero model, latent, QKV, or frame bytes copied across FFI.
4. Deterministic directive digest for identical observations.
5. P95 decision overhead no greater than 1% of the C0 steady progress interval (0.2235 seconds based on the observed 22.353-second median), with a stricter product target to be set before implementation.
6. Explicit timeout and full-compute fallback tests.
7. Unsupported metrics remain `null` with status and reason; they are never zero-filled.
8. No product speedup claim until an end-to-end paired run includes detection, policy, FFI, fallback, decode, and output costs.

## Deferred boundaries

Attention/QKV access, transformer-block skipping, patch/tile recompute, latent reuse, cache invalidation, VAE regional decode, GPU-resident shared state, and Compound Eye execution remain deferred. They require separate capability and safety gates. C0 does not authorize any of them.

## Source-call-chain basis

The installed ComfyUI source was inspected without modification. The logical call chain is:

1. `execution.py::PromptExecutor.execute_async` emits lifecycle messages and dispatches nodes.
2. `comfy_extras/nodes_minimax_h3.py::MiniMaxH3ImageToVideo.execute` builds text conditioning and the audio/video latent.
3. `comfy_extras/nodes_custom_sampler.py::SamplerCustomAdvanced.execute` creates `latent_preview.prepare_callback` and invokes `guider.sample`.
4. The sampler calls the patched model path ending at `comfy/ldm/minimax/model.py::MiniMaxH3Model.forward`.
5. `nodes.py::VAEDecode`, `comfy_extras/nodes_audio.py::VAEDecodeAudio`, and the video nodes decode and encode the result.

This call chain identifies reachable boundaries only. It does not prove that skipping or caching any computation is correct.
