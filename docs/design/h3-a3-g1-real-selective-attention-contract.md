# A3-G1 real H3 selective Attention contract

Status: stopped at source-only structural Gate

Mechanism: `REAL_H3_GPU_CONDITIONAL_ATTENTION_OMISSION_V1`

## Product question

Can the G0 GPU conditional omission primitive skip real H3 Attention work and
reduce runtime without reducing quality?

The fixed run profile is 864x480, 20 steps, 124 frames at 24 FPS, seed 101,
`simple` scheduler, `res_multistep` sampler, guidance and prompt inherited from
the unchanged A3 profile, and Sage disabled. The budget is one CONTROL and one
SELECTIVE Generation with zero retries, but neither run is permitted before
the source-only structural Gate passes.

## Structural Gate

The installed H3 exact path is identifiable at `DiTBlock -> Attention ->
optimized_attention`. With Sage disabled, the local standard backend resolves
to ComfyUI's PyTorch SDPA path.

G0 does not expose a general conditional executor. Its CUDA graph registers
two concrete compile-time kernel function pointers, both operating on
synthetic `int32` buffers. The CPython binding exports only the fixed
`run_sequence` call and rejects non-`int32` tensors. There is no API to register
an H3 Q/K/V graph, no CUDA child-graph injection, no stream-capture boundary,
and no native FULL branch that delegates to the existing exact H3 SDPA call.

Consequently, wrapping real H3 Attention would require a separately designed
exact Attention executor or a static captured-graph storage design. Those are
new execution mechanisms, not a connection of the admitted G0 primitive, and
are outside the frozen A3-G1 scope.

The exact decision is
`A3_G1_REAL_H3_CONDITIONAL_GRAPH_BODY_NOT_CONNECTABLE`. CONTROL, SELECTIVE,
model load, CUDA execution, and Generation remain zero. Standard Full Compute
is unchanged and independently callable.
