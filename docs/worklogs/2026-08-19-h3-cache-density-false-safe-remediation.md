# H3 Cache Density and False-Safe Remediation

Date: 2026-08-19
Issue: [#100](https://github.com/ksse29077-byte/HIVEFRAME/issues/100)
Branch: `codex/h3-cache-density-false-safe-remediation`
Base: `e83c40f2ffba1d237c98e3f02f4d113fd9e50e22` (Draft PR #91 G1D head)
Decision: `H3_COMPOUND_EYE_CACHE_DENSITY_REMEDIATION_FAILED`

## Scope and start state

The current checkout was the clean LTX admission branch at `2f5eb92...`.
It was not modified. This work uses a separate worktree and branch based on
the exact G1D dependency head. No duplicate remediation Issue, branch, or PR
existed. PRs #91, #92, #94, #95, #97, and #99 were not changed.

This task reused the immutable G1D CONTROL artifact and did not run H3,
CONTROL, SELECTIVE, a model load, CUDA, or Generation. The earlier
`H3_COMPOUND_EYE_REAL_ATTENTION_WORK_OMISSION_PROOF_PREFLIGHT_FAILED`
conversation result had not been stored in the repository. Its supporting
facts were already preserved in the G1D worklog and Knowledge record; this
worklog is the first repository record of the cache-density follow-up.

## Frozen evidence sufficiency

The private G1D callback receipt was found and its published digest matched the
immutable Knowledge record. It contains block-level calibration and per-step
region plans, but finalization discarded the per-observation `step` and
`region` values. Frame, eye/patch, packed-Q-row, uncertainty score,
motion/activation values, and per-case lineage fields were never serialized.
No intermediate tensors were preserved.

Consequently, the two false-safe cases cannot be replayed at the requested
row-level granularity without another model execution, which this task
forbids. Unsupported fields remain `null`; they are not inferred or zero-filled.

## False-safe cases

| Field | Block 48 | Block 49 |
|---|---:|---:|
| false-safe observations | 1 | 1 |
| predicted state | Stable / reusable candidate | Stable / reusable candidate |
| actual safety state | unsafe for reuse | unsafe for reuse |
| observation count | 12 | 12 |
| p05 corrected cosine | 0.962816 | 0.947653 |
| p95 corrected normalized L2 | 0.270164 | 0.319590 |
| catastrophic cosine threshold | 0.950 | 0.950 |
| catastrophic normalized L2 threshold | 0.250 | 0.250 |
| direct violation | normalized L2 | cosine and normalized L2 |
| frame / step / eye-patch / packed row | `null` | `null` |
| uncertainty / motion / activation | `null` | `null` |
| source kind | actual Full Attention-core output | actual Full Attention-core output |
| cache age | exactly one source interval | exactly one source interval |

The preplan classified a region as Stable without observing block-local
Attention-output drift. The immutable final false-safe Gate did not miss the
problem: it caught both observations and prohibited SELECTIVE. The minimum
conservative remediation is to deny blocks 48 and 49 and execute exact Full
Compute. Blocks 14, 15, 16, and 17 also remain Full because they failed the
unchanged block-quality admission, despite having zero catastrophic events.

After that exclusion, the frozen block set has false-safe zero and six admitted
blocks: 0, 4, 10, 11, 12, and 13. False-unsafe is `null` because no omitted-row
counterfactual was collected for Full-only Active/Uncertain states. The frozen
plan contains 23 lagged Stable candidates, 4 Active region occurrences, 45
Uncertain region occurrences, 10 regional events, 8 Full events, 12 Stable
region occurrences, and zero policy fallback events.

## Current cache byte ledger

The cache stores no Q, K, V, residual, FF output, or full block output. For
each candidate block it stores the four exclusive regional interiors of the
actual Full Attention-core output as contiguous BF16 pinned-host tensors.
Width is 7,168 and the source lifetime is exactly one denoising interval.

| Payload | Shape per block | Bytes/block | 12 blocks | 18 blocks | Required | Removal / lower precision |
|---|---:|---:|---:|---:|---|---|
| Q | none | 0 | 0 | 0 | no | already absent |
| K | none | 0 | 0 | 0 | no | already absent |
| V | none | 0 | 0 | 0 | no | already absent |
| region 0 Attention output | `[3367,7168]` BF16 | 48,269,312 | 579,231,744 | 868,847,616 | yes when region 0 admitted | cannot remove; lower precision adds reconstruction error |
| region 1 Attention output | `[3108,7168]` BF16 | 44,556,288 | 534,675,456 | 802,013,184 | yes when region 1 admitted | cannot remove; same precision risk |
| region 2 Attention output | `[2886,7168]` BF16 | 41,373,696 | 496,484,352 | 744,726,528 | yes when region 2 admitted | cannot remove; same precision risk |
| region 3 Attention output | `[2664,7168]` BF16 | 38,191,104 | 458,293,248 | 687,439,872 | no opportunity in this frozen trace | removable only for this frozen admission; future miss is Full |
| residual / FF output | none | 0 | 0 | 0 | no | already absent |
| tensor payload total | `[12025,7168]` BF16 | 172,390,400 | 2,068,684,800 | 3,103,027,200 | only admitted regions | region-sparse removal is exact; FP8 is unverified |

The 3,103,027,200-byte value is actual pinned-host tensor payload. It is not
VRAM, CUDA reserved memory, alignment, allocator overhead, Python metadata, or
CUDA-event overhead. Those overheads were not measured and remain `null`.
The shared A2 GPU mask/index plan is 9,061,696 bytes and is not duplicated per
block. G1D already separates metadata from payload and uses pinned host storage
with demand-driven stable-region H2D staging.

## Candidate comparison

| Candidate | Frozen-shape result | 2 GiB capacity / opportunity | Risk and decision |
|---|---|---|---|
| A. Required rows only | Current per-region payload already contains exactly cached representatives plus omitted rows | Removing never-used region 3 gives 134,199,296 B/block; 16 blocks fit, only 2.7213% even if all are safe | useful but insufficient alone |
| B. Stable-row sparse payload | Store only admitted `(block, region)` BF16 payloads | 44 region-0 items fit; 29 safe region-0 items would use 1,399,810,048 B and yield 3.0679% | selected representation, but only 6 safe blocks are evidenced |
| C. FP8 cache | 86,195,200 B/full block; 24 blocks fit | 18 safe blocks would be 1,551,513,600 B and 3.0614% | rejected: new numerical error and quality evidence unavailable |
| D. Effect/byte admission | Rank exact BF16 region items by omitted Q rows per byte | selects region 0, then 1, then 2 for frozen geometry | selected |
| E. Q-reduction knapsack | Same item surface as D for this fixed geometry | cannot create safe candidates absent evidence | folded into deterministic admission; no extra mechanism |
| F. Rolling lifetime | G1D already uses exact age one | future target mask is unavailable at source time | retained; no further safe reduction |
| G. Remove duplicate K/V/residual | These payloads are already absent | saves 0 B | no change |
| H. Split metadata/payload | Already split; tensor metadata is not duplicated per block | allocator/object overhead is unmeasured | retained |
| I. Tiered cache | Pinned host plus demand H2D already exists | avoids persistent full GPU cache | retained; no new tier |

Execution and safety comparison:

| Candidate | Extra GPU work | CPU/GPU traffic and selection overhead | Lineage / exact fallback | Numerical and quality risk | Difficulty / G1D compatibility |
|---|---|---|---|---|---|
| A | existing index-select/copy only | selected-row D2H/H2D; fixed row lookup | unchanged age-one lineage; miss is Full | none in BF16 | medium / compatible |
| B | existing regional copy only | region-only D2H/H2D; deterministic item ordering | lineage key adds region; miss and unadmitted region are Full | none in BF16; safety still needs evidence | medium / compatible |
| C | FP8 quantize/dequantize kernels | about half payload traffic; codec overhead | lineage must include codec/dtype; fallback remains possible | high and unmeasured | high / rejected |
| D | none beyond B | exact Fraction ordering over bounded metadata | unchanged; rejected items are Full | none | low / compatible and selected |
| E | bounded admission search | metadata-only planning | unchanged; rejected items are Full | none | medium / redundant with D on frozen geometry |
| F | none new | existing rolling D2H and demand H2D | exact age one; stale is Full | none | already implemented |
| G | none | saves no traffic because payloads are absent | unchanged | none | no-op |
| H | none | metadata is already separate; object overhead unmeasured | unchanged | none | already implemented |
| I | existing H2D copy | pinned-host payload and one-region staging | unchanged; transfer/error is Full | none | already implemented |

The minimum mechanism is
`REGION_SPARSE_BF16_EFFECT_PER_BYTE_ADMISSION`: immutable BF16 regional
payloads, deterministic benefit/byte ordering, exact 2 GiB cap, exact-age-one
lineage, and Full Compute on every invalid state. It avoids new precision and
correction risk and is budget-injectable for later hardware profiles.

## Model-free implementation and replay

`a3_g1_cache_density.py` implements the byte ledger, region candidates,
deterministic admission and eviction, interrupted cleanup, lineage/age/region
validation, shape/dtype/device validation, nonfinite rejection, and fail-open
access decision. It does not enable or connect a runtime SELECTIVE path.

The frozen replay admits only regions 0, 1, and 2 for the six previously
admitted blocks. It uses 805,195,776 bytes and plans 157,398 omitted Q rows:

```text
157,398 / 15,424,000 = 1.0204745850622407%
```

The remaining 1.34 GiB cannot be filled with additional safe items because
the frozen CONTROL contains no G1D correction evidence for the other 38 H3
blocks, while the other six observed candidates failed admission. Cache
compression cannot manufacture safety evidence.

## Verification

The new model-free tests and the existing G1D focused tests passed together:

```text
Ran 36 tests in 0.011s
OK
```

Coverage includes byte ledger, hard cap, admission, eviction, age-one lineage,
block/region mismatch, miss, scene cut, cache error, partial/full XOR, exact
fallback, shape/dtype/device, row partition/reconstruction contract, NaN/Inf,
deterministic ordering, false-safe exclusion, opportunity calculation, and
interrupted cleanup. The first bundled Python attempt passed the new tests but
could not import the existing Torch-dependent test; the installed ComfyUI
Python environment then ran both suites successfully. Full Python/Rust suites
were not repeated because no common runtime was connected or changed.
Targeted `py_compile` could not create `__pycache__` in the separate worktree
because of its filesystem ACL; a write-free AST parse of both changed Python
files passed instead.

## Gate and final decision

| Gate | Result |
|---|---|
| `FALSE_SAFE_COUNT=0` | PASS after conservative block exclusion |
| `CACHE_HARD_CAP_BYTES<=2GiB` | PASS: 805,195,776 B |
| `PLANNED_Q_REDUCTION>=3%` | FAIL: 1.020475% |
| `REQUIRED_CACHE_BYTES<=2GiB` | PASS for the selected safe set; 3% safe set not evidenced |
| `PARTIAL_FULL_XOR` | PASS |
| `EXACT_FALLBACK` | PASS |
| `LINEAGE_VALIDATION` | PASS |
| `BYTE_LEDGER` | PASS |
| `FROZEN_CONTROL_REPLAY` | FAIL: row-level cases absent and opportunity below 3% |
| `EXISTING_TESTS` | PASS: related 36-test suite |

Final decision:

`H3_COMPOUND_EYE_CACHE_DENSITY_REMEDIATION_FAILED`

## Hardware-profile compatibility and remaining risk

The payload format and admission algorithm accept a budget rather than an RTX
3060 identifier. The current hard maximum remains 2 GiB for the 12 GB Balanced
profile. A separately approved 24 GB Quality profile could inject a different
budget without changing payload or lineage semantics, but no such profile was
implemented here.

The blocker is evidence density, not byte density alone. A future real-GPU
proof cannot be requested from this result. A separately approved evidence
collection would need to preserve per-observation block, target/source step,
region, packed rows, state scores, and lineage while evaluating enough blocks
to establish at least 29 safe region-0 items or another verified combination.
No such Generation is authorized by this task.

Diagram impact: none. The runtime and product flow remain unchanged.
