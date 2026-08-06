# H3 Rust Acceleration Handoff Contract

Status: design only; no Rust implementation, selective compute, cache reuse, or product Fast Mode is included.

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
