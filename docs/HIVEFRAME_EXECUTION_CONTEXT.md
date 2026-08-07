# HIVEFRAME Execution Context

Status: non-normative retrieval index

Snapshot date: 2026-08-07

Verified source `main`: `90ee5e7b6530afd8da286040c40d167c1ade017d`

This file is the compact context that an agent must retrieve before starting
HIVEFRAME work. It does not duplicate or replace the constitution, roadmap,
task ledger, worklog, receipts, or GitHub merge evidence. If this snapshot is
stale, verify the newer evidence and update this file through normal review.

## 1. Authority and reading order

Apply these sources in this order:

1. platform, legal, security, service, and execution-environment limits;
2. the single normative Product-First Constitution in
   [`AGENTS.md`](../AGENTS.md);
3. the user's current explicit product question, scope, stop conditions, and
   any clearly bounded one-time exception;
4. the current work order and task-specific predeclared Gate;
5. [`ROADMAP.md`](../ROADMAP.md) and
   [`ROADMAP_EXECUTION_RULES.md`](ROADMAP_EXECUTION_RULES.md);
6. current actionable state in [`TASKS.md`](../TASKS.md);
7. chronological verified evidence in [`WORKLOG.md`](WORKLOG.md), dated
   worklogs, receipts, commits, Issues, PRs, and merge metadata.

A plan, proposal, branch name, Draft PR, or successful component test is not
completion evidence. Remote publication claims require read-back verification.
If a task conflicts with the constitution, stop and use the repository's
`CONSTITUTION_CONFLICT_CONFIRMATION_REQUIRED` procedure unless the user gives
a precise one-time exception or permanent amendment.

## 2. Constitution as currently understood

- Ship the smallest safe user-visible path first. Research exists to unblock
  or improve that path, not to delay it until every hypothesis is complete.
- One task answers one product question and ends with one bounded decision.
  Do not automatically begin the next R-stage, milestone, backend, benchmark,
  or architecture expansion.
- Reuse unchanged evidence. A new commit or PR does not justify rerunning the
  same model, benchmark, hash, environment audit, or full suite.
- Validate only the changed product surface plus essential smoke, core flow,
  fallback, and release-blocking safety. Full suites are reserved for common
  runtime/contract changes, release candidates, cross-module impact, failures,
  or an explicit request.
- Privacy, rights, license, credential, billing, destructive-file, corrupt
  output, fatal OOM/crash/retry, core generation, and fallback checks cannot be
  silently skipped.
- Unsupported and uncollected metrics remain `null` with status, reason, and
  method. They are never converted to numeric zero.
- Historical receipts and predeclared thresholds are immutable evidence.
  Do not relax a Gate after seeing a result or rerun until it passes.
- Every experimental selective path retains Full Compute fallback. Silent
  degradation is a terminal violation.
- Public Git content contains no private prompt, user media, credentials,
  model/video binaries, complete sensitive logs, or local absolute paths.
- No training, LoRA/DoRA/DPO, distillation, new backend, or follow-up research
  begins without a separately approved product question and rights boundary.

## 3. Product and architecture definition

HIVEFRAME is not merely an H3 wrapper and is not a project whose success is
measured by eye count. Its product objective is to make the complete
accepted-result inference path for pretrained video generation/editing lighter
and faster than the same-condition Full Compute path while preserving quality,
temporal stability, safety, rights, license, and fallback.

Compound observation is an evidence mechanism:

```text
Input + intent
  -> EyeObservation[] (1x1 Mono remains valid)
  -> Sensory Fusion
  -> SharedVisualState
  -> candidate ComputePlan
  -> BackendCapability admission + dependency/boundary closure
  -> backend adapter
  -> selective/reuse execution or Full Compute
  -> audit, repair, fallback, output, receipt
```

An Eye, pixel difference, movement box, `dirty` region, or model-free
`ComputePlan` cannot authorize backend work omission. `UNCERTAIN` blocks skip;
scene cuts and global invalidation clear incompatible reusable state.

The complete cost scope includes scout/change detection, observation, fusion,
planning, scheduling, backend work, reuse, transfer, synchronization, merge,
boundary, audit, expected repair/fallback, VAE/output, and attributable
setup/finalization. Active-area fraction is not a speedup measurement.

Core/adapter ownership remains replaceable:

- HIVEFRAME Core owns generic state, reuse/invalidity/fallback semantics,
  quality-first Gates, metadata-only Rust policies, verification, and receipts.
- The H3 adapter owns H3 node/workflow mapping, `DiTBlock`, packed tensors,
  block ranges, hooks, CUDA cache ownership, and H3-specific execution details.
- H3 tensor shapes, block counts, paths, and classes must not leak into generic
  Core contracts.

## 4. Two coordinated tracks

### Product launch track

The Product-First launch line has priority:

- P0 Local H3 vertical slice: shipped and verified once through loopback
  ComfyUI with product job states, result handling, feedback, and explicit Mock
  provenance.
- P1 one-click Local H3 launcher: not started; requires separate approval.
- P2 hardened real local product flow: not started.
- P3 selective runtime integration: only an admitted, quality-preserving,
  complete-cost mechanism may enter.
- P4 internal alpha/commercial preparation: not started.

### Selective-recompute evidence track

- M0 Wan Single-Eye/Full Compute Cost Truth remains `in_progress` and immutable.
  Smoke, reproducibility, and memory admission do not close the canonical
  same-condition baseline.
- M1-P0 is complete with `RUST_CONTROL_PLANE_ADMITTED`; it is model-free and
  not a model or product speedup.
- M1-A2 is published with `ORACLE_PROTOCOL_REVISE`; its Guided Oracle is
  observed-change evidence, not compute relevance or safe-skip truth.
