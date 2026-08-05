# M1-B0 Model-free Locality Opportunity Worklog

Date: 2026-08-05

Branch: `agent/m1-b0-model-free-locality`

Issue: [#51](https://github.com/ksse29077-byte/HIVEFRAME/issues/51)

Draft PR: [#52](https://github.com/ksse29077-byte/HIVEFRAME/pull/52)

Starting `origin/main`: `5e93745b8280159ff79ea7ef75343790c0a78e48`

Final decision: `M1_B0_LOCALITY_SURFACE_MEASURED`

## Purpose and preserved state

This bounded experiment measures real-video spatial/temporal pixel locality
and detector cost without a model or backend. PR #50's merge commit was the
starting main head and was confirmed in ancestry. The worktree was clean; no
duplicate M1-B0 Issue, branch, PR, or implementation existed.

M0, M1-P0 v1/R1/R2/R3, M1-A, and M1-A2 evidence was not rewritten. M1-A2
remains merged with decision `ORACLE_PROTOCOL_REVISE`. Guided Oracle boxes were
not loaded as truth and did not tune thresholds. HIVEFRAME 2.0 was not started.

## Counterexample-first checkpoint

Twenty negative cases were committed before the implementation as
`7288790eb4cb6404689941251bf8baed73557ec0`. They reject pixel-locality-to-skip
promotion, Guided Oracle promotion, incomplete wall scopes, scalar Python
performance baselines, missing partial tiles, undeclared threshold changes,
frozen exposed borders, hidden global pressure, omitted halo cost, unsupported
zeroes, mislabeled oversubscription, public absolute paths, missing digests,
parity continuation, model-free speed/VRAM claims, input hash drift, wrong
partial-tile denominators, cherry-picking, compensated-only reports, and
automatic backend admission.

The failed checkpoint is preserved: one invocation used a non-existent
unittest module path; a second showed that the isolated embedded Python ignores
relative `PYTHONPATH`; the corrected harness collected the tests and produced
the expected missing-implementation errors. Results were not measured until
the implementation existed.

## Implementation checkpoint

Commit `3d05409` added the fixed `m1-b0-v1` config and Schema, vectorized NumPy
gray8/RGB24 reference, deterministic Rust detector and native CLI, exact
partial-tile/halo/temporal/global-translation semantics, collision-safe phased
runner, deterministic digests, and input hash enforcement.

Commit `9d11308` added dependency-free positive/negative result invariants,
claim-counter completeness, exact/tolerant parity tests, nearest-rank cost
statistics, and output collision regression coverage. The optional external
`jsonschema` package was not installed; this is recorded as unavailable rather
than passed. Repository JSON parsing and the dependency-free receipt validator
remain mandatory.

## Official input integrity

All twelve FFV1 derivatives passed SHA-256, byte-size, 832x480, 16 FPS, FFV1,
and exact frame-count checks using the already approved FFmpeg/FFprobe 7.1.1
binaries.

| Clip | Frames | SHA-256 |
|---|---:|---|
| C01 | 205 | `f8620de20a277266daab1c4fccd2eb2616b3a29036f1e4987506911f62f23e5b` |
| C02 | 150 | `84e7f15872e831e55ca3b19fd7c62fd230d85c1c74c7ac52b878c5b79e901aa3` |
| C03 | 90 | `00b0dc0ce0198a1b9971f3561fdb1ab58bcc0e0c93d962d919c7c21a8c3e0563` |
| C04 | 121 | `24af9b252d8b079f06acfa15a549e704cc3707b36b39fd395f708d5b5a1ca941` |
| C05 | 154 | `9710fad8a499876dd1f9223a9b56fb4d38148e9bdccd2eeae7cac71e4d14d916` |
| C06 | 151 | `d633d37179c0d8b8d4bacc008c49e52cd4feca4fffee6fc4aaa49c066ef702cb` |
| C07 | 127 | `2ab83e6405cd0740fe164f7ab846685ee57938ae4ac320cdde8b277e1d3c6f9f` |
| C08 | 143 | `6a5ecab734ff79c116efb149ff93ca14610577dcad0cee4290d9cd166fdefb2d` |
| C09 | 132 | `14473ebcff24d7fc86a34aee88ae095147bb37e94a129e4d3b0cdf9f4ac356c2` |
| C10 | 100 | `7237b5950d9869040e61a43fa89b27b62e06e8bd13ba001f559d4f1518525040` |
| C11 | 139 | `a483ff7cb2f88b6d102c92015d37ebab22647ccd66db5f471bc860d8a168934d` |
| C12 | 165 | `c2415a3d5d0d70660c9dca21e01cb1915992feef3bbf1931bba582f5104d80e2` |

Decoded logical input contains 1,677 frames and 1,665 adjacent-frame pairs.
The local gray8/RGB24 preparation generated 26 files totaling 2.495 GiB at
that checkpoint. Originals and FFV1 derivatives were not modified.

FFmpeg executable SHA-256:
`b90225987bdd042cca09a1efb5e34e9848f2d1dbf5fbcd388753a44145522997`.
FFprobe executable SHA-256:
`05e8fa639450f8191635192871ae37a3ec3e4638fa12f3b7d49c6522ba16a8ed`.

## Parity

NumPy and Rust were compared for C01-C12 in gray8 and RGB24: 24/24 passed,
zero mismatches. Integer counts, tiles, partial edges, halo expansion,
temporal runs, translation records, and summary digests matched. A mismatch
would have stopped all cost benchmarks.

## Full fixed surface results

All configurations are retained in the JSON/CSV reports. The following
weighted pixel table summarizes the fixed thresholds; it is not a selected
operating point.

| Threshold | Raw gray changed | Translation-compensated changed |
|---:|---:|---:|
| 0 | 55.2251% | 54.5530% |
| 1 | 36.7986% | 35.4699% |
| 2 | 27.9859% | 26.4276% |
| 4 | 20.6741% | 19.0551% |
| 8 | 14.5320% | 13.0553% |
| 16 | 9.4529% | 8.3058% |

RGB changed ratios were 64.6116%, 35.4899%, 23.8256%, 16.2652%, and
10.5759% at thresholds 0, 2, 4, 8, and 16. Corresponding gray/RGB
disagreement was 9.3868%, 10.8146%, 4.1177%, 1.9122%, and 1.2317%.

For a transparent fixed anchor only (threshold 4, 5% tile activation), the raw
active/frozen candidate surface was:

| Tile | Halo | Active | Frozen candidate | >=90% pairs | Full pairs |
|---:|---:|---:|---:|---:|---:|
| 8 | 0 | 38.6747% | 61.3253% | 2 | 0 |
| 8 | 1 | 53.2903% | 46.7097% | 68 | 1 |
| 8 | 2 | 61.0075% | 38.9925% | 105 | 1 |
| 16 | 0 | 44.5519% | 55.4481% | 10 | 1 |
| 16 | 1 | 60.4169% | 39.5831% | 106 | 1 |
| 16 | 2 | 68.3729% | 31.6271% | 398 | 43 |
| 32 | 0 | 50.3086% | 49.6914% | 48 | 1 |
| 32 | 1 | 68.3596% | 31.6404% | 439 | 51 |
| 32 | 2 | 77.0084% | 22.9916% | 715 | 136 |
| 64 | 0 | 54.9428% | 45.0572% | 88 | 4 |
| 64 | 1 | 74.9636% | 25.0364% | 666 | 220 |
| 64 | 2 | 84.5426% | 15.4574% | 1,036 | 621 |

This table demonstrates why halo and granularity costs cannot be omitted. It
does not authorize any frozen candidate to skip model work. Translation
compensation exposed 1,946,368 border pixels (0.2927% of all pair-pixels) and
recorded 50 low-confidence pairs. NumPy reference timing for translation
estimation/apply was 2.4844/1.1010 seconds across the suite; these are
detector-internal research spans, not product wall time.

## Cost profiles and worker scaling

Hardware fingerprint: AMD Ryzen 5 9600X, 6 physical cores, 12 logical threads,
66,145,665,024 bytes installed RAM, Windows 11 Pro. Python 3.12.9, NumPy 2.4.4,
rustc/cargo 1.97.1, and approved FFmpeg/FFprobe 7.1.1 were used.

Summed per-clip p50 spans were 2.4770 seconds for decode-only, 22.5681 seconds
for resident Rust analysis, and 24.8273 seconds for external streaming
decode+pipe+analysis. These are separated scopes and must not be summed into or
presented as product end-to-end latency.

| CPU workers | Suite wall | Speedup vs 1 | Parallel efficiency | Class |
|---:|---:|---:|---:|---|
| 1 | 23.4902 s | 1.000x | 1.000 | required |
| 2 | 13.1397 s | 1.788x | 0.894 | required |
| 3 | 9.5808 s | 2.452x | 0.817 | required |
| 4 | 7.8046 s | 3.010x | 0.752 | required |
| 6 | 5.8464 s | 4.018x | 0.670 | required |
| 8 | 5.8441 s | 4.020x | 0.502 | oversubscription diagnostic |
| 12 | 4.9839 s | 4.713x | 0.393 | oversubscription diagnostic |

The 8/12-worker rows are not part of the base success result. They illustrate
declining parallel efficiency. No CPU worker is described as a GPU stream.
OS caches were not flushed. Scheduling overhead, peak process-tree RSS, and
CPU utilization were not collected by a validated sampler and are null with
reasons.

## Local and public evidence

The canonical local bundle inventory contains 220 files, 2,797,139,675 bytes,
and digest
`aee19615de605e9ff0fc3d190a0213d99a207c9622bd536e8d091354347cece0`.
It is not tracked by Git. Public reports contain logical asset IDs and relative
names only. Aggregate summary digest:
`2cc1094d40b0f85424ca67cdff32a9b0a242b45ed50934ef6d4980d46bf73e3a`.

## Claim counters and decision

Model downloads 0, model loads 0, model runs 0, CUDA runs 0, GPU runs 0,
backend integrations 0, selective-compute runs 0, VRAM measurements 0,
product-speedup results 0, safe-skip truths 0, and verified compute-relevance
Oracles 0. No personal data was transferred externally and no paid API was
called.

All Gate prerequisites passed, so the bounded result is
`M1_B0_LOCALITY_SURFACE_MEASURED`. This means the surface is measured and
reviewable. It does not close M0, prove safe skip, or admit M1-B1.

## Verification and rollback

Focused model-free tests passed before measurement. The first full Python run
then exposed two existing R3 byte-hash failures: global Git
`core.autocrlf=true` had materialized the byte-hashed R3 config with CRLF even
though the immutable Git blob and recorded SHA-256 were correct. No R3 content
or evidence hash was changed. A repository portability rule now pins that one
byte-hashed config to LF; its worktree SHA-256 again equals the recorded
`f0d7b85d...88e2`. The subsequent full Python run passed 237 tests with two
declared optional-dependency skips. Cargo format/check passed and all 14 Rust
tests passed.

Final verification also includes all JSON parsing, Markdown link/path/secret/
binary checks, protected evidence comparison, and `git diff --check`. Any
later protocol change must retain this v1 evidence and create a new revision
rather than overwrite it.

Rollback is branch deletion or PR closure before merge; protected prior
history remains reachable from `main`. The local large-artifact directory is
not a Git rollback surface and is not published.

## Next M1-B1 evidence needed

M1-B1 requires one separately approved backend selector contract with exact
compute unit, dependency closure, state/cache ownership, invalidation and
fallback semantics, supported tensor/memory measurements, full-compute parity,
and receipts for actual backend work. Pixel fractions cannot be converted to
VRAM or speed without those facts.

## Publication checkpoint

The branch was published with a normal push; no force-push, rebase, or history
rewrite occurred. Draft PR #52 is open against `main`, remains Draft, and was
verified `MERGEABLE`/`CLEAN`. It was not marked Ready and was not merged.

Commit sequence:

- counterexamples: `7288790eb4cb6404689941251bf8baed73557ec0`;
- deterministic implementation: `3d054091e27381e29a3315afb03af832142c6149`;
- receipt invariant tests: `9d113088d31659d6f9661875050aa966f316cdcd`;
- measured evidence and documents: `c8c1c9fb23f959ee07de7afa5e39ecea2a869981`.

At the initial Draft publication checkpoint, local and remote branch heads both
equaled `c8c1c9fb23f959ee07de7afa5e39ecea2a869981`. The final docs-only metadata
commit containing this paragraph is the later PR head recorded by GitHub.
