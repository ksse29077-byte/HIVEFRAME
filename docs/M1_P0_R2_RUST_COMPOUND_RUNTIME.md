# M1-P0-R2 Python Attribution and Rust Compound Runtime

Status: pre-measurement contract; no R2 result yet

Issue: [#42](https://github.com/ksse29077-byte/HIVEFRAME/issues/42)

Base and PR #41 merge commit:
`e5bbaa751d7c449dd0c5a7ad3b7fff18bd661388`.

## Purpose and product direction

R2 attributes removable implementation overhead in the current Python
Compound I/O control plane and tests whether a coarse Rust-first boundary can
recover it. Compound Perception First remains the product direction. Mono is
the same-condition comparator and safety fallback, not the default product
decision and not an R2 Gate outcome.

This is a CPU-only, model-free M1-P0 refinement. It does not close M0 or M1,
admit or invoke H3, modify Wan, reactivate LTX, load a model, use CUDA, or
claim backend, quality, end-to-end, product, or commercial speedup.

## Immutable evidence and bounded scope

The sixteen v1/R1 config, design, worklog, success-report, decision, and failed
attempt Git blobs are fixed by SHA-256 in
`configs/m1-p0-r2.rust-compound-runtime.json`. Validation normalizes checkout
CRLF to Git's LF form before comparison with the merged `main` blob hashes, so
newline conversion cannot rewrite the evidence contract.

R2 measures only Case B:

- B/T0 (`mono_1x1`);
- B/T1 (`uniform_2x2`);
- B/T2 (`motion_focused`).

No new topology or corpus is added. A/T1, A/T2, C/T1, and C/T2 remain
analytically pruned and are not executed.

The executable profile ID and single declared change region are the exact R1
Case B contract, not the older three-region Rust-admission profile named
`high`.

## Python stage taxonomy and timing

The fixed taxonomy is input validation, Eye contract construction, Eye setup,
routing, coordinate transform, mask construction, crop/view construction,
array allocation, explicit copy, observation, overlap handling, Fusion input
conversion, Fusion, SharedVisualState construction, ComputePlan construction,
receipt construction, JSON serialization, and garbage collection.

Nested spans use `time.perf_counter_ns`. Inclusive time is span end minus span
start. Exclusive time is inclusive time minus the union of direct child spans.
The empty span tree is calibrated separately; overhead is reported and never
silently subtracted. Official Python/Rust comparison uses a separate
uninstrumented Python execution before the attributed execution for every
deterministically interleaved candidate.

The block-level identity is:

```text
C_paired_delta(T, i)
  = sum(C_exclusive_stage(T, i) - C_exclusive_stage(T0, paired_i))
  + C_unattributed(T, i)
```

Negative unattributed duration is rejected. Independent median subtraction is
forbidden. Each phase uses five warm-up and twenty measured T0/T1/T2 blocks in
one Python process with one prepared Case B NumPy object.

## Copy and allocation accounting

- NumPy receptive-field crops are views and count zero copied pixel bytes.
- Motion difference and mask arrays count as allocated and temporary bytes.
- An absent explicit-copy operation has call count zero and copied bytes zero;
  it is not an unsupported timing value disguised as zero.
- Python writes the packed input once for the coarse Rust process boundary.
- Rust reads the packed input once. Both full-buffer copies are counted.
- Rust JSON bytes and the temporary input/output files are recorded separately.
- Unsupported FFI time remains `null` with status, reason, and method.

## Coarse Rust boundary

The bounded v0 transport is one subprocess batch:

```text
one packed Case B buffer handoff
  -> one Rust process
  -> internally run complete T0/T1/T2 topology blocks
  -> return semantic results, ComputePlans, timing, counters, and receipt metadata
```

There is no per-Eye Python/Rust round trip. The Rust scope includes Eye
contract/routing/coordinate work, mask/view metadata, observation
orchestration, Fusion, SharedVisualState, ComputePlan, and receipt metadata.
Python/PyTorch retains model tensors, VAE, denoising, attention/scheduler
hooks, and model evaluation. Those model-plane components are not executed in
R2.

The process transport measures Rust core, external process call, Python input
write and output parse, Rust input read and serialization, copied bytes, and
temporary bytes. PyO3/C-ABI FFI is deliberately not introduced; its time is
`null/not_collected`. Benchmark-suite amortized boundary time is labeled as
such and is not a single-call product latency claim.

## Fixed thresholds and decisions

- Python attributed percentage: at least 80%;
- Python unattributed percentage: at most 20%;
- Rust T1 and T2 core reduction: strictly greater than 0%;
- boundary-inclusive T1 and T2 reduction: strictly greater than 0%;
- exact semantic parity and deterministic hashes required;
- total boundary copies: at most two packed input-buffer equivalents;
- collected FFI timing required for `RUST_RUNTIME_VIABLE`;
- unavailable values must remain `null`.

Exactly one decision is allowed:

- `RUST_RUNTIME_VIABLE`;
- `REFINE_RUST_BOUNDARY`;
- `OPTIMIZE_COMPOUND_RUNTIME`;
- `PAUSE_CURRENT_IMPLEMENTATION`.

`MONO_FIRST` is not an R2 decision. `PAUSE_CURRENT_IMPLEMENTATION` stops the
current implementation shape, not Compound Perception First.

The taxonomy, equation, instrumentation, boundary, copy policy, thresholds,
and decision tree are committed before measurement and may not be changed in
response to results.

## Planned evidence

R2 writes only new files under `reports/topology_pruning/r2/`:

- `predeclared-attribution-model.json`;
- `python-stage-attribution.json`;
- `rust-boundary-results.json`;
- `parity-report.json`;
- `decision-report.md`.

Existing output causes a pre-execution failure; overwrite is unsupported.

## Explicit zero-execution boundaries

- H3 API calls: 0;
- API-key use: 0;
- paid API runs: 0;
- model downloads: 0;
- model loads: 0;
- CUDA runs: 0.
