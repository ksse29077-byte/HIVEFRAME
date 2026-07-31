# 2026-07-31 — Rust I/O Admission Probe

Status: verified locally; publication metadata pending

## Purpose

Determine whether Compound I/O input profiling, Eye routing, coordinate
transforms, observations, Sensory Fusion, SharedVisualState, ComputePlan, and
admission receipts are viable Rust control-plane candidates.

This is not a Python rewrite, model integration, or Wan speedup experiment.

## Starting repository state

- repository: `ksse29077-byte/HIVEFRAME`;
- starting `origin/main`:
  `c7186822561a46b596817e3fc8a653f6d44e9a68`;
- branch: `agent/m1-rust-io-admission-probe`;
- Issue: pending publication;
- Draft PR: pending publication.

No duplicate Issue, PR, or remote branch existed at the start.

## Changed areas

- `crates/hive-retina-runtime/`;
- `Cargo.toml` and `Cargo.lock`;
- `python/hive_probes/rust_io_reference.py`;
- `python/hive_benchmarks/rust_io_admission.py`;
- `python/tests/test_rust_io_reference.py`;
- `reports/rust_io_admission/`;
- `docs/RUST_IO_ADMISSION_PROBE.md`;
- `ROADMAP.md`, `docs/ROADMAP_EXECUTION_RULES.md`, and `ARCHITECTURE.md`;
- `README_FIRST.md`, `TASKS.md`, and `docs/WORKLOG.md`;
- this worklog.

## Python reference change

The existing compound-eye simulation remains unchanged. A separate benchmark
reference adds:

- deterministic packed grayscale synthetic profiles;
- Mono, uniform 2×2, uniform 4×4, halo-overlap 2×2, and motion-focused routing;
- explicit local-to-global transforms and bounded write scopes;
- frame-difference observations, checksums, provenance, conservative Fusion,
  and backend-neutral plans;
- steady-clock spans, algorithmic byte counters, temporary-buffer accounting,
  process CPU time, Python thread count, and process high-water RSS where
  supported;
- null/status/reason/method for unavailable values.

## Rust implementation

The new crate implements the same semantic projection and:

- validates input shape and buffer length;
- generates deterministic synthetic packed frame buffers;
- routes all five topologies;
- observes motion and per-Eye region checksums without copying pixel buffers;
- preserves provenance through Fusion;
- maps dirty/stable/uncertain to generate/reuse/reconcile candidates;
- produces deterministic semantic SHA-256 and a separate admission report;
- records required timings and explicit unsupported metrics.

It does not contain PyO3, DLPack, async runtime, codec, GPU, or model
dependencies.

## Dependencies

Direct dependencies were necessary because the workspace had no typed JSON or
SHA-256 implementation:

| Dependency | Reason | License |
|---|---|---|
| `serde` | typed interchange structures | MIT OR Apache-2.0 |
| `serde_json` | deterministic JSON evidence | MIT OR Apache-2.0 |
| `sha2` | semantic SHA-256 | MIT OR Apache-2.0 |

`Cargo.lock` records 21 direct/transitive package additions. No large runtime
or GPU dependency was introduced.

## Benchmark environment

- Windows 11 Pro `10.0.26200`, 64-bit;
- AMD Ryzen 5 9600X, 6 cores / 12 logical processors;
- approximately 61.6 GiB visible RAM;
- Python 3.12.9, NumPy 2.4.4;
- Rust/Cargo 1.97.1, release build;
- workers executed sequentially;
- no CPU-affinity or exclusive-host reservation.

No host name, account path, token, session, or private data location is
recorded.

## Inputs and topologies

- Low: 640×384, 16 frames, one small local change;
- Medium: 1280×720, 16 frames, two change regions;
- High: 1920×1080, 8 frames, three changes including boundary-adjacent motion;
- Extended 4K: skipped because the optional profile was not needed for the
  default admission decision.

Every profile used seed `101` and all five topologies:
`mono_1x1`, `uniform_2x2`, `uniform_4x4`, `overlap_2x2`, and
`motion_focused`.

## Command and repetition contract

```powershell
cargo build -p hive-retina-runtime --release --locked
python python/hive_benchmarks/rust_io_admission.py `
  --rust-binary target/release/hive-retina-runtime.exe `
  --output-dir reports/rust_io_admission `
  --profiles low medium high `
  --topologies mono_1x1 uniform_2x2 uniform_4x4 overlap_2x2 motion_focused `
  --seed 101 --warmups 5 --repetitions 30
