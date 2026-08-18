# P1-A Release Alpha Product Shell and One-Click Local Launcher

## Decision

`P1_A_RELEASE_ALPHA_SHELL_READY`

The existing Local H3 Standard path is now packaged as an Alpha product shell
with explicit Text-to-Video and Image-to-Video modes, readiness reporting, a
bounded Windows launcher, localized lifecycle/error handling, video playback,
download, and simplified feedback. No model was loaded and no Generation was
submitted during this work.

## Starting repository state

| Item | Value |
|---|---|
| `origin/main` | `f5d2bf8c2f80612909eef21c555d764a116f7062` |
| Product source branch | `codex/p1-h3-two-minute-profile` |
| Product source SHA | `e04259fa00539a2e1c56d8944dbb80857073b851` |
| Product branch | `product/p1-release-alpha` |
| Starting worktree | clean |
| PR #91 / #92 / #94 | read-only and unchanged |

The source SHA was used directly because it contains the existing Local H3
T2V, first-frame I2V, ComfyUI upload, Standard workflow, product job lifecycle,
artifact, result, and feedback lineage. No acceleration branch was used as a
product base and no cherry-pick, reset, rebase, stash, or force operation was
performed.

## Product surface

### Before

The inherited P0 page exposed backend and execution-profile selectors, Mock as
the default, experimental fast-profile language, raw internal job states, and
developer-oriented ComfyUI terminology. Image input implicitly selected I2V.

### After

The first screen is the usable HIVEFRAME studio. It contains:

- explicit `text_to_video` and `image_to_video` modes;
- a prompt field and I2V-only image chooser with browser preview;
- a fixed Standard Quality summary;
- GPU, Local AI, Model, and Storage readiness;
- localized state, elapsed time, cancellation, bounded retry, and actionable
  product errors;
- successful-video playback and file download;
- two-step positive/negative feedback with rejection reasons shown only after
  a negative choice.

Normal mode has no backend selector, fast profile, Mock choice, raw job ID, or
training opt-in. `HIVEFRAME_DEV_MODE=1` exposes Mock for development and tests.

## T2V and I2V contracts

T2V is the default mode. It never persists or sends a reference image, even if
a stale reference value is supplied. I2V requires exactly one bounded
first-frame image. PNG, JPEG, and WebP filename/media-type pairs are accepted;
unsupported, mismatched, empty, and over-10-MiB inputs fail before backend
submission. The stored request continues to reference media only by asset ID.

## Standard Quality policy

Normal product requests are fixed to `standard` and the existing Local H3
workflow profile:

```text
864x480
124 frames
24 FPS
20 steps
simple scheduler
res_multistep
denoise 1.0
native audio
```

Normal-mode attempts to request `fast_2m_candidate` are rejected. The
historical backend capability remains untouched and is not product-exposed.

## Readiness and errors

Readiness reuses the existing Local H3 runtime, asset, and workflow inspection.
GPU is ready only when the inspected ready runtime reports CUDA; otherwise it
is `needs_attention`. Local AI, Model, and Storage similarly fail closed rather
than inventing readiness. The Generate button requires all product readiness.

Stored backend error codes remain unchanged. The normal UI maps runtime,
missing model/assets, OOM, artifact save, and timeout failures to concise Korean
messages. Raw job and backend details are visible only in developer mode.

## Launcher

`scripts/hiveframe-local.cmd` is the double-click entry point and delegates to
`scripts/hiveframe-local.ps1`. The PowerShell launcher:

1. verifies the repository and Python import;
2. verifies the prepared ComfyUI root and its dedicated Python;
3. verifies all four required H3 model files and the workflow;
4. verifies a writable external artifact root and an available product port;
5. starts the product server with Local H3 runtime preflight;
6. opens the browser once, only after `/api/config` is reachable.

The product process starts ComfyUI only when its configured loopback runtime is
not already reachable. It records ownership and stops only a runtime it started.
An already-running external ComfyUI remains untouched. Ctrl+C returns through
the product `finally` path. The launcher performs no install, update, download,
elevation, registry change, permanent PATH change, telemetry, or external API
request.

## Validation

| Validation | Result |
|---|---|
| Existing product focused tests | 20 passed |
| P1-A named product/launcher tests | 32 passed |
| Total focused tests | 52 passed |
| Python compile check | passed |
| JavaScript syntax check | passed |
| PowerShell parser check | passed |
| `git diff --check` | passed |
| Desktop browser check | passed; no console errors |
| Mobile browser check | passed at 390x844; no horizontal overflow |
| I2V mode visibility check | passed |
| Normal Mock/fast-profile visibility | absent |
| Launcher missing-Python path | bounded failure passed |
| Launcher bad-runtime path | bounded failure passed |
| Launcher port-conflict path | bounded failure passed |
| Launcher server-ready smoke | passed |
| Browser ordering | `server_ready` before `browser_open` |

Historical acceleration and Rust suites were not run because no changed product
code depends on them. Model downloads, external network calls, and actual H3
Generation were not used.

## Counts and provenance

| Item | Count |
|---|---:|
| Actual H3 Generation | 0 |
| External API calls | 0 |
| Model downloads | 0 |
| Automatic fallback | 0 |
| Acceleration evidence changes | 0 |

## Commits and push

- Source: `e04259fa00539a2e1c56d8944dbb80857073b851`
- Implementation: `9e571c9` - `feat(product): build HIVEFRAME local release alpha shell`
- Evidence: `docs(product): record P1-A release alpha evidence` (this commit;
  final SHA is recorded in the PR and final report)
- Implementation push: verified on `origin/product/p1-release-alpha`
- Evidence push: verified after the evidence commit

## Known limitations

This Alpha does not add an installer, dependency/model manager, updater, branded
desktop executable, 1080p upscaler, job-history UI, Sage product promotion,
selective acceleration, or a final commercial-license gate. Those are separate
product decisions.

## Final decision

All P1-A product gates passed without lowering the Standard profile or invoking
Generation.

`P1_A_RELEASE_ALPHA_SHELL_READY`
