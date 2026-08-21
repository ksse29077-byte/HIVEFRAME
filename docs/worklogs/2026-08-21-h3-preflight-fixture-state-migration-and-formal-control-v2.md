# H3 Preflight Fixture State Migration and Formal CONTROL V2

## Authorization and exact base

Issue #131 tracks the one-time constitutional exception for
`H3_PREFLIGHT_FIXTURE_STATE_MIGRATION_AND_FORMAL_CONTROL_V2`. This branch
starts from exact Draft PR #130 head
`c10d2e559b5fc70b69615fcec8d3c864a4302afe`; local, upstream, and remote PR
heads matched and the worktree was clean before branch creation. Existing PRs
remain unchanged.

The authorized code change is limited to migrating stale row-region CUDA
preflight fixtures from `PENDING` to the production slot lifecycle. The
production finalizer must continue to reject `PENDING`, unknown states,
skipped transitions, duplicate finalization, and reuse before FREE.

## Execution boundary

Focused and bounded CUDA fixture Gates must pass before H3 model load or
workflow submission. Only then may exactly one H3 Standard Full Compute Formal
CONTROL run, followed by complete holdout adjudication and one Rust CachePlan
V2 live compile plus deterministic offline replay.

SELECTIVE, partial-Q, Attention omission, executor integration, product
wiring, production-finalizer relaxation, retry, fallback Generation, and
automatic follow-up work are prohibited.

## Starting counters

```text
PRIOR_CUMULATIVE_FORMAL_CONTROL_SUBMISSIONS=2
CURRENT_TASK_FORMAL_CONTROL_SUBMISSIONS=0
CURRENT_TASK_RETRY_COUNT=0
DIAGNOSTIC_SUBMISSIONS=1
```

The PR #130 Admission block had submission/GPU start `0/0` and is not a Formal
CONTROL submission.

Current status: `FIXTURE_MIGRATION_NOT_STARTED`.
