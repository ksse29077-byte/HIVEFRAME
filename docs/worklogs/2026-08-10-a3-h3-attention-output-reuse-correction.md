# A3 — Regional Attention Output Reuse with Correction

Date: 2026-08-10
Issue: [#86](https://github.com/ksse29077-byte/HIVEFRAME/issues/86)
Draft PR: [#87](https://github.com/ksse29077-byte/HIVEFRAME/pull/87)
Branch: `accel/a3-h3-attention-output-reuse-correction`
Base `main`: `8d89b4dc64f3d15142ab4dc8bd32728988784bff`
Implementation-freeze commit: `ef6f70036f8d563b45edfe446fb18f8078904b20`
Status: `A3_ATTENTION_OUTPUT_REUSE_STRUCTURALLY_NOT_ADMITTED`
Disposition: `FALLBACK_ONLY`

## Executive result

A3 asked whether the H3 adapter could reuse one-interval-old, actual Full
Attention-core outputs for stable regional interiors and correct them with the
current exact representative-row channel mean, while preserving current H3
quality and reducing actual attention-core Q work.

The cache and mapping portion is structurally viable: installed H3 source,
the A1 subset-Q/full-global-KV boundary, A2 representative mapping, the
unchanged metadata-only Rust ABI, Full Attention fallback, and bounded storage
all passed. The 2 GiB host-cache budget admits 12 candidate blocks.

The execution-authority portion is not viable under the fixed A3 V1 contract.
The current PyTorch adapter cannot evaluate the current GPU representative
guard and conditionally dispatch same-block Full Attention on failure without
blocking the host or computing Full Attention unconditionally. The former
violates the no-stall contract; the latter produces no real omitted-Q work.
Quality-First therefore stopped the experiment before model load or CUDA.

This is not evidence that attention output reuse can never work. It is precise
evidence that this runtime-guard/fallback contract needs a different execution
boundary before a costly H3 run is justified.

## Constitutional and roadmap alignment

- Product-First: no approximately correct but non-shippable runtime was run.
- Quality-First: guard failure must have same-block Full Attention authority;
  quality safety was not traded for a potential speedup.
- Observation is not compute authority: Stable metadata alone never enabled
  reuse.
- Uncertain, Active, Halo, Anchor, stale, missing, late, nonfinite, or invalid
  state remains Full Compute.
- Model-replaceable Core: semantic region state, invalidation, anchors, reason,
  and fallback remain generic; H3 rows, blocks, tensors, cache, CUDA, and
  correction remain adapter-owned.
- Immutable evidence: A1 and A2 evidence was read and reused, not rewritten or
  rerun. Thresholds and the A3 decision matrix were committed before preflight.
- No next stage is automatically active.

## Frozen A3 V1 mechanism

`REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1` keeps full QKV projection,
original Q/K normalization and RoPE, full/global K/V, full output projection,
full MLP, VAE, and audio. Only current attention-core Q rows could have been
omitted.

The sole correction is `REGION_CHANNEL_MEAN_DELTA`:

```text
delta(region, channel) = mean(current_exact_representative - cached_representative)
corrected_omitted = cached_actual_full_omitted + delta(region, channel)
```

Cache source is actual Full Attention-core output only. Corrected or selective
outputs are never cached. Age is exactly one source interval. Reuse requires a
Full refresh before another reuse of the same block/region. The A1
`A1_ATTENTION_REGION_PLAN_ABI_V1` remains unchanged and receives zero tensor
bytes.

The fixed runtime guard requires representative cosine at least 0.97,
normalized L2 at most 0.25, and zero nonfinite values. Failure requires Full
Attention for that same block and region.

## Installed-source and prior-evidence verification

Read-only source inspection recorded:

- H3 model source SHA-256:
  `882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`;
- attention source SHA-256:
  `a540a0b487eb5979c4dbc38c72926e3a38b5e41480a038a98707e2eef7e038d9`;
- full packed QKV projection, original normalization/RoPE, variable-Q
  optimized attention boundary, separate full output projection, separate MLP,
  and video-last packed layout: present;
- source modification: zero.

The immutable A2 callback receipt SHA-256 matched
`fc84edd21438fbbcb474b682d5666ed901d7a8d0771a8354ffc0410d5ca5e04e`.
Its full 50-block metrics were sorted by the frozen A2 order: mean normalized
L2 ascending, mean cosine descending, p95 normalized L2 ascending, then block
index ascending. No Generation was used to recreate the ranking.

## Cache capacity and deterministic candidate set

The installed H3 attention core has 56 heads times 128 dimensions, or 7,168
channels. A1's four exclusive interior regions contain 12,025 rows. BF16
worst-case storage per candidate block is:

```text
12,025 rows * 7,168 channels * 2 bytes = 172,390,400 bytes
```

At preflight, available host memory was 50,546,864,128 bytes. After the fixed
8 GiB safety reserve, the explicit 2 GiB cap remained the limiting budget.
Twelve blocks fit:

`[0, 48, 16, 10, 4, 11, 17, 13, 49, 15, 12, 14]`

Their worst-case total is 2,068,684,800 bytes. One-block GPU staging is
172,390,400 bytes, below the 268,435,456-byte target. The minimum three-block
capacity Gate therefore passed. No host buffer was allocated because a later
structural Gate failed before runtime setup.

## Structural contradiction found before Generation

At each eligible block, SELECTIVE would first calculate exact current
representative attention rows, compare them with the cached representatives,
and use the result to decide whether omitted rows may be reconstructed. If the
guard fails, the same block/region must immediately run Full Attention.

The guard result is a CUDA scalar. In the current eager PyTorch/ComfyUI adapter:

1. converting it with `.item()`, `bool(tensor)`, or an equivalent host branch
   waits for CUDA and violates the fixed no-blocking/no-hot-sync contract;
2. launching both reduced and Full Attention and selecting with `torch.where`
   preserves output safety but performs the supposedly omitted work;
3. consuming the result in a later step is non-blocking but cannot repair the
   current block, violating fail-open semantics.

No existing H3 hook or A1 Rust ABI exposes a GPU-native conditional dispatch
that can launch the Full Attention branch only when the device guard fails.
Adding such an ABI or kernel capability was outside A3 V1 and was not invented
after observing this result.

## Structural Gate receipt

| Check | Result |
|---|---|
| Installed H3 source fixed | PASS |
| A1 smaller-Q/full-global-KV reachable | PASS |
| Attention-core output hook available | PASS |
| Original full output projection preserved | PASS |
| Full Attention fallback callable | PASS |
| A2 representative mapping reusable | PASS |
| Host cache capacity at least 3 blocks | PASS — 12 |
| GPU staging within 256 MiB | PASS |
| Generic Core H3 leakage | PASS — zero |
| Rust ABI unchanged | PASS |
| Same-block GPU guard conditional dispatch | FAIL |

The public and private structural receipts were written outside Git. Their
SHA-256 is
`b8003e212e9458d55f320a0f220313481f66c2cebf0adde7096b89b5516ee4d8`.
The A3 settings digest is
`1006c859daaa8606e8cb884594089162ab014b30b52fbe696c14c45c5e87eb67`.

## Model-free verification

Twenty-six focused tests passed in 0.015 seconds using CPU tensors only. They
cover the 21 required surfaces plus cache-budget arithmetic, immutable A2
ranking, stable settings digest, structural admission, and frozen config/
decision values. Python compile, JSON parsing, and `git diff --check` passed.
The unchanged full Python and Rust suites were intentionally not rerun.

The existing Standard product workflow remained callable and retained
`SamplerCustomAdvanced`. The A3 capability is registered on the H3 adapter as
experimental, structurally not admitted, disabled by default, with Standard
Full Compute fallback.

## Cost, quality, and claim receipt

| Item | Result |
|---|---:|
| Model load | 0 |
| CUDA execution | 0 |
| Generation | 0 |
| CONTROL | 0 |
| SELECTIVE | 0 |
| Retry | 0 |
| Sage execution | 0 |
| External API / paid call | 0 |
| Model download / training | 0 |
| Actual Q reduction | `not_collected` |
| Paired automatic quality | `not_collected` |
| Visual equivalence | `not_proven` |
| Runtime speedup | `not_collected` |
| Speedup claim | 0 |
| Quality promotion | 0 |
| Product promotion | 0 |

Unsupported runtime metrics are not recorded as zero. They were not collected
because the pre-generation structural Gate failed.

## Decision and next bounded choices

Final technical decision:

`A3_ATTENTION_OUTPUT_REUSE_STRUCTURALLY_NOT_ADMITTED`

Disposition: `FALLBACK_ONLY`. Attention surface: `ALIVE`. Full Compute remains
the product default and independent fallback.

Two better execution boundaries were identified but not implemented:

1. a GPU-native conditional attention-dispatch capability that preserves
   same-block fail-open without host synchronization;
2. a separately approved pre-admission contract that decides reuse before the
   current block and no longer claims the same runtime guard.

Both change execution authority and require a new product question,
predeclared Gate, and explicit approval. Neither is an automatic A4 or P3
start. A0 Sage remains independent optional evidence and was not combined.

## Repository and privacy

Public files contain logical IDs, hashes, aggregate capacity, contracts, and
the bounded decision only. Prompt text, local absolute paths, model/video
binaries, raw cache tensors, credentials, and full runtime logs remain outside
Git. Existing M0, M1, C-series, A0, A1, and A2 evidence was not changed.

Diagram impact: `updated`. The Living System Map now shows A3 cache capacity as
structurally verified and same-block guard dispatch as not admitted, with a
solid return to Full Compute rather than a false optimized path.
