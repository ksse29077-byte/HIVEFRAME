# 2026-07-31 — M1-P0 Analytical Topology Pruning

Status: published on remote branch; Draft PR review pending

## Repository and dependency state

- base `main`: `a71eea742f5a804c30f6f095c1a256ee2d2561a6`;
- PR #36: merged at `2026-07-31T08:45:53Z`;
- PR #36 merge commit:
  `a71eea742f5a804c30f6f095c1a256ee2d2561a6`;
- Issue #35: closed through PR #36;
- merged Rust decision: `CONDITIONAL_ADMIT`;
- branch: `agent/m1-p0-analytical-topology-pruning`;
- Issue:
  [#37](https://github.com/ksse29077-byte/HIVEFRAME/issues/37);
- Draft PR:
  [#38](https://github.com/ksse29077-byte/HIVEFRAME/pull/38).

## Existing WIP search

Local and remote branches, registered worktrees, stash, reflog, repository
files, and known workspaces were searched. Only the precondition hold worklog
existed. There was no Analytical implementation to preserve or rebase, so a
new branch was created from post-PR36 `main`.

## Scope

- T0 Mono Eye;
- T1 Global + Fixed 2×2;
- T2 Global + Motion-focused Eye;
- Case A 640×384×16 local change;
- Case B 1920×1080×8 local change;
- Case C 1280×720×16 global change.

No 4×4, object-centered, temporal, learned planner, model hook, model load, or
CUDA work was added.

## Backend target policy correction

Decision date: 2026-07-31.

- MiniMax H3 is the highest-priority product backend target.
- The official MiniMax V2 video API documentation reviewed on this date names
  `MiniMax-H3` and `POST /v2/video_generation`.
- This documentation fact does not admit the API into HIVEFRAME. Runtime,
  price/billing, H3-specific data handling, commercial fitness, provenance,
  and receipts remain pending Issue #39.
- The official MiniMax GitHub and Hugging Face organizations did not provide a
  jointly verified H3 source, checkpoint, license, and digest for admission at
  review time. Future open weights therefore remain blocked.
- Wan remains the frozen legacy comparator and all M0 evidence is preserved.
- LTX is inactive; no historical code or Git history was removed.
- No standalone backend capability matrix existed in the repository; Issue
  #39 plans the black-box/white-box matrix after evidence is admitted.

Official sources:

- [MiniMax H3 video guide](https://platform.minimax.io/docs/guides/video-generation)
- [MiniMax V2 create contract](https://platform.minimax.io/docs/api-reference/video-generation-v2-create)
- [MiniMax V2 OpenAPI](https://platform.minimax.io/docs/api-reference/video/generation/api/v2-video-generation.json)
- [MiniMax pay-as-you-go pricing](https://platform.minimax.io/docs/guides/pricing-paygo)
- [MiniMax privacy policy](https://platform.minimax.io/docs/guides/privacy-policy)
- [MiniMax terms of service](https://platform.minimax.io/docs/guides/terms-of-service)
- [MiniMax official GitHub](https://github.com/MiniMax-AI) and
  [official Hugging Face organization](https://huggingface.co/MiniMaxAI)

Secondary press context was separated from admission evidence. A
[Reuters report republished by MarketScreener](https://www.marketscreener.com/news/china-s-minimax-plans-to-launch-giant-2-7-trillion-parameter-model-ce7f5ed9d98ffe27)
reported the planned H3 launch earlier in July; it was not used to establish
an API identifier, license, checkpoint, capability, or M1-P0 numeric input.

H3 API calls: 0. H3 model loads: 0. Paid API runs: 0. CUDA runs added by this
policy correction: 0.

## Cost and Amdahl model

```text
C_total(T) =
  C_scout + C_route(T) + C_observe(T) + C_overlap(T)
  + C_fusion(T) + C_plan(T) + C_generation(T)
  + C_audit(T) + E[C_recovery | T]

S_required(T) =
  C_input_and_orchestration(T)
  - C_input_and_orchestration(Mono)
```

Merged Rust Probe p50 and stage means are the only fixed orchestration inputs.
The local Rust control-plane factor is 1.2331–1.6253×. M0 has no eligible
input/orchestration fraction, so `f_input` and the end-to-end Amdahl upper
bound are `null/unavailable`. Generation, audit, recovery, isolated scout, and
isolated overlap cost are also unavailable where applicable.

## Analytical pruning

Nine case/topology combinations were evaluated analytically.

- Case A T1/T2: pruned by the declared small-input threshold.
- Case C T1/T2: pruned because motion and generation scope are global while
  observation is 2× or 3× Mono.
- Case A/C T0 and Case B T0/T1/T2: retained.

Pruned records preserve reason, geometry, triggered rules, and required
savings.

## Final measurement

- retained combinations: 5;
- warm-ups: 5 per combination;
- repetitions: 20 per combination;
- runner wall: 2.185 seconds;
- deterministic semantic hashes: stable in every measured combination;
- dirty recall: 1.0 in every measured combination;
- maximum false-stable: 0.0;
- copied bytes: 0;
- overlap timing: `null/unavailable`.

| Case | Topology | Predicted ms | Actual p50 ms | p95 ms | Error |
|---|---|---:|---:|---:|---:|
| A | T0 | 3.950 | 2.788 | 2.936 | 41.66% |
| B | T0 | 18.238 | 14.232 | 15.506 | 28.15% |
| B | T1 | 26.006 | 19.848 | 20.627 | 31.03% |
| B | T2 | 30.587 | 22.596 | 23.749 | 35.36% |
| C | T0 | 15.375 | 13.890 | 14.638 | 10.69% |

Case B ranking matched: predicted and measured were both `T0 < T1 < T2`.
Measured Case B additional model-free cost was 5.616 ms for T1 and 8.365 ms
for T2. Rust-calibrated required savings was 3.249 ms and 4.455 ms
respectively.

## Failure and correction

The first analytical draft assumed a dirty global observation created a
full-canvas generate unit for local T1/T2 cases. A new integration test
disproved that assumption: the compiler emits bounded quadrant or motion-focus
generation scopes. The invalid first result was not committed.

The model was corrected to compute generation scopes explicitly. Case B T1/T2
then survived pruning. A missing per-execution Eye count and measured
break-even field were also added before the final receipt was generated.
Superseded development outputs were moved outside the repository and are not
evidence.

## Decision

**`REFINE_COST_MODEL`**

Absolute p50 prediction exceeded the 35% error threshold twice. This does not
invalidate the correct Case B ranking or false-stable result, but it blocks
`PROCEED_TO_COST_SURFACE`.

M0 remains `in_progress`. M1 has not started or completed through this result.

## Verification

- `PYTHONPATH=python python -m compileall -q python`: passed;
- `PYTHONPATH=python python -m unittest discover -s python/tests`: passed,
  88 tests;
- `cargo fmt --all -- --check`: passed;
- `cargo check --workspace --locked`: passed;
- `cargo test --workspace --locked`: passed, including 8 Rust runtime tests;
- all JSON Schema, M1-P0 config, and final result JSON files parse: passed;
- `git diff --check`: passed.

Model loads: 0.

CUDA runs: 0.

## Unproven

- model or GPU savings;
- end-to-end Wan improvement;
- quality parity;
- actual realization of geometric generation-scope savings;
- PyO3/FFI/DLPack cost;
- generalization beyond the three synthetic cases;
- rights-cleared M1 Cost Surface behavior.
- H3 runtime behavior, queue/generation/download timing, price, data handling,
  commercial fitness, integration, selective execution, or speedup;
- an admitted H3 open-weight source, checkpoint, license, digest, or runtime.

## Next exact work

Keep the same five measured combinations. Normalize predictions to a same-run
Mono anchor, isolate motion detection where possible, and rerun the same 5/20
contract. Do not add corpus or proceed to M1 until the cost model is corrected.

## Publication

- implementation commit:
  `30ebdf0b3937c4e7a16dc4f72c7750437ff7dc53`;
- evidence documentation commit: this worklog's Git commit;
- remote branch: `agent/m1-p0-analytical-topology-pruning`, published;
- Issue:
  [#37](https://github.com/ksse29077-byte/HIVEFRAME/issues/37), open for
  review closure;
- Draft PR:
  [#38](https://github.com/ksse29077-byte/HIVEFRAME/pull/38), open and not
  merged;
- Issue #37 scope clarification:
  [comment](https://github.com/ksse29077-byte/HIVEFRAME/issues/37#issuecomment-5143736348);
- H3 Admission Issue:
  [#39](https://github.com/ksse29077-byte/HIVEFRAME/issues/39);
- local/remote HEAD equality: verified after publication;
- final worktree: verified clean after publication.
