# A2 — GPU-Resident Regional Query Prototype Attention

Date: 2026-08-10

Issue: [#84](https://github.com/ksse29077-byte/HIVEFRAME/issues/84)

Draft PR: [#85](https://github.com/ksse29077-byte/HIVEFRAME/pull/85)

Branch: `accel/a2-h3-gpu-regional-query-prototype`

Base `main`: `6c9b53f398df7c7c4ecbd38e2c1d5812d34b5f1b`

Contract commit: `3e2847aea97da522555d20d43b497f5988372d1a`

Status: `A2_QUERY_PROTOTYPE_OPPORTUNITY_TOO_LOW`

Disposition: `FALLBACK_ONLY`

## Product question and constitutional boundary

A2 asks whether the A1 subset-Q/full-global-KV execution boundary and live C2
Compound Eye region signal can reduce actual H3 attention-core query work by
evaluating exact representative Q rows in stable interiors and reconstructing
the omitted outputs. Standard Full Compute quality, safety, and fallback remain
mandatory. The cumulative product goal remains accepted-result end-to-end
speedup of at least 2.0x at quality at least Standard, but A2 is one bounded
component experiment and is not required to meet that target alone.

`QUALITY FAILURE OVERRIDES SPEEDUP`, observation is not compute authority, and
Uncertain always means Full Compute. A0 Sage remains immutable optional
evidence with human review pending. Sage was disabled for A2, A0 and A2 were
not combined, and component ratios were not multiplied.

The historical A1 mechanism
`REGIONAL_ACTIVE_QUERY_GLOBAL_KV_ZERO_UPDATE_V1` remains unchanged. A2 did not
retry or rewrite A1's zero-update result. Instead, the separate fixed mechanism
`GPU_RESIDENT_REGIONAL_QUERY_PROTOTYPE_ATTENTION_V1` retains real attention
information from exact original query rows and deterministically reconstructs
only omitted stable-interior attention-core outputs.

## Frozen contract before runtime

Commit `3e2847a...` fixed the algorithm, row topology, reconstruction, Rust
boundary, thresholds, quality Gate, runtime Gate, decision matrix, two-
Generation maximum, and retry zero before CONTROL ran. None was changed after
the result.

The fixed mechanism is:

- exact original Q rows after Q normalization and RoPE; no average, synthetic,
  learned, or clustered prototype;
- spatial stride exactly 2x2 and temporal stride one; no sweep and no temporal
  compression;
- bilinear reconstruction within the same latent time and same stable semantic
  region;
- Active, Uncertain, one-patch halo, non-video, anchor, refresh, invalid, late,
  and unavailable rows use Full Query;
- anchors 0, 1, 18, and 19 and the A1 no-consecutive-region cooldown remain;
- QKV projection remains full, K/V remain full/global, output projection runs
  for all rows, and MLP/VAE/audio remain Full Compute;
- only attention-core Q rows are eligible for reduction;
- any source, layout, mapping, Rust, non-finite, runtime, or reconstruction
  error fails open to the installed Full Compute block.

CONTROL executes actual Full Attention. Its prototype reconstruction is a
GPU-first counterfactual diagnostic computed from the already available full
attention-core result and never changes model output. SELECTIVE can execute
only if every structural, timing, opportunity, and integrity Gate passes.

## Core and H3 Adapter ownership

The existing `A1_ATTENTION_REGION_PLAN_ABI_V1` was reused without changes. The
generic Rust Core still owns only semantic region state, invalidation, anchors,
cooldown, fail-open decisions, reasons, and digests. It receives zero tensor
bytes and makes at most one call per ready step-level observation. Per-block and
per-token Rust calls remain forbidden.

The H3 Adapter owns the installed packed layout, row indices, device tensors,
representative gather, full/global K/V attention, bilinear reconstruction,
full output projection, block identity, and model-specific fallback. No H3
token count, block class, CUDA pointer, tensor, prompt, or local path moved into
the generic Rust contract. An ABI change was not needed.

## Row layout, prototype mapping, and temporal isolation

The fixed video grid is 37x15x27, or 14,985 video rows. The four exclusive
regional interiors preserve a one-patch internal seam halo. Their interior,
representative, and omitted row counts are:

| Region | Interior | Exact representatives | Omitted | Interior compression |
|---:|---:|---:|---:|---:|
| 0 | 3,367 | 1,036 | 2,331 | 69.2308% |
| 1 | 3,108 | 1,036 | 2,072 | 66.6667% |
| 2 | 2,886 | 1,036 | 1,850 | 64.1026% |
| 3 | 2,664 | 1,036 | 1,628 | 61.1111% |

For the all-stable mask, 4,144 representative rows retain 7,104 total video Q
rows and omit 7,881 stable-interior rows. This is a structural mapping ceiling,
not an admitted execution plan or performance claim. Every interpolation
neighbor belongs to the same region and the same latent time as its omitted
row; no temporal or cross-region borrowing occurs.

All 16 possible four-region semantic masks have deterministic CPU metadata.
Their GPU index and weight tensors are materialized once for the observed
device and packed layout, then reused. The CONTROL run materialized 16 masks
using 9,061,696 persistent bytes. Dynamic per-block plan allocation, per-block
CPU tensor construction, explicit hot-path CUDA synchronization, full-tensor
host transfer, and tensor-to-Rust transfer counts were zero.

## Source inspection and model-free verification

The installed H3 model source SHA-256 remained
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`;
the attention source SHA-256 remained
`a540a0b487eb5979c4dbc38c72926e3a38b5e41480a038a98707e2eef7e038d9`.
Read-only inspection confirmed full packed QKV projection, Q/K normalization
and RoPE, an optimized attention boundary accepting independent Q and K/V
lengths, separate output projection, separate residual/MLP, and unchanged
video-last packed layout. Installed source was not modified.

Sixteen focused Python tests passed in the H3 Python environment. They covered
all 16 masks, deterministic representative selection, stable-only omission,
halo/non-video/full-region preservation, same-time/same-region interpolation,
unit-sum bilinear weights, known-field reconstruction, exact representative
Q equality against full attention rows, full-row wrapper parity, GPU-plan
reuse, frozen config/Gates, workflow isolation, source admission, and hot-path
prohibitions. The existing PyO3 A1 roundtrip passed. Three focused Rust A1
tests passed and confirmed deterministic metadata-only decisions, uncertainty,
anchor, cooldown, conflict, late-plan, and malformed-plan Full Compute safety.
`cargo fmt --all -- --check`, `cargo check --workspace --locked`, Python
compile, and `git diff --check` passed. The full Python/Rust suites were not
run under the bounded verification budget.

## CONTROL execution and observation chain

One fresh owned ComfyUI process ran the fixed Standard profile: seed 101,
864x480, 124 frames, 24 FPS, 20 steps, Simple scheduler, `res_multistep`,
denoise 1.0, native audio, H.264, and Sage disabled. Retry was zero.

The C2 observer produced 20 structurally admitted FP32 CUDA observations from
the established 48-value sketch. It transferred 3,840 aggregate sketch bytes
to host and zero full-tensor bytes. Lagged Stable/Active/Uncertain candidate
counts were 23/4/45; all 23 Stable candidates were validated and zero were
contradicted.

The unchanged Rust bridge made 18 metadata calls and zero fallbacks. Rust
policy p50/p95 were 2.2/4.8 microseconds; boundary p50/p95 were 10.4/17.0
microseconds. The A1 100-microsecond Rust threshold was intentionally not an
A2 Gate and is record-only here.

The inclusive Compound Eye callback span, which already contains the Rust
child span and therefore must not be summed with it again, had p50 608,800 ns,
p95 59,829,032 ns, and maximum 484,952,763 ns. Its fixed A2 p95 maximum was
3,000,000 ns, so this control-plane Gate failed. No sample was discarded or
reclassified after the result.

## Counterfactual prototype fidelity and block admission

CONTROL executed 20 model forwards and 1,000 Full Attention block calls. It
collected 600 finite block-region reconstruction observations, exactly 12 per
block, with zero non-finite observations. The frozen block Gate required at
least three observations, mean/p05 cosine at least 0.980/0.950, mean/p95
normalized L2 at most 0.120/0.250, mean energy ratio in 0.85..1.15, and zero
non-finite results.

No block passed. Block 0 was the closest candidate:

| Metric | Block 0 | Frozen Gate |
|---|---:|---:|
| Mean cosine | 0.9805388550 | >= 0.980 |
| p05 cosine | 0.9681153297 | >= 0.950 |
| Mean normalized L2 | 0.1936711843 | <= 0.120 |
| p95 normalized L2 | 0.2508505285 | <= 0.250 |
| Mean normalized MAE | 0.1357106101 | diagnostic |
| Mean energy ratio | 0.9869841337 | 0.85..1.15 |
| Non-finite | 0 | 0 |

Its mean normalized L2 exceeded the immutable 0.120 maximum and its p95 L2
also narrowly exceeded 0.250. The deterministic admitted set was empty.
Thresholds, stride, halo, ranking, and reconstruction were not relaxed.

Ten stable regional plan events occurred at non-anchor steps 4, 5, 6, 8, 11,
13, 14, 15, 16, and 17. Those counts satisfied the event and affected-step
floors, but zero admitted blocks made planned query reduction 0%, below the
fixed 5% floor. The opportunity Gate therefore failed independently of the
callback p95 Gate.

## CONTROL runtime, work accounting, and output

| Span | Result |
|---|---:|
| Runtime startup | 10.592784 s |
| Model/encoder loader nodes | 1.014902 s |
| Prompt conditioning | 33.826399 s |
| Sampler/denoising | 493.593208 s |
| Video VAE decode | 62.775359 s |
| Audio VAE decode | 1.363066 s |
| Video encode | 1.547169 s |
| Result collection | 0.587163 s |
| Submit-to-terminal | 594.124892 s |
| Runner total | 605.969617 s |
| C4-S0 sampler reference | 488.847320 s |
| Sampler relative delta | +0.970832% |

The sampler remained within the fixed +5% comparability limit. This does not
override the failed fidelity, opportunity, and callback Gates.

Because CONTROL is Full Attention, its full and actual kernel Q-row counts were
both 15,424,000; representative and omitted execution rows were zero. Full and
actual K/V counts were both 30,848,000. QKV projection and output projection
both processed all 15,424,000 rows. Thus actual query reduction, QKV reduction,
K/V reduction, and output-projection reduction were all zero in the only
eligible run.

The retained output is H.264, 864x480, 124/124 decoded frames, 24 FPS, with one
audio stream, zero black frames, and zero corrupt frames. Its size is 263,060
bytes and SHA-256 is
`4ff07d975d51b21c324103da8f1cf966dd7966b703dbe23f4a545fd59c164fac`.
No OOM, fatal CUDA error, traceback, or runtime `ERROR` signature was observed.

Periodic resource polling was excluded from the frozen hot path, so peak VRAM
and process-tree RAM remain `null`/`not_collected`, not zero. GPU kernel-duration
sum is also uncollected because profiler, CUPTI, and Nsight were disabled.

## SELECTIVE, quality, and final decision

SELECTIVE Generation count is zero. The runner stopped after CONTROL exactly
as predeclared because no block and no planned reduction were admitted; the
callback p95 Gate also failed. It did not retry, change a threshold, change
stride, or run a third Generation.

Actual representative-Q execution, actual omitted rows, paired automatic
quality, visual equivalence, paired runtime, and human visual review are
therefore `not_collected` or `not_proven`. The output is a valid CONTROL result,
not evidence that prototype execution preserved quality.

The bounded technical decision is
`A2_QUERY_PROTOTYPE_OPPORTUNITY_TOO_LOW`; the exact mechanism disposition is
`FALLBACK_ONLY`. The precise failure scope is the fixed 2x2 exact-query plus
bilinear reconstruction strategy under this profile and its current inclusive
callback implementation. This does not prove that the H3 global-attention cost
surface, every query reduction mechanism, or corrected attention-output reuse
is impossible.

The next candidate recorded by the frozen decision matrix is
`REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1`. It was not implemented or
started. Full Compute remains the product default. A0 integration, component
speedup multiplication, final 2x verification, speedup claim, quality
promotion, and product promotion are all zero.

## Evidence, privacy, and repository state

Full receipts, prompt, local paths, generated video, runtime log, and ComfyUI
artifacts remain outside Git. Public evidence stores only the contract, logical
IDs, hashes, aggregate measurements, and sanitized conclusions. Key retained
digests are:

- experiment receipt:
  `1e035827c54f155be8311f75e00667bc00c88b5d09b9c71f6822011bc267ddf3`;
- callback receipt:
  `fc84edd21438fbbcb474b682d5666ed901d7a8d0771a8354ffc0410d5ca5e04e`;
- CONTROL receipt:
  `ac9206789c7543696f1b52c310f4ceb1e4f846a2f7bcecade6eecfbcceb9175a`;
- public CONTROL summary:
  `683a0d19d85b7a97502f3a8531fea4d86dfd0840a5e0dc003673cf4038be8ce0`;
- WebSocket events:
  `ec9c7eb78993298b1ef02ab835dc5efbf8ea1dae4138faf76997c1e8d4e8c0f0`;
- runtime log:
  `1fea69845352829b6e09ee14befed5c2f981b008a389c41bea42016b6cb8547b`.

Model download, external API call, paid call, model training, Sage run,
SELECTIVE run, retry, and third Generation counts were zero. A1, A0, C2,
C4-S0, M0, and earlier M1 evidence were not modified.

Diagram impact: `updated`. The system map now shows A2 as a distinct exact-query
prototype branch after A1 structural evidence, its stopped CONTROL admission,
and Full Compute fallback. The candidate next mechanism is shown only as a
dashed, separately approved path.

## Commits and publication state

- Contract/implementation commit:
  `3e2847aea97da522555d20d43b497f5988372d1a`;
- Evidence commit: recorded after this worklog is committed;
- Issue #84 remains open;
- PR #85 remains Draft and open;
- Ready transition, merge, Issue close, and automatic A3 start: zero.
