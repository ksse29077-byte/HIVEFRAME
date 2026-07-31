# Roadmap Execution Rules

These rules govern milestone advancement in the official Compound I/O
roadmap. They are normative for planning, implementation, testing, reporting,
and review.

## 1. Sources of truth

- `ROADMAP.md` defines milestone intent and exit gates.
- `TASKS.md` records current actionable state.
- `docs/WORKLOG.md` records verified chronological evidence.
- dated files under `docs/worklogs/` record major reconciliations and decision
  events.
- receipts, reports, commits, Issues, PRs, and CI runs are evidence.

A plan is not completion evidence.

## 2. Status vocabulary

Use only:

- `planned`: no implementation;
- `in_progress`: work exists but exit evidence is incomplete;
- `implemented`: code or documents exist;
- `verified`: declared local or runtime checks passed;
- `published`: the exact remote object was verified;
- `blocked`: an external requirement prevents progress;
- `unsupported`: the backend or environment cannot provide the capability;
- `rejected`: evidence failed a predeclared gate.

Do not silently promote `implemented` to `verified` or `verified` to
`published`.

## 3. Milestone ordering

- M0 evidence remains independent of compound-eye changes.
- M0 remains `in_progress` until its own exit evidence is complete; successful
  Smoke, reproducibility, or memory-admission components do not close it.
- M1-P0 analytical preparation is a pre-gate, not M1 entry or M1 completion.
- M1 cost and safety ground truth precedes learned planning.
- M2 planning precedes dynamic activation.
- M3 observation/fusion safety precedes backend skipping.
- M4 capability and parity precede speed claims.
- M5 net gain precedes product and multi-backend expansion.

Parallel research is allowed only when it cannot be mistaken for passing a
later gate.

For M1-P0 Analytical Topology Pruning, draft equations, schemas, synthetic
cases, test scaffolding, unavailable-metric handling, and pre-rejection rules
may remain WIP. Final measurements, fixed Rust/Amdahl inputs, Gate decisions,
completion claims, and remote Analytical publication require the depended-on
Rust I/O report and its measurement semantics to be merged into `main`.
After that merge, the WIP branch must update from `origin/main` and rebase
before the final benchmark is rerun. Existing WIP must be preserved rather
than deleted or recreated.

## 4. Same-condition rule

Performance comparisons must hold constant:

- backend and checkpoint revision;
- code revision and relevant configuration;
- resolution, frame count, FPS, prompt/input, and seed policy;
- denoising steps, scheduler, guidance, and precision;
- offload, VAE, video encode, and profiler scope;
- hardware class, driver/runtime family, and eligibility.

Any difference must be declared and disqualifies the result from an official
speedup comparison unless the experiment explicitly studies that difference.

## 5. Complete-cost rule

Measure or explicitly mark unsupported:

- scout and input decode/preprocessing;
- every eye observation;
- coordinate conversion and Sensory Fusion;
- topology planning and recompilation;
- backend model work;
- boundary communication and reconciliation;
- VAE and output encode;
- audit/evaluation;
- repair, promotion, fallback, and failed attempts;
- CLI/runner and attributable setup/finalization.

No subsystem may be excluded merely because it weakens the speedup.

## 6. Measurement semantics

- CUDA event span is not GPU-kernel duration.
- Actual GPU-kernel duration requires a profiler/CUPTI path and carries
  profiler-overhead disclosure.
- Allocated, reserved, device-sampled VRAM, and host process-tree RAM remain
  separate scopes.
- Unsupported or uncollected values are `null` with unit, scope, status,
  reason, and measurement method.
- Historical receipts are immutable.

Cross-language control-plane benchmarks additionally require exact integer
parity, a fixed float tolerance, identical input/topology, and deterministic
semantic hashes. Core pipeline, interpreter/process startup, compilation, and
process/FFI handoff are separate scopes. A core-language improvement cannot be
reported as end-to-end model or product speedup.

## 7. Safety and fallback

- `uncertain` blocks skip.
- A regional eye cannot authorize writes outside its compiled scope.
- Scene cuts invalidate incompatible temporal state.
- Unsupported selectors fail or promote; they do not become fake successes.
- Every selective path retains a full-compute fallback until a later product
  policy explicitly narrows it.
- Silent failure is a terminal gate violation.

## 8. Data and license admission

Every model, checkpoint, dataset, clip, oracle label, and generated derivative
must have provenance, rights, license terms, digest, and admission status
before use. Unadmitted data cannot enter M1 or later training/evaluation
receipts.

Backend priority is not backend admission. MiniMax H3 is the primary product
target, but it remains unsupported by HIVEFRAME until its separate black-box
API gate is accepted. Any future open-weight H3 path requires independent
source, checkpoint, license, digest, and runtime admission. Do not substitute
another Hailuo model identifier, infer unreleased weights, or use unavailable
H3 costs as zero. Wan remains a frozen M0 comparator; LTX is inactive.

## 9. Git and review policy

- Never write roadmap changes directly to `main`.
- Use a dedicated branch and Draft PR.
- Preserve exact Git history with normal Git transport.
- GitHub Contents API commits are new commits and must never be described as
  preserved local Git history.
- Record repository visibility accurately.
- Public documentation must not include local absolute paths, credentials,
  tokens, session identifiers, or personal environment identifiers.
- Tags and remote SHAs are `published` only after read-back verification.

## 10. Required verification for model-free RFC changes

```bash
PYTHONPATH=python python -m compileall -q python
PYTHONPATH=python python -m unittest discover -s python/tests
cargo check --workspace --locked
git diff --check
```

All JSON Schema files must parse. Do not load the model or use CUDA for an
architecture-only change.

## 11. Gate-change policy

Changing a threshold or exit condition requires:

- the old and new value;
- evidence motivating the change;
- quality, cost, safety, and product impact;
- alternatives considered;
- rollback path;
- review in a dedicated PR.

Schedule pressure is not evidence.
