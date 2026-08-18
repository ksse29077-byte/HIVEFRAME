# P1-A1 Real Alpha End-to-End Smoke

Date: 2026-08-18

## Product question

Can a user start the Release Alpha through `scripts/hiveframe-local.cmd`,
submit one real private-reference Local H3 Standard image-to-video request,
and receive a usable MP4 through the product result flow?

Final decision: `P1_A1_REAL_ALPHA_E2E_FAILED`.

## Repository start state

| Item | Value |
|---|---|
| Branch | `product/p1-release-alpha` |
| Start HEAD | `053f10a7ebd0566e927580e5ee3e1c41f993bd35` |
| Remote branch HEAD | matched start HEAD |
| `origin/main` | `f5d2bf8c2f80612909eef21c555d764a116f7062` |
| Draft PR | `#95`, open, draft, base `main` |
| Worktree | clean |

PRs `#91`, `#92`, and `#94` were not changed. No Issue, branch, PR,
reset, rebase, stash, amend, force push, model download, or environment repair
was used.

## Pre-generation Gate

The real entry point was `scripts/hiveframe-local.cmd`. Its preflight found the
existing product Python, ComfyUI root and dedicated Python, all four required
H3 model files, the approved workflow, a writable external artifact root, and
free product/runtime ports. Static backend inspection reported assets and
workflow `ready`. The runtime started locally, `/api/config` returned HTTP 200
with `can_generate=true`, and all model, GPU, Local AI, and storage readiness
states were `ready`.

The launcher process began at `2026-08-18T06:54:32.0717752Z`. Browser creation
was observed 11.905 seconds later. Because the launcher waits for
`/api/config` before invoking the browser, launcher-to-ready was bounded by
`<=11.905` seconds. The automatic browser-open path was invoked once.

The existing P1-A focused suite executed once outside the restricted test
sandbox and passed all 52 tests in 15.620 seconds. Earlier sandboxed
invocations did not reach a valid test run because Windows denied creation of
test-owned child directories; they are environment harness failures, not test
results. No code was changed before the real submission.

## Controlled I2V request

The controlled request used:

```text
mode = image_to_video
backend = minimax_h3_comfyui_local
profile = standard
generation_consent = true
prompt_source = REUSED_PRIVATE_PRODUCT_TEST_PROMPT
reference_source = REUSED_PRIVATE_LOCAL_I2V_REFERENCE
```

The reference remained outside Git. Its product reference asset was created
with SHA-256
`493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411`,
media type `image/png`, and size 258,324 bytes. One matching hash-named file
was present in the local ComfyUI input directory. The backend path performs one
upload before submitting the prompt and wires the resulting local input name
through `LoadImage` to H3 `first_frame`; no URL or external transfer is used.

The product job was `job_118a56bedea446918832e46b28944c80`, and its one
backend prompt was `b9197773-0a60-4c1c-aa79-1edb5f5f6051`. This backend submit
consumed the single P1-A1 Generation budget. Retry count remained zero.

The effective backend profile remained:

```text
864x480
124 frames
24 FPS
20 steps
simple scheduler
res_multistep sampler
denoise 1.0
seed 101
native audio
Sage disabled
candidate_only false
```

No Fast profile, acceleration wrapper, selective path, residual reuse, or
automatic fallback was enabled.

## Failure and safe stop

Before the controlled I2V submit, the same freshly launched product store had
already received a separate unattributed local request. It was a Standard
text-to-video job with no reference asset and had already reached `running`.
The server logs do not identify the local caller, so its origin is not
asserted.

The controlled I2V job was accepted and observed as `queued`, but it could not
provide an isolated one-job E2E measurement. Its ComfyUI prompt was removed
from the pending queue before GPU execution. Read-only queue inspection then
showed the I2V prompt absent from running, pending, and history while the
separate T2V prompt remained the only running item. The separate request was
not interrupted or modified.

The cancellation also exposed a product integration bug: ComfyUI returns a
successful empty body for queue deletion and interrupt commands, while the
loopback client required JSON for every successful response. Queue deletion
succeeded, but the product endpoint surfaced a JSON decode failure and left
the persisted job state stale at `queued`. Commit `14db3a1` now accepts an
empty successful response as `{}`. Eight focused product/backend tests,
including the new regression test, passed in 1.129 seconds. No second real
Generation was run.

Observed P1-A1 lifecycle:

```text
queued
-> removed from ComfyUI pending queue before running
-> no product terminal state because the pre-fix cancellation response failed
```

The required `queued -> running -> succeeded` lifecycle was therefore not
met. `request_to_queued_seconds`, `submit_to_terminal_seconds`,
`running_to_terminal_seconds`, and total product E2E are `null`: the bounded
run was stopped and no successful terminal result exists.

## Result and safety

| Gate | Result |
|---|---|
| P1-A1 workflow submissions | 1 |
| P1-A1 real Generation budget used | 1 |
| Retry | 0 |
| Reference uploads | 1 |
| External transfer | false |
| External API calls | 0 |
| Model downloads | 0 |
| Automatic fallback | 0 |
| OOM | 0 |
| Fatal CUDA | 0 |
| Runtime crash | 0 |
| Artifact save error | 0 |
| Output asset / receipt / result URL | absent |
| MP4 integrity checks | not run; no output |
| Minimal human review | not run; no output |

No codec, resolution, decoded-frame, FPS, audio, corruption, output SHA-256,
download, playback, or usability claim is made. Uncollected result metrics are
not represented as zero.

## Commits and next action

- Product fix: `14db3a1` - `fix(product): repair P1-A1 alpha E2E path`
- Evidence: `docs(product): record P1-A1 real alpha E2E smoke`
- Diagram impact: none; the execution structure did not change.

The next product target is `P1_A1_PRODUCT_FIX`. The empty-response fix is
implemented, but another real Standard I2V Generation requires separate user
approval and a clean launcher store with no pre-existing running or pending
job. PR `#95` remains Draft.

