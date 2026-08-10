# A3-G1 Decision Report

Date: 2026-08-10
Issue: [#90](https://github.com/ksse29077-byte/HIVEFRAME/issues/90)
Draft PR: [#91](https://github.com/ksse29077-byte/HIVEFRAME/pull/91)
Implementation commit: `5fa85ce31cd33d6f3296e5d32719f1ba01fc04dc`

## Decision

`A3_G1_REAL_H3_EXECUTION_ISLAND_NOT_ADMITTED`

Disposition: `FALLBACK_ONLY`.

The bounded CONTROL attempt reached the first real H3 Attention block. The
exact `attention_pytorch`/PyTorch SDPA body could not be captured in the
conditional CUDA Graph execution island. CUDA reported a dependency on
uncaptured work in another stream (`cudaErrorStreamCaptureIsolation`), then
invalidated graph capture. The allocator also reported `freeAsync` on an
uncaptured allocation during capture. The owned ComfyUI process subsequently
terminated.

This is an execution-island admission failure, not a finding that the reuse
correction is inaccurate and not an H3 output-quality failure. The CONTROL
did not finish, native Full parity was not collected, and the frozen Gate
therefore prohibited SELECTIVE.

## Bounded execution receipt

| Item | Result |
|---|---:|
| CONTROL attempts / successes | 1 / 0 |
| SELECTIVE attempts / successes | 0 / 0 |
| Retry | 0 |
| Model forwards before failure | 1 |
| H3 blocks entered before failure | 1 |
| Conditional graph captures / replays | 0 / 0 |
| Native errors routed to fallback | 1 |
| Full Attention eager calls in partial attempt | 1 |
| Cache hits / misses | 0 / 0 |
| Host cache bytes | 0 |
| GPU staging peak | 172,390,400 bytes |
| Guard D2H / host guard reads | 0 / 0 |
| Explicit hot-path CPU synchronization | 0 |
| Rust calls / tensor bytes to Rust | 0 / 0 |
| Video output | not created |

The partial runner wall time was 50.609 seconds, submit-to-error-terminal was
40.989 seconds, and the sampler node ran 6.327 seconds before the error. These
are failure-path diagnostics, not performance-baseline values.

## Claims not available

Actual Q reduction, paired quality, sampler speedup, submit speedup, runner
speedup, and human quality are `not_collected`. They are not represented as
numeric zero. Speedup claim, quality promotion, and product promotion are
zero.

Standard Full Compute remains the independent product default. No threshold,
correction, cache lineage, installed H3 source, workflow, model asset, or Sage
setting was changed. The one failed CONTROL was not retried, and no automatic
A3-G1-R1 work was started.

Structured public evidence is in
[`knowledge/h3/a3_g1_real_h3_conditional_reuse.yaml`](../../knowledge/h3/a3_g1_real_h3_conditional_reuse.yaml).
Full receipts and runtime logs remain outside Git; the Knowledge record keeps
their bounded findings without disclosing private paths or prompt content.
