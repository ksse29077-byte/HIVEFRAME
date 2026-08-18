# P1-A2 Shared Runtime Guard and Clean Alpha E2E

Date: 2026-08-18

## Product question and decision

Can HIVEFRAME protect work already present in the shared local generation
runtime, then complete exactly one Standard image-to-video job from a clean
product store when that runtime is idle?

Final decision: `P1_A2_REAL_ALPHA_E2E_READY`.

This decision means the current product path completed end to end. It does not
mean that the current engine is commercially competitive.

## Repository start state

| Item | Value |
|---|---|
| Branch | `product/p1-release-alpha` |
| Start HEAD | `2343197b37e2ca0b3b7beec28338c4e918c934bd` |
| Remote branch HEAD | matched start HEAD |
| `origin/main` | `f5d2bf8c2f80612909eef21c555d764a116f7062` |
| Draft PR | `#95`, open, draft, base `main` |
| Worktree | clean |

PRs `#91`, `#92`, and `#94` were not changed. No Issue, branch, PR, reset,
rebase, stash, amend, force push, model download, or environment repair was
used.

## Preserved P1-A1 evidence and conflict context

The P1-A1 decision remains `P1_A1_REAL_ALPHA_E2E_FAILED`: launcher and
readiness passed, the controlled Standard I2V was submitted, a separate
unattributed T2V was running, the I2V was removed before GPU execution, retry
remained zero, and there was no output.

The user subsequently confirmed that they were running T2V in another video
creation screen backed by the same local environment at that time. This is
recorded as `LIKELY_SHARED_RUNTIME_USER_T2V_CONFLICT`. Prompt ownership was not
proven, so no `PROVEN_OWNER=user` claim is made.

## Shared runtime policy and guard

Alpha now uses a single-GPU-job policy. A read-only queue snapshot is busy when
`running_count > 0 OR pending_count > 0`. The backend checks this state before
any reference upload and checks it again immediately before `/prompt`. Product
submissions are serialized within the process so simultaneous product requests
cannot both pass the second check.

Busy readiness is presented as `Generation: 다른 작업 실행 중`, with the
normal product message:

```text
현재 다른 영상 생성 작업이 실행 중입니다. 작업이 완료된 후 다시 시도해주세요.
```

The app remains available while busy, but Generate is disabled. The guard does
not delete, cancel, interrupt, or clear any foreign prompt. A private input
uploaded before a second-check race is left in place rather than adding a risky
shared-runtime cleanup operation.

The focused test set covered empty, running, pending, combined, pre-upload,
pre-submit race, no-foreign-termination, idle-transition, Korean-message, and
empty-success cancellation cases. The P1-A2/relevant product suite passed 51
tests in 6.850 seconds. One unrelated legacy launcher test was excluded from
that invocation because the user-owned P1-A1 app already occupied its hardcoded
default port; the earlier full invocation passed its other 51 tests and failed
only that environment assumption.

Commit 1 was pushed immediately:

`93f52ce` - `fix(product): guard shared Local AI runtime before generation`

Product code was frozen after that commit.

## Clean idle Gate and launcher

The shared runtime was inspected read-only immediately before the real run:

```text
running = 0
pending = 0
```

A new external product artifact root was used. Its persisted product job count
was zero immediately before submission. The existing P1-A1 app, store, and
runtime were not stopped or modified. The real entry point was
`scripts/hiveframe-local.cmd`, started on a separate loopback product port. The
new app returned HTTP 200 with backend `ready`, `can_generate=true`, and
Generation `ready`. Launcher-to-ready was bounded by the 6.3-second launch and
readiness orchestration span.

An initial orchestration attempt had incorrect Windows quoting and stopped
before the command file ran. It created no store, product job, backend prompt,
or GPU work and did not consume the generation budget.

## One real Standard I2V

The run reused the approved private product-test prompt and the prior private
local I2V reference. Neither is stored in Git or reproduced here. The reference
SHA-256 matched the P1-A1 evidence:

`493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411`

The effective profile remained:

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