- M1-B0 is published with `M1_B0_LOCALITY_SURFACE_MEASURED`; it measures a
  model-free opportunity surface only.
- M1-B1 backend capability admission and M1-B2 controlled selective recompute
  remain separate, unstarted approval stages in the formal roadmap.
- M2-M5 planner, dynamic state, backend compiler, and accepted-result net gain
  cannot be claimed before their preceding Gates.

## 5. Current H3 execution evidence on `main`

| Stage | Published decision | What it proves | What it does not prove |
|---|---|---|---|
| P0 | `P0_LOCAL_H3_COMFYUI_READY` | One real local H3 product flow completed | Quality, speed, selective compute, or default-profile generality |
| F0-SAGE | `F0_SAGE_NO_GAIN` | External Sage path was measured once | Product accelerator admission; it was dropped as a product accelerator |
| C0 | `C0_H3_PHASE_MAP_READY` | H3 execution phases and hook candidates mapped | Rust acceleration or compute omission |
| C1 | `C1_RUST_POLICY_BRIDGE_READY` | Rust metadata policy safely ran at 20 callbacks with Full Compute | Skip, reuse, partial compute, or speedup |
| C2 | `C2_COMPOUND_EYE_SHADOW_READY` | Float32 callback signal and nonblocking shadow path verified once | Execution authority or compute reduction |
| C3 | `C3_POLICY_OPPORTUNITY_TOO_LOW` | Predeclared policy opportunity was below its Gate | Runtime selective execution |
| C3-R1 | `C3_R1_LIVE_VETO_OPPORTUNITY_TOO_LOW` | 148 actual H3 block forwards were omitted and runtime decreased once | Quality preservation, admitted speedup, dynamic product policy |
| C3-R2 | `C3_R2_RESIDUAL_SIMILARITY_TOO_LOW` | Residual capture, provenance, bounded cache, diagnostics, and fallback verified once | Residual replay, paired quality/speed, or block reduction |

The current verified `main` ends with C3-R2 merge commit
`90ee5e7b6530afd8da286040c40d167c1ade017d`. In C3-R2, all six frozen
similarity candidates failed the unchanged cosine/L2 admission Gate,
calibrated targets were zero, and SELECTIVE generation count was zero. The
correct interpretation is admission failure before replay, not replay-induced
quality failure.

No current HIVEFRAME Core mechanism has a product speedup claim. C3-R1 proved
real block omission once but failed quality/opportunity/performance Gates.
C3-R2 never entered selective execution. Product promotion remains zero and
Full Compute is the safe fallback.

## 6. Backend and data policy

- MiniMax H3 is the primary local product backend currently verified once
  through the published ComfyUI path. External MiniMax API use is not implied.
- Wan 2.1 T2V 1.3B remains the frozen M0 comparator; do not reinterpret or
  casually rerun its receipts.
- LTX is inactive; historical assets remain preserved.
- Model binaries, local H3 assets, user prompts, outputs, and full runtime
  receipts remain outside Git.
- H3 output training eligibility defaults to `evaluation_only`; runtime
  Knowledge Flywheel evidence is not model-training consent.
- Rights-cleared observation clips do not become training, safe-skip, or
  compute-relevance truth without their separate admissions.

## 7. Current authorization boundary

There is no automatically active next implementation stage at this snapshot.
Each of the following requires separate explicit approval:

- P1 one-click Local H3 launcher;
- M1-B1 backend capability admission or M1-B2 formal selective probe;
- C3-R3 Compact Residual Correction / Prediction;
- any model training, new backend, cache strategy, threshold change, or
  additional generation/benchmark.

C3-R3, if approved later, is a distinct correction/prediction strategy. It may
not lower C3-R2's immutable cosine 0.99 or normalized-L2 0.20 thresholds and
must not reinterpret raw residual replay as already admitted.

## 8. Retrieval checklist for every new task

Before acting:

1. run `git status -sb`, `git rev-parse HEAD`, and verify branch/base/remote
   state relevant to the task;
2. read `AGENTS.md`, then this file, then `TASKS.md`, `docs/WORKLOG.md`, and the
   relevant work order/roadmap/knowledge record;
3. identify exactly one product question, allowed mutations, forbidden work,
   maximum executions/retries, stop conditions, and required final decision;
4. locate existing evidence and reuse it when code/input/environment are
   unchanged;
5. separate observed, verified_once, published, rejected, unsupported, and
   not_collected states;
6. freeze thresholds and execution order before measurement;
7. retain Full Compute/fail-open behavior and stop immediately at a declared
   admission failure;
8. keep private artifacts outside Git and run public path/secret/binary checks;
9. do not commit, push, Ready, merge, close an Issue, or start the next stage
   unless the current instruction authorizes that exact action;
10. finish with the bounded decision, evidence references, Git state, skipped
    checks and reasons, and the next separately approved stage.

## 9. Known documentation drift at this snapshot

Some status prose predates later verified GitHub events:

- `README_FIRST.md` still names P0-LR as the immediate action although P0 was
  subsequently shipped.
- `TASKS.md` contains pre-publication wording for some C2/C3 entries even
  though their PRs were later merged.
- older H3 policy prose describes unreleased or unadmitted artifacts, while
  the later P0 evidence verifies one local ComfyUI product path.

Do not erase those chronological statements or silently treat them as current.
Use verified merge metadata and later worklog entries for factual publication
state, while the constitution and roadmap Gates remain normative. A future
roadmap/status reconciliation should be a dedicated docs change, not an
incidental feature edit.

## 10. Refresh rule

Refresh this index only when a verified event changes product state,
architecture ownership, a milestone/Gate, backend/data admission, or the
authorization boundary. Record the source commit/PR and preserve prior
decisions. Do not create a publication-sync loop merely to record that this
file itself was merged.
