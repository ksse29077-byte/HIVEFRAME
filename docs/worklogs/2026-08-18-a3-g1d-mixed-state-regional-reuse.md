# A3-G1D - Mixed-State Regional Selective Reuse

Date: 2026-08-18
Source PR: [#91](https://github.com/ksse29077-byte/HIVEFRAME/pull/91)
Branch: `accel/a3-g1-h3-conditional-attention-reuse`
Starting head: `a342f9d2f8fb6d3ec15301929087f973560b085f`
Implementation commit: `fa792f7468996d3ad9f1366d7d344241d1c0aa12`
Decision: `A3_G1D_PREPLAN_NOT_SAFE`
Disposition: `FALLBACK_ONLY`

## Start state and bounded question

Local branch, local HEAD, remote branch HEAD, and Draft PR #91 head matched the
approved starting commit. The worktree was clean, and local/origin main remained
`f5d2bf8c2f80612909eef21c555d764a116f7062`. No issue, branch, or PR was
created. PR #92 and PR #94 were not changed.

Prior A1/A2/A3/G1C/W0 evidence was treated as immutable. G1C had observed 23
lagged Stable candidates but rejected all mixed Stable+Uncertain plans at the
block level, leaving zero executable events, zero admitted blocks, and zero
actual Q reduction. G1D asked only whether Stable interior rows could be
omitted while Active, Uncertain, halo, and non-video rows in the same block
continued through exact Q Attention.

## Mixed-state implementation

The execution authority remains
`RUST_METADATA_PREPLAN_DIRECT_SELECTIVE_V1`. The pre-Attention directives are
`FORCE_FULL` and `REGIONAL_SELECTIVE`. The G1C rule that forced an entire block
to Full whenever any Uncertain region existed was removed. A valid nonzero
Stable mask may now coexist with disjoint Active and Uncertain masks.

Malformed or missing masks, out-of-range masks, Stable/Active overlap,
Stable/Uncertain overlap, Active/Uncertain overlap, Stable/refresh overlap,
global invalidation, overlap conflict, invalid source or prediction, fallback,
anchor, stale/missing cache, or invalid cache lineage still force Full before
Attention starts.

The frozen A2 `GPUPrototypePlanCache` supplies the only subset-Q mapping. Its
kernel includes all Active rows, all Uncertain rows, the one-patch halo,
non-video rows, Stable representatives, and other Full-required rows. Only
admitted Stable interior omitted rows are absent. K and V remain global Full,
QKV projection remains Full, and the original output projection, FFN, VAE, and
native audio remain unchanged. Normal Full and Partial execution is XOR.

Correction remains `REGION_CHANNEL_MEAN_DELTA`. Current exact Stable
representatives from the existing Partial Attention call are reused for
correction and reconstruction; there is no second representative Attention
call. Cache source remains actual Full Attention-core output only, exact age
one, with no selective/corrected/partial cache source and no consecutive
approximation.

## Lean rolling cache

The rolling exact source cache refreshes only source steps 1 through 16, which
can supply non-anchor targets 2 through 17. Source steps 0, 17, 18, and 19 are
skipped. With 12 CONTROL candidates this reduces the upper bound from 240 to
192 Full refreshes. D2H remains rolling exact-source caching because the target
mask is unavailable when the source Full result is produced. H2D is
demand-driven and uploads only regions present in the target Stable mask.

The maximum GPU region staging remains 48,269,312 bytes, full-size GPU staging
remains zero, and correction temporary memory remains bounded to 32 MiB. Static
QKV, conditional graphs, runtime capture, and the same-block GPU guard remain
absent. Tensor transfer to Rust remains zero.

## Focused verification and freeze

Twenty-two focused tests passed. They independently covered Stable-only,
Stable+Uncertain, Stable+Active, no-Stable states, overlap and malformed masks,
all exact-row guarantees, Stable-only omission, exact representatives, Full/
Partial XOR, cache lineage and age, the 1..16 source schedule, stable-only H2D,
bounded staging, and separation of callback diagnostics from the E2E Gate.
AST parsing, JSON parsing, and diff checks also passed. The full suite and G0
synthetic evidence were not repeated.

Commit 1 used the required message and was pushed before runtime. No algorithm,
threshold, correction, or Gate changed after that commit.

## CONTROL

Exactly one `CONTROL_A3_G1D_MIXED_STATE_REGIONAL_REUSE` Generation completed
with retry zero. The fixed profile remained 864x480, 124 frames, 24 FPS, 20
steps, seed 101, canonical prompt, existing scheduler and guidance, denoise
1.0, native audio, and Sage disabled. Every block returned the original exact
Full Attention output.

| Metric | CONTROL result |
|---|---:|
| Stable candidates | 23 |
| Stable regional / executable events | 10 / 10 |
| Mixed Stable+Uncertain / Stable+Active events | 10 / 0 |
| Admitted blocks | 6: 0, 10, 4, 11, 13, 12 |
| False-safe | 2 |
| Planned Q reduction | 1.020475% |
| Full / Partial calls | 1,000 / 0 |
| Full / actual Q rows | 15,424,000 / 15,424,000 |
| Normal / exception double work | 0 / 0 |
| Sampler / submit / runner | 494.990247 / 594.598532 / 606.384254 s |

Mixed-state mapping, ten executable events, six admitted blocks, affected-step
count, output integrity, cache capacity, zero double work, bounded memory,
zero static/graph/guard state, and E2E comparability all passed. Block 48 and
block 49 each produced one catastrophic counterfactual false-safe. Their p95
normalized L2 values were 0.270164 and 0.319590 respectively; block 49 also had
p05 cosine 0.947653. The required total false-safe count is zero, so the Gate
selected `A3_G1D_PREPLAN_NOT_SAFE`. Planned reduction was also below the frozen
3% threshold, but false-safe has higher decision precedence.

The output integrity Gate passed: H.264, 864x480, 124/124 frames, 24 FPS,
native audio, black frames zero, corrupt frames zero, OOM zero, and no fatal
CUDA error. The output SHA-256 is
`87eb74dd23560d9ea7557b734be06b75f1bc22980759955b860d2f4abe65af6e`.

## Cache, memory, and diagnostics

| Metric | G1C | G1D CONTROL |
|---|---:|---:|
| Cache refresh count | 240 | 192 |
| Cache D2H bytes | 41,373,696,000 | 33,098,956,800 |
| Cache H2D bytes | n/a | 6,651,617,280 |
| Region uploads | n/a | 144 |
| Skipped ineligible refreshes | 0 | 48 |

Refresh and D2H both decreased by exactly 20%, or 8,274,739,200 D2H bytes.
Eligible source step count was 16. Host cache bytes were 2,068,684,800; region
staging peaked at 48,269,312 bytes; correction temporary peaked at 14,708,736
bytes; CUDA allocated/reserved peaks were 3,145,350,951 and 3,523,215,360
bytes. Full-size staging and OOM counts were zero.

The total shadow callback p95 was 347,569,456 ns and is diagnostic only. GPU
sketch/GPU-to-host p95 was 223,680 ns. Rust boundary p95 was 24,300 ns and Rust
policy p95 was 6,700 ns, both below the 100,000 ns boundary target. Admission
used E2E comparability instead: CONTROL sampler and submit regressed only
1.2566% and 0.7943% against immutable Standard, within the 5% limits.

## SELECTIVE, quality, runtime, and stop rule

The false-safe Gate prohibited SELECTIVE. SELECTIVE Generation count is zero,
retry remains zero, and actual regional work counters, paired automatic quality,
human quality, and Selective runtime were not collected. Missing values remain
`null`; CONTROL's zero omission is not presented as a Selective measurement.

Standard Full Compute remains the product default and completed the CONTROL
output successfully. The experimental capability remains disabled. No
threshold relaxation, correction change, additional Generation, G1E, or other
Attention-selective revision was started. Under the bounded G1D stop rule, the
current PyTorch/ComfyUI H3 Attention-selective line ends here; product release,
Sage, exact residency, and native exact acceleration remain separate future
priorities.

Private receipts, logs, prompts, binaries, local paths, and credentials remain
outside Git. Their bounded measurements are recorded in
[`knowledge/h3/a3_g1d_mixed_state_regional_reuse.yaml`](../../knowledge/h3/a3_g1d_mixed_state_regional_reuse.yaml).
Commit 2 records only this worklog and Knowledge evidence with the required
`docs(knowledge): record A3-G1D mixed-state evidence` message and is pushed
before the PR #91 body update.
