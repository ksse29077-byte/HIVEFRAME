# A1 — H3 Compound Eye Regional Active-Query Attention

Date: 2026-08-10

Issue: [#82](https://github.com/ksse29077-byte/HIVEFRAME/issues/82)

Draft PR: [#83](https://github.com/ksse29077-byte/HIVEFRAME/pull/83)

Branch: `accel/a1-h3-compound-eye-active-query-attention`

Base `main`: `1d339f5966c89fc66bf59d025bce3d2a1d289bf5`

Contract commit: `8b181266ce475f4f845c28c398dec6b1a0a22ed1`

Status: `A1_CONTROL_PLANE_OVERHEAD_TOO_HIGH`

## Product question and constitutional boundary

A1 asks whether the live C2 low-cost observation and a new metadata-only Rust
plan can authorize regional H3 attention-core Q work while full/global K/V,
quality-first admission, and independently available Full Compute fallback
remain intact. The final product target is still quality at least Standard
Full Compute and accepted-result end-to-end speedup of at least 2.0x. A1 was
not required to reach 2.0x by itself, and component ratios were not multiplied.

`QUALITY FAILURE OVERRIDES SPEEDUP`, observation does not equal compute
authority, and `UNCERTAIN` means Full Compute. The exact experimental
mechanism was `REGIONAL_ACTIVE_QUERY_GLOBAL_KV_ZERO_UPDATE_V1`. A0
`ATTENTION_KERNEL_SAGE` remains immutable optional evidence with product
default false and human review pending. Sage was disabled only to isolate the
HIVEFRAME workload mechanism; no A0 evidence was rejected or modified.

## Frozen contract before runtime

The first commit fixed the algorithm, thresholds, topology, halo, anchors,
cooldown, Gates, generation budget, and decision matrix before the CONTROL
result existed. It introduced `A1_ATTENTION_REGION_PLAN_ABI_V1`, a fixed-size
metadata-only Rust contract. Raw tensors, CUDA pointers, prompts, and paths do
not cross that boundary. One plan call is permitted per ready step-level
observation; per-block and per-token Rust calls are forbidden.

The H3 adapter owns packed row layout, video-token mapping, block identity,
query gather, global K/V retention, active-row output projection, output
scatter, and model-specific fail-open behavior. The generic Rust Core owns
only semantic region state, invalidation, anchors, cooldown/refresh, decisions,
reasons, and digests.

The fixed execution contract was:

- video grid 37x15x27, four exclusive 2x2 spatial regions across all latent
  time positions;
- one-patch internal boundary halo kept Full Compute;
- prediction horizon two steps;
- anchors 0, 1, 18, and 19 always Full Compute;
- no consecutive selective execution for the same region; the next eligible
  event must refresh with Full Compute;
- Active, Uncertain, boundary, and all non-video queries remain Full Compute;
- all K and V rows remain global and full;
- eligible stable queries would receive zero attention residual update, while
  the following feed-forward path remains Full Compute;
- every missing, late, malformed, conflicting, invalidated, nonfinite, source,
  layout, digest, Rust, or mapping error fails open to Full Compute.

The runtime budget was at most two Generations: one CONTROL and one conditional
SELECTIVE only if every CONTROL admission Gate passed. Retry and third
Generation budgets were zero.

## Installed H3 source and structural proof

The installed H3 model source SHA-256 remained
`882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`.
Read-only source inspection established that H3 performs one packed full QKV
projection, applies Q/K normalization and RoPE, calls an optimized attention
boundary whose basic backends support different Q and K/V sequence lengths,
then applies a separate output projection and residual update. The packed
video segment remains last, and the feed-forward path is separate.

The admitted implementation therefore preserves the full QKV projection,
selects Q only after Q/K normalization and RoPE, supplies smaller Q with
unchanged full/global K/V to the attention core, and projects only returned
active-query rows. No QKV projection reduction is claimed.

Model-free tests proved that the all-row wrapper matches the original
attention calculation, subset-Q results match the corresponding rows of the
full result, actual Q length is smaller while K/V lengths remain full, and all
non-video rows are retained. Region bounds, exclusivity, halo closure, anchors,
cooldown, late-plan fallback, row accounting, Gate arithmetic, and PyO3 ABI
roundtrip were also checked.

## Live C2 observation and Rust plan

CONTROL reused the established `x0.tensors[0]` FP32 CUDA source with shape
1x24x37x30x54 and the 4x4x3, 48-value sketch. Each of 20 observations moved
192 bytes to host, for 3,840 bytes total. Full-tensor host copies, tensor bytes
to Rust, explicit callback synchronization, per-block Rust calls, and
per-token Rust calls were zero.

The lagged C2 states were Stable/Active/Uncertain 23/4/45. All 23 Stable
predictions were validated and zero were contradicted. C2 total callback p95
was 611,164 ns. The A1 bridge issued 18 Rust plan calls, one maximum per ready
in-range observation. It produced ten `REGIONAL_ACTIVE_QUERY` candidate plans
and eight Full Compute plans; there were no malformed or late plans and no
Rust fallback.

The new Rust policy time was p50 2,000 ns and p95/max 191,200 ns. Boundary
roundtrip was p50 10,000 ns and p95/max 202,500 ns. The immutable Rust boundary
limit was 100,000 ns, so this Gate failed. An aligned diagnostic union of the
C2 callback CPU span and A1 boundary span had 18 samples and p95 2,451,200 ns,
which remained below the separate 3 ms callback limit. This derived diagnostic
does not discard the first-call boundary sample or override the failed Rust
Gate.

## CONTROL block calibration and opportunity

CONTROL executed full attention for 20 model forwards and 1,000 block calls.
The adapter collected 12 stable-region aggregate observations per block. The
fixed block Gate required at least three finite observations, mean update ratio
at most 0.020, p95 at most 0.040, and maximum at most 0.080.

No block passed. Block 10 had the lowest mean, 0.0338607638, with p95/max
0.0349549018. Since even the lowest mean exceeded 0.020, the deterministic
admitted block set was empty. Thresholds were not relaxed after observing the
result.

The Rust plan still identified ten stable-region events at non-anchor target
steps 4, 5, 6, 8, 11, 13, 14, 15, 16, and 17. However, zero admitted blocks
made planned query-row reduction 0%, below the fixed 5% floor. This is an
independent SELECTIVE blocker in addition to the Rust boundary p95 failure.

## CONTROL runtime and output

| Metric | Result |
|---|---:|
| Model/encoder load span | 5.508833 s |
| Prompt conditioning | 34.060134 s |
| Sampler/denoising | 489.823359 s |
| Video VAE decode | 62.953579 s |
| Audio VAE decode | 1.207831 s |
| Submit-to-terminal | 595.023887 s |
| Runner total | 606.862300 s |
| C4-S0 sampler reference | 488.847320 s |
| Sampler relative delta | +0.199661% |

The fixed plus/minus 5% CONTROL comparability Gate passed. Periodic one-second
resource sampling was deliberately disabled by the frozen A1 hot-path
contract. Process-tree RAM peak and NVIDIA sampled VRAM peak are therefore
`null`/`not_collected`, not zero. GPU kernel duration is likewise uncollected
because profiler, CUPTI, and Nsight were disabled.

The retained private output is H.264, 864x480, 124/124 decoded frames, 24 FPS,
with one audio stream, zero black frames, and zero corrupt frames. Its size is
263,044 bytes and SHA-256 is
`4c6ad0743092af45da743480ab7b5ab35363c745c7f7516e52e7ce9689275173`.
OOM, fatal CUDA, and retry counts were zero based on successful terminal
completion, full decode, and retained runtime-log inspection. The successful
CONTROL receipt lacks a dedicated safety object; that instrumentation
limitation is preserved rather than repaired after seeing the result.

## SELECTIVE, quality, and actual work

SELECTIVE Generation count is zero because CONTROL admission failed. Actual
smaller-Q H3 execution, actual omitted video-query rows, paired runtime,
automatic quality metrics, and visual equivalence are therefore
`not_collected` or `not_proven`. No visual-review package was produced. Actual
Q reduction, speedup claim, quality promotion, product promotion, and combined
A0+A1 execution are all zero.

This result must not be described as an attention-surface failure. Structural
subset-Q/global-KV support was admitted, the live Compound Eye to Rust plan
chain ran, CONTROL output was valid, and sampler comparability passed. The
current host-boundary implementation missed its p95 Gate, and the frozen
zero-update block-impact Gate admitted no blocks before selective authority
could be granted.

## Decision and failure scope

- `FAILED_MECHANISM`: current host-boundary implementation of
  `A1_ATTENTION_REGION_PLAN_ABI_V1`;
- `FAILED_REASON`: boundary p95 202.5 us exceeded the immutable 100 us Gate;
  independently, no block passed the immutable mean-impact Gate;
- `PRESERVED_EVIDENCE`: H3 structural source admission, full-Q and subset-Q
  equivalence, full/global K/V, deterministic region mapping, live C2
  observation, live Rust plans, valid Full Compute CONTROL, and sampler
  comparability;
- `NEXT_MECHANISM_CANDIDATE`: `GPU_RESIDENT_PLAN_MASK` under a separately
  approved task;
- exact A1 zero-update mechanism disposition: `FALLBACK_ONLY`;
- Attention cost surface: `ALIVE`;
- technical decision: `A1_CONTROL_PLANE_OVERHEAD_TOO_HIGH`.

`COARSE_REGION_ATTENTION_OUTPUT_REUSE` remains a separately declared
alternative if future work targets the independent no-admitted-block result.
Neither candidate was implemented or started here. A2 was not started.

## Validation and repository evidence

Before runtime, Python compilation and 14 focused Python tests passed. Three
focused Rust A1 tests, `cargo fmt --all -- --check`, and
`cargo check --workspace --locked` passed. The release PyO3 boundary built,
imported in the actual H3 Python environment, and completed the A1 ABI
roundtrip. The structural source test used the installed source only in
read-only mode. No full Python or Rust suite was run.

Private prompt text, model paths, output paths, media, full receipts, runtime
logs, and environment identifiers remain outside Git. Public evidence stores
only logical IDs, hashes, fixed contracts, aggregate metrics, and sanitized
results. Model downloads, external API calls, paid calls, training, A0+A1
integration, threshold sweeps, topology sweeps, and retries were zero.

Diagram impact: `updated`. The system map now distinguishes the structurally
admitted Active-Q/global-KV route from its failed CONTROL admission and keeps
the solid product path on Standard Full Compute.
