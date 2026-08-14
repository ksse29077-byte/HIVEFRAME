# A3-G1 Real H3 Selective Attention

Date: 2026-08-14

Status: stopped at the model-free, source-readonly structural Gate

Decision: `A3_G1_REAL_H3_CONDITIONAL_GRAPH_BODY_NOT_CONNECTABLE`

Base main: `f5d2bf8c2f80612909eef21c555d764a116f7062`

Branch: `codex/a3-g1-real-h3-selective-attention`

Implementation commit: `c78e05f`

## Product question

> When the G0 GPU conditional omission primitive is connected to actual H3
> Attention, can it skip actual Attention work and reduce runtime while
> preserving quality?

This was the only product question. The work did not expand into residency,
prefetch, a complete CUDA block, Sage, a new Attention approximation, a new
correction, low resolution, extra Generation, or A3-G1-R1.

## Work separation and starting state

The unrelated P1-F/Image-to-Video work was preserved before A3-G1:

- branch: `codex/p1-h3-two-minute-profile`;
- independent commit: `e04259f`;
- pushed before the A3-G1 branch was created;
- A3-G1 history starts directly from the required clean main commit;
- P1-F files and commit are absent from the A3-G1 diff;
- no temporary commit was made on `main`.

The A3-G1 profile was frozen before the Gate: 864x480, 20 steps, 124 frames,
24 FPS, seed 101, `simple`, `res_multistep`, unchanged A3 prompt/guidance, Sage
disabled, CONTROL maximum one, SELECTIVE maximum one, and retry zero. Existing
A3 correction and quality thresholds were not changed.

## Minimal structural Gate

Only five source boundaries were read:

1. installed H3 `model.py`;
2. installed ComfyUI `attention.py`;
3. G0 `conditional_omission.cu`;
4. G0 `binding.cpp`;
5. G0 `conditional_omission.h`.

No C2, A1, A2, A3, or G0 generation/runtime evidence was replayed. The Gate
loaded no model, launched no CUDA work, generated no media, and consumed no
CONTROL or SELECTIVE budget.

## Findings

The actual H3 exact path is source-identifiable:

`DiTBlock -> Attention.forward -> optimized_attention(q, k, v)`

The standard Sage-disabled ComfyUI source includes the PyTorch SDPA route.
Therefore the exact integration target is clear.

The G0 execution boundary is not composable with that target:

| Gate | Result |
|---|---:|
| Actual H3 exact Attention boundary identified | pass |
| Standard PyTorch SDPA boundary identified | pass |
| G0 conditional primitive present | pass |
| G0 body is not fixed synthetic code | fail |
| G0 accepts real floating-point H3 Q/K/V | fail |
| G0 can inject/capture an H3 Attention graph | fail |
| Native FULL branch delegates existing exact H3 Attention | fail |

G0 installs the concrete `reuse_body_kernel` and `exact_body_kernel` function
pointers into the conditional graph at graph construction. Both are synthetic
`int32` kernels. The binding exports the fixed `run_sequence` method, validates
`torch.int32`, and exposes neither an Attention body registration API nor a
child-graph/stream-capture boundary.

As a result, the admitted G0 primitive cannot wrap the existing H3 PyTorch
SDPA call. Making it do so would require one of two new mechanisms:

- a new native exact Attention executor; or
- a static captured-graph design with separately owned Attention buffers.

Neither is a direct G0-to-H3 connection under the frozen A3-G1 scope. The
first changes the Attention backend, and the second introduces the prohibited
residency/complete execution-island design surface. Post-compute masking was
not considered because it cannot prove actual work omission.

Exact blocker:

`G0_CONDITIONAL_BODIES_ARE_FIXED_SYNTHETIC_KERNELS_AND_EXPOSE_NO_H3_SDPA_GRAPH_REGISTRATION_OR_CAPTURE_BOUNDARY`

## Stop decision

The structural Gate failed, so the authorized stop rule applied immediately:

- CONTROL Generations: 0 of 1;
- SELECTIVE Generations: 0 of 1;
- retries: 0;
- model loads: 0;
- CUDA executions: 0;
- low-resolution executions: 0;
- actual omitted Attention rows: not claimed;
- quality and runtime comparison: not collected;
- A3-G1-R1 automatic start: false.

Standard exact Full Compute remains unchanged and independently callable. No
threshold, correction, workflow, model, or production-default change occurred.

## Verification

- Focused A3-G1 model-free tests: 4 passed.
- Gate tested against the current G0 source and a positive composable fixture.
- Public source Gate receipt: `reports/h3/a3_g1_source_structural_gate.json`.
- `git diff --check`: passed before the evidence commit.
- Full Python suite: intentionally not repeated.
- G0 native GPU sequence: intentionally not repeated.
- Prior generation and quality evidence: intentionally not repeated.

The successful visual-review decision was not reached. No Ready or Merge
transition is authorized from this result.
