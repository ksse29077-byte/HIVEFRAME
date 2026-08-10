# A3-G1 — Real H3 Conditional Attention Reuse

Date: 2026-08-10
Issue: [#90](https://github.com/ksse29077-byte/HIVEFRAME/issues/90)
Draft PR: [#91](https://github.com/ksse29077-byte/HIVEFRAME/pull/91)
Branch: `accel/a3-g1-h3-conditional-attention-reuse`
G0 merge / G1 base: `f5d2bf8c2f80612909eef21c555d764a116f7062`
Implementation commit: `5fa85ce31cd33d6f3296e5d32719f1ba01fc04dc`
Status: `A3_G1_REAL_H3_EXECUTION_ISLAND_NOT_ADMITTED`
Disposition: `FALLBACK_ONLY`

## Product question and bounded outcome

A3-G1 asked whether the published G0 conditional omission authority could be
connected to the real MiniMax H3 exact Attention path so that stable rows use
one-interval-old actual Full Attention output plus the frozen channel-mean
correction, while unsafe blocks execute exact Full Attention in the same GPU
dispatch.

The implementation and focused admission checks passed before runtime. The one
authorized CONTROL then reached step 0, block 0, but CUDA Graph capture of the
real PyTorch SDPA Attention execution island was invalidated. CUDA identified
a dependency on uncaptured work in another stream. Graph teardown then raised
`cudaErrorStreamCaptureInvalidated`, the `cudaMallocAsync` allocator warned
about an uncaptured allocation being freed during capture, and the owned
ComfyUI process terminated.

The frozen Gate therefore stopped the task. CONTROL attempts/successes were
1/0, SELECTIVE attempts/successes were 0/0, and retry count was zero. This is
an execution-island admission failure, not a quality rejection of the reuse
formula and not proof that regional Attention reuse is impossible.

## G0 publication and immutable evidence

G0 Draft PR [#89](https://github.com/ksse29077-byte/HIVEFRAME/pull/89) was
converted to Ready and merged normally. Its merge commit is
`f5d2bf8c2f80612909eef21c555d764a116f7062`; Issue
[#88](https://github.com/ksse29077-byte/HIVEFRAME/issues/88) was completed.
Local and remote `main` matched that commit before G1 began.

The following were reused without rerun or rewrite:

- C2 Compound Eye observation evidence;
- A1 Rust semantic ABI and subset-Q/full-global-KV contract;
- A2 exact representative mapping;
- A3 cache/correction contract;
- G0 synthetic GPU conditional omission evidence.

The installed model source SHA-256 remained
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`,
and the installed Attention source SHA-256 remained
`a540a0b487eb5979c4dbc38c72926e3a38b5e41480a038a98707e2eef7e038d9`.
Installed source modification count was zero.

## Frozen integration contract

- mechanism: `REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1`;
- correction: `REGION_CHANNEL_MEAN_DELTA`;
- execution authority: `GPU_NATIVE_CONDITIONAL_KERNEL_OMISSION_V1`;
- exact backend: `attention_pytorch`, using the installed PyTorch SDPA path;
- island strategy: `PYTORCH_CUDAGRAPH_CONDITIONAL_IF_EXACT_SDPA_V1`;
- Rust directives: `FORCE_FULL` or `GPU_CHECK` only;
- final GPU decisions: `SAFE_REUSE` or `FULL_COMPUTE`;
- block-level decision: any unsafe, missing, stale, uncertain, invalid, or
  nonfinite region forces the entire block to Full Compute;
- cache source: actual Full Attention-core output only, age exactly one;
- corrected/selective outputs are never cached and approximation chaining is
  prohibited;
- host cache cap: 2 GiB; host safety reserve: 8 GiB; maximum candidates: 16;
- persistent multi-block full GPU cache: zero; one-block staging cap: 256 MiB.

No threshold, correction, candidate ranking, cache architecture, Attention
algorithm, Sage setting, model, workflow, or external asset was changed after
the implementation was frozen.

## Model-free and focused verification before CONTROL

Fifteen focused model-free tests passed with one opt-in CUDA case skipped.
The one explicitly opted-in focused CUDA test then passed. It used fake-tensor
tracing to build the fixed conditional graph without executing the traced
bodies and confirmed that SAFE executed only the reuse branch, UNSAFE executed
only the exact BF16 SDPA branch, both outputs matched their references
bit-exactly, and branch counters were isolated. Targeted syntax/import checks
and the custom-node import check passed.

These checks established the bounded primitive with representative tensor
shapes, but they did not prove capture compatibility with the live H3 stream.
The prior G0 synthetic evidence sequence itself was not rerun.

Immediately before CONTROL, preflight reported the installed source and exact
backend admitted, 12 cache candidates within the fixed capacity, no other GPU
compute process, sufficient free VRAM and host RAM, and no output collision.

## CONTROL attempt and exact failure

The CONTROL was launched once in `CONTROL_A3_G1_REAL_H3` mode. Sage remained
disabled. The path loaded the fixed H3 workflow and reached the first exact
Attention call. The primary runtime error was:

```text
cudaErrorStreamCaptureIsolation:
dependency created on uncaptured work in another stream
```

During cleanup, CUDA reported `cudaErrorStreamCaptureInvalidated`. The
`cudaMallocAsync` allocator then warned that `freeAsync` was called on an
uncaptured allocation during graph capture. The runtime terminated rather
than silently continuing with a potentially poisoned capture state.

Partial diagnostics before termination:

| Metric | Value | Scope |
|---|---:|---|
| Model forwards | 1 | failed CONTROL process |
| Block calls | 1 | step 0, block 0 |
| Native-error fallbacks | 1 | wrapper failure handling |
| Full Attention eager calls/body executions | 1 / 1 | partial attempt |
| Conditional graph captures/replays | 0 / 0 | island not established |
| Native Full parity | `not_collected` | capture failed first |
| Stable plan events/admitted blocks | 0 / 0 | calibration never ran |
| False-safe | 0 | no SAFE decision occurred |
| Cache hits/misses/invalidations | 0 / 0 / 0 | cache unused |
| Host cache bytes | 0 | cache unused |
| GPU staging peak | 172,390,400 bytes | preallocated one-block staging |
| Guard D2H / host reads | 0 / 0 | no guard result read |
| Explicit hot-path CPU sync | 0 | no conditional replay |
| Rust calls / tensor bytes | 0 / 0 | no `GPU_CHECK` reached |

Runner wall time was 50.609 seconds, submit-to-error-terminal was 40.989
seconds, and the sampler node was observed for 6.327 seconds. These are
failure-path timings only and are not CONTROL performance results.

No MP4 was created. Video integrity, output SHA-256, block admission,
false-safe admission, actual Q omission, paired quality, and speedup were not
collected. Missing metrics remain `null`/`not_collected`; they are not replaced
with zero.

## Generation, quality, runtime, and claims

| Item | Result |
|---|---:|
| CONTROL attempted / completed | 1 / 0 |
| SELECTIVE attempted / completed | 0 / 0 |
| Retry | 0 |
| Actual Q reduction | `not_collected` |
| Reused omitted rows | `not_collected` |
| Automatic quality | `not_collected`; pass `false` |
| Human quality | `not_collected` |
| Sampler speedup | `not_collected` |
| Submit speedup | `not_collected` |
| Runner speedup | `not_collected` |
| Speedup claim | 0 |
| Quality promotion | 0 |
| Product promotion | 0 |

## Fallback and product interpretation

Standard Full Compute remains independently callable, unchanged, and the
product default. The experimental selective capability remains disabled. The
wrapper attempted the declared native-error fallback once, but CUDA capture
invalidation affected the process, so this failed CONTROL did not produce a
Full Compute output. That distinction prevents overclaiming successful
fail-open completion for this attempt.

The shortest plausible next engineering question is whether the exact H3
Attention body can be isolated from cross-stream work and allocator activity
before capture, or expressed as a native preallocated execution body. That is
a separate A3-G1-R1 product question; it was not implemented, tested, or
started automatically.

## Evidence, privacy, and publication

Structured evidence is stored in
[`knowledge/h3/a3_g1_real_h3_conditional_reuse.yaml`](../../knowledge/h3/a3_g1_real_h3_conditional_reuse.yaml)
and the [decision report](../../reports/a3_g1/decision-report.md). Private
receipts and full runtime logs remain outside Git. Their bounded findings are
recorded without local paths, prompts, credentials, model/video binaries, or
full logs.

Commit 1 froze the implementation before the runtime attempt and was pushed.
Commit 2 records this immutable failed-attempt evidence, Knowledge, task state,
worklogs, and the Living System Map. Draft PR #91 remains Draft; Ready, merge,
Issue closure, additional Generation, and automatic revision counts are zero.

Diagram impact: `updated`. The map now distinguishes G0's verified synthetic
primitive from G1's real-H3 capture-isolation failure and routes the result
back to Standard Full Compute.
