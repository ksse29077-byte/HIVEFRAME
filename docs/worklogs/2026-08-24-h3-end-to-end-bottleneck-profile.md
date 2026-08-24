# 2026-08-24 H3 End-to-End Bottleneck Profile

## Objective

Freeze the exhausted V4 path and identify a measured H3 acceleration candidate
whose projected product impact is at least 10 percent end to end.

## Start Gate

- PR #138 remained OPEN and DRAFT and was not modified.
- PR #138 local, remote, and GitHub HEAD matched
  `6747e96a6ca94cdb4f137aebc36b86eb4b5b08b4`.
- The source worktree was clean.
- Issue #139 was created.
- Branch `codex/h3-e2e-bottleneck-profile-plan` was created from the exact PR
  #138 HEAD.

## Existing Evidence

The immutable evidence inventory is
`artifacts/h3-high-impact-profile-existing-evidence-20260824.json`. P1-A2
measured 559.391 seconds submit to terminal. The comparable C4-S0 Full Compute
run measured 488.847 seconds in the sampler and 589.913 seconds submit to
terminal. Its six child spans covered 91.253 percent of the sampler, below this
task's 95 percent accounting Gate. V4's final 537.654-second sampler included
19.646 GB of observer evidence transfers and is not a Standard-path profile.

This established that one additional Standard Generation is necessary and
that no previous generation should be repeated.

## Implementation

`H3AggregateTimingController` temporarily wraps the exact installed H3 model
and block methods. It reproduces the source operation order while recording
deferred CUDA event pairs for aggregate leaf categories and enclosing model
and sampler spans. It resolves them after sampler completion with one
synchronization. The callback contains aggregate scalar timings only.

The dedicated ComfyUI node and one-shot runner enforce the unchanged Standard
profile, private first-frame identity, source and workflow hashes, fresh-runtime
ownership, queue emptiness, output integrity, 95 percent accounting, and zero
V4/SELECTIVE/partial-Q/omission execution.

## Focused Verification Before Generation

- Python compilation: PASS.
- New aggregate profiler unit tests: 5 PASS.
- C4-S0 regression tests: 10 PASS, 1 environment-dependent source test SKIP.
- Generation submissions: 0.
- GPU starts: 0.

## Formal Profile

Pending the first implementation commit, push, Draft PR, and clean runtime
Admission Gate. The admitted run count remains exactly one with retry zero.