Fast profile, selective execution, acceleration wrappers, external APIs,
automatic fallback, and model downloads were all zero.

Accounting for the bounded run:

| Counter | Value |
|---|---:|
| `product_job_create_count` | 1 |
| `backend_prompt_submission_count` | 1 |
| `gpu_execution_started_count` | 1 |
| `completed_generation_count` | 1 |
| `retry_count` | 0 |
| `foreign_job_termination_count` | 0 |

The one product job and its one backend prompt were tracked without mixing IDs.
The observed lifecycle was exactly:

```text
queued
-> running
-> succeeded
```

After completion the backend history reported `success` and `completed=true`,
and the shared queue returned to running zero and pending zero.

## Runtime evidence

| Span | Seconds | Source |
|---|---:|---|
| Launcher to ready | `<= 6.3` | bounded launcher/readiness orchestration |
| Product submit to backend accepted observation | `0.332` | product poll harness |
| Backend accepted observation to running observation | `0.259` | product poll harness |
| Running to terminal | `559.313` | backend monotonic receipt |
| Backend submit to terminal | `559.391` | backend monotonic receipt |
| Product submit to terminal observation | `559.988` | product poll harness |
| Total product E2E including result flow | `559.990` | product poll harness |

The receipt sampled resources 1,023 times. It reported no OOM, fatal CUDA
error, runtime crash, artifact save error, or retry. No profiler, Nsight, or
CUPTI run was added.

## Result integrity and product flow

| Gate | Result |
|---|---|
| Container / codec | MP4 / H.264 |
| Resolution | 864x480 |
| Decoded frames | 124/124 |
| FPS | 24.0 |
| Audio streams | 1 |
| Decoded audio frames | 162 |
| Black frames | 0 |
| Corrupted frames | 0 |
| Result asset | present |
| Receipt | present, status `succeeded` |
| Result URL | HTTP 200 |
| Download bytes | 329,399 |
| Download contract | PASS |
| Output SHA-256 | `6243074127ddf75e6d41fac2ff75710585978185e2d1e5bde7d4cf8ae7fef539` |

The fresh store contains one job, one succeeded job, one output link, one
receipt link, and retry sum zero. Local full-frame decoding was used for the
integrity check; no network or additional generation was used.

## Minimal visual product review

`VISUAL_PRODUCT_RATING=LOW_QUALITY_BUT_FUNCTIONAL`

Five frames spanning the completed output preserve the reference subject and
background and show motion without black output or obvious structural failure.
One motion sample is soft/blurred, and the overall result does not justify a
stronger commercial-quality claim. It is functional and not
`OBVIOUSLY_BROKEN`.

## User-reported product feedback

The following is `USER_REPORTED_PRODUCT_FEEDBACK`, not a Codex measurement:

```text
user_reported_output_duration approximately 5 seconds
user_reported_generation_time > 10 minutes
user_reported_quality = unsatisfactory
```

The clean P1-A2 run measured separately above does not erase or reinterpret
that feedback.

## Safety, commercial boundary, and next target

```text
external API calls = 0
model downloads = 0
auto fallback = 0
foreign job termination = 0
OOM = 0
fatal CUDA = 0
```

`P1_A2_REAL_ALPHA_E2E_READY` means only that the guarded product path completed
successfully. `COMMERCIAL_ENGINE_READY` is not asserted. Installer work is not
started automatically.

`ENGINE_COMPETITIVENESS_REQUIRED=true`

The next separately approved product target is
`ENGINE_COMPETITIVENESS_GATE_BEFORE_INSTALLER`: determine whether an RTX 3060
12GB-class system can use a local video engine/runtime with a better
quality/time/VRAM combination than the current H3 Standard path.

## Commits and pull request

- Commit 1: `93f52ce` - `fix(product): guard shared Local AI runtime before generation`
- Commit 2: `docs(product): record P1-A2 clean alpha E2E evidence`
- Existing Draft PR: `#95`; append `P1-A2 Shared Runtime Guard + Clean E2E`
- Ready: no
- Merge: no
