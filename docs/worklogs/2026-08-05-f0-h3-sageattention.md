# F0-SAGE — Local MiniMax H3 SageAttention KJ paired validation

Date: 2026-08-05

Issue: [#55](https://github.com/ksse29077-byte/HIVEFRAME/issues/55)

Branch: `accel/f0-h3-sageattention`

Starting `main`: `d716a2231e929796840d58377c98594298683939`

Feature contract commit: `bb480b1623ae42c96f3ead8b0d0cbddfaf1f1068`

Status: evidence recorded; Draft PR review pending

Decision: **`F0_SAGE_NO_GAIN`**

## Product question and claim boundary

The bounded question was whether the external KJNodes `Patch Sage Attention
KJ` node in `auto` mode could reduce the current Local MiniMax H3 generation
time to one half or less, without breaking the existing output contract, on an
RTX 3060 12 GiB. The paired experiment fixed the current P0 prompt, seed,
workflow, model components, resolution, frames, FPS, steps, scheduler, sampler,
denoise, native-audio path, output codec contract, and polling behavior.

This is an **external F0 attention-kernel comparison**. It is not a HIVEFRAME
Core acceleration result. Change detection, compound-eye observation, cache
reuse, selective recompute, boundary verification, and selective repair were
not implemented or measured. The Standard full-compute path remains the
product fallback.

## Starting state and reused P0 evidence

PR #54 was merged through merge commit
`d716a2231e929796840d58377c98594298683939`; Issue #53 was completed; local
`main` and `origin/main` matched; and the worktree was clean. The published
decision `P0_LOCAL_H3_COMFYUI_READY` was present on `main`. No duplicate F0
Issue, branch, or PR existed, so Issue #55 and the dedicated branch were
created from that exact main.

The original workflow remained under logical root `H3_ASSET_ROOT`. Its
SHA-256 stayed
`31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6`.
The four required logical model components and the private P0 receipt were
present. The P0 prompt was read from the private repository-external P0
database; only its SHA-256
`4d91c71a70cb55ca844628def1bfd4815d3af710f9e66a4c539e7673934b9c0a`
was used in public evidence. The prompt text was not copied into Git, logs,
Issue text, or PR text.

## Environment fingerprint

| Component | Fixed value |
|---|---|
| Runtime logical ID | `COMFYUI_DESKTOP_MOBEON` |
| ComfyUI | 0.30.2 |
| ComfyUI commit | `dec5d9450a5290bcf63430409ea41018e67f41c3` |
| Python | 3.13.12 |
| PyTorch | 2.12.1+cu130 |
| PyTorch CUDA build | 13.0 |
| GPU | NVIDIA GeForce RTX 3060 |
| Compute Capability | 8.6 |
| Device memory | 12,884,377,600 bytes |
| ComfyUI allocator | `cudaMallocAsync` |

Installation changed none of Python, PyTorch, torchvision, torchaudio,
ComfyUI core, the CUDA Toolkit, or the NVIDIA driver. Installation created a
separate fixed KJNodes checkout in the runtime's custom-node area and added
only the packages described below to the existing ComfyUI virtual environment.
The pre-install `pip freeze`, ComfyUI commit/status, custom-node inventory,
runtime fingerprint, install logs, checksums, and rollback plan remain outside
Git under the private F0 evidence root.

## Fixed sources and installation

KJNodes was pinned to
[`kijai/ComfyUI-KJNodes@6edfa765`](https://github.com/kijai/ComfyUI-KJNodes/tree/6edfa76599c13905968841b81309784a7dbb7803),
reported by that source as version 1.4.9. The registered API class is the
upstream spelling `PathchSageAttentionKJ`. `/object_info` confirmed that the
node was registered and that `auto` was an admitted selection.

The algorithm source was pinned to
[`thu-ml/SageAttention@v2.2.0`](https://github.com/thu-ml/SageAttention/tree/v2.2.0).
The official project does not provide the selected Windows binary. The runtime
therefore used the fixed Windows ABI3 package
`sageattention-2.2.0+cu130torch2.10.0andhigher.post6-cp310-abi3-win_amd64.whl`
from the immutable trusted-third-party
[`woct0rdho/SageAttention` post6 release](https://github.com/woct0rdho/SageAttention/releases/tag/v2.2.0-windows.post6).
Its SHA-256 is
`1635283f5c01ec3cda58a784d0d7eabbcaffaf9511d1b263db4750e1ed7958bb`.
The package was installed with `--no-deps`.

The RTX 3060 `auto` path requires Triton. The official Windows distribution
`triton-windows==3.7.1.post27` supplied the exact CPython 3.13 wheel
`triton_windows-3.7.1.post27-cp313-cp313-win_amd64.whl`; its SHA-256 is
`e8ed215c02afc85a81f0097196f8bebdf6f68085f1bc0fe8771b9a74783f15ab`.
It was also installed with `--no-deps`. No separate system CUDA Toolkit was
installed.

KJNodes' fixed non-Torch additions were `color-matcher==0.6.0`,
`matplotlib==3.11.1`, `mss==10.2.0`,
`opencv-python-headless==5.0.0.93`, `ddt==1.7.2`, `docutils==0.23`,
`imageio==2.37.4`, `contourpy==1.3.3`, `cycler==0.12.1`,
`fonttools==4.63.0`, `kiwisolver==1.5.0`, `pyparsing==3.3.2`,
`python-dateutil==2.9.0.post0`, and `six==1.17.0`. Existing NumPy, Pillow,
SciPy, and Torch-family packages were retained. `pip check` reported no broken
requirements.

The first package command installed the KJNodes dependencies successfully but
PowerShell treated pip's informational standard-error output as a terminating
shell error before either acceleration wheel ran. The corrected command
installed the two pre-verified wheels and confirmed the protected runtime
fingerprint was unchanged. Two initial ad-hoc kernel harness attempts stopped
before a kernel ran: one lost a quoted device string in PowerShell, and one
defined a Triton JIT function under `python -c`, which Triton correctly rejects
because it requires source-file inspection. The final package check invoked
the installed SageAttention file-based kernel on a small BF16 CUDA tensor;
shape and finite-value checks passed on Compute Capability 8.6. These harness
failures were not model generations or benchmark samples.

ComfyUI then started once without loading H3, imported KJNodes, exposed the
node through `/object_info`, and exposed `auto`. The owned process was stopped
before model runs began. No import, DLL, or CUDA-kernel compatibility blocker
remained.

## Workflow patch contract

The user workflow was never rewritten. The Standard API copy still contains
zero Sage nodes. The Sage API copy adds exactly one node:

```text
UNETLoader MODEL
    -> PathchSageAttentionKJ(sage_attention=auto, allow_compile=false)
    -> BasicScheduler model
    -> BasicGuider model
```

The actual graph has no separate Fusion node. Both consumers of the original
`UNETLoader:0` MODEL edge—`BasicScheduler:model` and `BasicGuider:model`—were
rewired to the one patched MODEL output. No other node or setting changed.
Because the KJ node documents that its override is not normal model patching,
Standard and Sage each ran in a separately started and stopped owned ComfyUI
process. No global `--use-sage-attention` flag was used.

## Predeclared execution profile

| Field | Both runs |
|---|---:|
| Width × height | 864 × 480 |
| Frames | 124 |
| FPS | 24 |
| Steps | 20 |
| Scheduler | `simple` |
| Sampler | `res_multistep` |
| Denoise | 1.0 |
| Seed | 101 |
| Audio | native |
| Prompt | same private P0 prompt; hash matched |

Run A was Standard exactly once. Its runtime stopped, both loopback ports were
free, and system-sampled GPU usage returned to 10 MiB before Run B began. Run
B was Sage KJ `auto` exactly once in a new process. No third generation,
retry, smaller profile, alternate seed, alternate Sage mode, cache node, or
other accelerator was used.

## Paired measurements

| Metric | Standard | Sage `auto` | Paired result |
|---|---:|---:|---:|
| Runtime startup | 7.576036 s | 9.619052 s | separate processes |
| Queue wait | 0.083811 s | 0.071986 s | — |
| Running-to-terminal | 586.888688 s | 486.175229 s | 1.207155× |
| Submit-to-terminal | 586.972500 s | 486.247216 s | **1.207148×** |
| Runner entry through runtime stop | 595.482869 s | 497.111835 s | 1.197885× |
| Time reduction, submit scope | — | — | **17.160137%** |
| Peak system-sampled VRAM | 12,460,611,508 B | 12,460,611,508 B | no reduction observed |
| Peak system-wide used RAM | 60,500,926,464 B | 60,398,510,080 B | -102,416,384 B |
| OOM | 0 | 0 | 0 |
| Retry | 0 | 0 | 0 |

ComfyUI's own log reported full prompt spans of 586.65 seconds and 485.90
seconds, consistent with the client measurements. The runtime did not isolate
model load, denoising, per-step, video-VAE decode, audio-VAE decode, or encode
spans. Those fields remain `null/not_collected` with reasons. In particular,
the 1.207155× running-span ratio is not relabeled as a denoising speedup.

The historical P0 submit-to-terminal value was 587.513159 seconds. The new
paired Standard was 586.972500 seconds and reproduced the exact P0 output
SHA-256, but the F0 decision uses the same-session-era paired Standard and
Sage observations rather than the historical number.

## Output integrity and private review artifacts

| Output | Standard | Sage `auto` |
|---|---:|---:|
| Size | 262,579 B | 264,736 B |
| Codec | H.264 | H.264 |
| Resolution | 864 × 480 | 864 × 480 |
| Decoded frames | 124/124 | 124/124 |
| FPS | 24 | 24 |
| Duration from decoded frames | 5.166667 s | 5.166667 s |
| Audio streams | 1 | 1 |
| Fully black frames | 0 | 0 |
| Decode corruption | 0 | 0 |

The Standard SHA-256 is
`ec4ddbacaf9a9d578885c61b3514abc15dad1172566cd4ce84198f7a3bd641c4`,
exactly matching P0. The Sage SHA-256 is
`147eb7872394fcb98a9a8990eb1a132bb776253739a238f38333220e6bcee120`.
Different hashes are expected after changing numerical attention execution;
they are not proof of better or worse quality.

Repository-external private artifacts include logical IDs
`F0_STANDARD_VIDEO`, `F0_SAGE_AUTO_VIDEO`, a five-timestamp contact sheet, and
a 124-frame side-by-side preview. The contact sheet SHA-256 is
`2c065fc687967effbb848e790ad9e88c62bde9341f77968c8ba55e383f5dc1f5`;
the preview SHA-256 is
`651ae67f84a2c47ae2ddaf3484bbc54d185ef48a68dcbb6e41ddc0ec6aa9b983`.
The sampled contact sheet had no obvious black output or gross corruption,
but no perceptual flicker metric or full human equivalence judgment was
admitted. **`VISUAL_QUALITY_REVIEW_REQUIRED`** remains the quality state.

## Focused verification and omissions

The first model-free test attempt was blocked by the desktop sandbox's default
temporary-directory ACL. A second location was rejected by the product's
intentional “artifacts outside Git” boundary. The final external temporary
root collected the intended tests. Thirteen focused tests passed in 0.051
seconds: nine new F0 tests plus four existing Local H3 ComfyUI tests. They
cover exactly-one-node insertion, zero-node Standard, both MODEL edges, fixed
settings, immutable input copy, Standard fallback, error normalization,
bounded polling, path/output-prefix safety, public path/prompt filtering,
runtime/asset/workflow inspection, sanitized receipt provenance, and cancel
semantics. `git diff --check` passed. The original workflow hash was checked
before and after the runs and stayed unchanged.

Full Python, full Rust, M0, M1, repeated generation, multi-seed, profile sweep,
Sage-mode sweep, VRAM benchmark, perceptual benchmark, model hash sweep, and
other accelerator tests were intentionally not run. Model downloads 0;
external MiniMax API calls 0; API keys 0; paid calls 0; model-asset changes 0;
original-workflow changes 0; model/media/tool binaries tracked 0; Standard
generations 1; Sage generations 1; total H3 generations 2; retries 0.

## Decision and retained product/core knowledge

The fixed Fast-candidate threshold was 1.3×, and the strong target was 2.0×.
The paired submit speedup was 1.207148×. Therefore the only valid bounded
decision is **`F0_SAGE_NO_GAIN`**. Sage KJ `auto` is not enabled as a product
default or optional Fast mode, and no other Sage profile is searched
automatically. Standard full compute remains available and unchanged.

H3-specific knowledge now includes the exact node class, fixed KJNodes commit,
SageAttention and Triton packages, RTX 3060 compatibility, `auto` behavior,
MODEL insertion point, process-restart boundary, output integrity, and the
sub-threshold paired result. HIVEFRAME Core retains a concrete MODEL edge that
a future controller may observe, but no proprietary compute reduction is
claimed. The single paired result is `verified_once`; automatic promotions are
zero.

The next action is user direction. Under the declared protocol, a
`F0_SAGE_NO_GAIN` result keeps Standard and forbids automatic exploration of
another accelerator. No Ready transition or merge is authorized for the Draft
PR, and no Rust, compound-eye, selective-compute, or model-training work starts
from this result.