```

- warm-ups: 5 per case;
- measured repetitions: 30 per case;
- measured cases: 15;
- input generation and compilation excluded from core time;
- Python and Rust process startup measured separately.

## Parity

All 15 cases passed. Eye IDs/counts, receptive/write coordinates, overlap,
local-to-global transforms, motion bounds, dirty/stable/uncertain state,
provenance, Fusion sources, ComputePlan action/scope, unsupported metric
semantics, and semantic SHA-256 matched.

Integer comparison was exact. Float tolerance was fixed at `1e-9`. No
rounding was used to hide a difference.

## Measurement summary

| Profile/topology | Python p50 ms | Rust p50 ms | p50 reduction | p95 reduction |
|---|---:|---:|---:|---:|
| Low Mono | 3.950 | 3.203 | 18.91% | 43.29% |
| Low uniform 4×4 | 5.895 | 3.860 | 34.51% | 41.55% |
| Medium Mono | 15.375 | 11.832 | 23.04% | 39.55% |
| Medium uniform 2×2 | 21.341 | 14.517 | 31.97% | 32.91% |
| High Mono | 18.238 | 14.364 | 21.24% | 35.56% |
| High motion-focused | 30.587 | 18.819 | 38.47% | 59.05% |

All cases are in `benchmark-summary.json`. Dominant temporary-buffer accounting
was 87.50–93.75% lower in Rust. Explicit pixel-buffer copies were zero in both
paths, so a copied-byte reduction is not claimed.

Whole-suite external command time was 9.994 seconds for Python and 6.430
seconds for Rust. This includes process/setup scope and is not product
end-to-end latency.

## Unsupported and uncollected

- Rust peak RSS: `null/uncollected`, separate process sampler required;
- allocation count: `null/unsupported`, allocator instrumentation required;
- Rust process CPU and sampled thread count: `null/uncollected`;
- compilation time: `null/uncollected`, build completed before benchmark;
- PyO3/FFI cost: `null/uncollected`, excluded from this probe;
- DLPack/zero-copy: unimplemented and unproven;
- estimated Wan end-to-end gain: `null/uncollected`, no eligible isolated M0
  input-orchestration span exists.

Python peak RSS uses the process high-water mark and is not an isolated
per-case peak.

## Failures and resolutions

- The first locked Cargo check correctly rejected a stale lockfile after new
  direct dependencies were declared. The lockfile was generated once, and
  subsequent verification uses `--locked`.
- The initial isolated Python test command used the wrong discovery/import
  path. The test and executable wrapper now establish the repository Python
  package root explicitly.
- The first Windows peak-RSS call lacked explicit foreign-function signatures.
  The signatures were fixed and the final benchmark records Python peak RSS.
- A low-repetition parity preflight passed before the final measured suite.
  It is not used as benchmark evidence.
- Final evidence was regenerated after complete stage metrics and RSS support
  were added; only the final 5/30 result is committed.

## Admission decision

**`CONDITIONAL_ADMIT`**

Parity, determinism, error semantics, and core performance admission passed.
The result is not `ADMIT` because process/FFI cost, M0 attributable share,
backend execution, and accepted-result end-to-end impact remain unknown.

This decision permits a future bounded shared-buffer/FFI probe. It does not
authorize Rust-only migration.

## Roadmap reconciliation

The official M1 gate still requires the rights-cleared clip/oracle Topology
Cost Surface. The roadmap and execution rules now state that this Rust
admission is supporting evidence only and cannot complete M1 or prove backend
speedup.

## Unproven

- PyO3/FFI cost and shared-buffer behavior;
- DLPack or zero-copy tensors;
- backend selector execution;
- lower GPU work or Wan latency;
- quality parity;
- end-to-end product or commercial benefit.

## Validation

- `PYTHONPATH=python python -m compileall -q python`: passed;
- `PYTHONPATH=python python -m unittest discover -s python/tests`: passed,
  70 tests;
- `cargo fmt --all -- --check`: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 8
  `hive-retina-runtime` tests;
- all repository JSON schemas plus both JSON evidence reports parse: passed;
- `git diff --check`: passed.

The all-workspace rustfmt check exposed one trailing blank line in each of
seven pre-existing stub crate sources. Rustfmt removed only those blank lines;
their code and behavior are unchanged.

Model loads: 0.

CUDA runs: 0.

## Next exact work

1. Complete the rights-cleared M1 clip and oracle suite.
2. Attribute the control-plane share of the M0 comparator where possible.
3. In a separate approved PR, measure one bounded shared-buffer/PyO3 boundary.
4. Keep Python Wan/LTX, tensor, VAE, denoising, hook, evaluator, and training
   responsibilities unchanged.

## Publication

- implementation/evidence commit:
  `5a03e761f039c7b4e611f56c4ba7d7f55ce8ed5b`;
- Issue/publication-status documentation commit:
  `16f53e2be692c988bbddb4dd014ee9d208493697`;
- remote branch: `agent/m1-rust-io-admission-probe` (published with exact Git
  history);
- Issue:
  [`#35`](https://github.com/ksse29077-byte/HIVEFRAME/issues/35);
- Draft PR:
  [`#36`](https://github.com/ksse29077-byte/HIVEFRAME/pull/36);
- final PR-head commit is the commit containing this publication-link update
  and is resolved authoritatively by the branch and Draft PR refs;
- local/remote HEAD equality and the clean final worktree are verified after
  publishing that commit and reported in the task handoff.

## Downstream M1-P0 prerequisite correction

The Rust evidence is not in `main` while Draft PR #36 remains open. Therefore
Analytical Topology Pruning is classified as `M1-P0 — Analytical Topology
Pre-Gate` and remains WIP/blocked for final measurement and Gate
classification.

Before using this receipt as a fixed Amdahl input, the downstream work must
wait for this PR to merge, update from the resulting `origin/main`, rebase its
preserved WIP branch, read the merged report and measurement semantics, and
revalidate the cost model. This result closes neither M0 nor M1.
