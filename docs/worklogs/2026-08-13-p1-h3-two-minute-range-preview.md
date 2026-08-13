# P1-F Local H3 Two-Minute-Range Preview

## Product question

Can the existing RTX 3060 12 GiB machine produce one valid 5-second Local H3
video in the two-minute range while preserving the Standard path as the default
fallback?

The bounded scope was one optional profile, one initial run, and one permitted
revision. No model, sampler, scheduler, seed, frame count, or native-audio
change was explored beyond that scope.

## Preserved baseline

The existing fastest same-profile evidence was reused without rerunning it:

- SageAttention auto submit-to-terminal: `486.247216` seconds;
- effective profile: 864x480, 124 frames, 24 FPS, 20 steps;
- sampler: `res_multistep`; scheduler: `simple`; seed: `101`.

## Candidate runs

| Attempt | Effective profile | Cold wall time | Integrity | Decision |
|---|---|---:|---|---|
| Initial | 608x352, 124 frames, 8 steps, Sage auto | 181.954261 s | 124 decoded frames, H.264, 24 FPS, video and audio streams | `REVISE_ONCE` |
| Final | 480x288, 124 frames, 8 steps, Sage auto | 156.858657 s | 124 decoded frames, H.264, 24 FPS, 5.167 s, video and audio streams | `KEEP_AS_OPTIONAL` |

The final cold result is 3.100x faster than the reused 486.247216-second Sage
baseline, a 67.74% wall-time reduction. ComfyUI reported 155.94 seconds for
the final prompt. The first model initialization occupied about 51.82 seconds;
the eight-step progress phase then reported about 4.18 seconds per step.

The final output SHA-256 is
`251f9ed37a4314105385d4f07efe404c11e7e87de27fc06bf90f20d0a5b9094e`.
Prompts, machine paths, full receipts, logs, and generated media remain outside
Git.

## Product decision

Decision: `KEEP_AS_OPTIONAL`.

`fast_2m_candidate` is exposed only for the Local H3 ComfyUI backend. It uses
480x288, 124 frames, 24 FPS, 8 steps, the existing scheduler and sampler, seed
101, native audio, and SageAttention auto. The UI labels it experimental and
shows the effective settings. Standard remains the default and its 864x480,
20-step workflow is unchanged.

This result proves a valid two-minute-range output on the measured machine. It
does not prove quality parity with Standard. A first/middle/last-frame visual
check found no obvious corruption or broken subject/background continuity, but
final quality acceptance remains a user decision. No further profile sweep or
generation run is authorized by this task.

## Verification

- `PYTHONPATH=python python3 -m compileall -q python`: passed under WSL.
- Focused Local H3, product-contract, Sage, and fallback tests: 28 passed.
- Broader suite with the ComfyUI Python: 449 tests ran; 427 passed and 12
  skipped. Nine unrelated Windows SQLite cleanup errors and one pre-existing
  C0 knowledge-status mismatch remained; no fast-profile assertion failed.
- Standalone JavaScript parse check: unavailable because Node.js is not
  installed in the current Windows shell; the UI request path is covered by
  the focused product tests.
- Cold generation attempts: exactly 2, including the one permitted revision.
- Final decode: 124/124 frames, 0 black frames, video stream 1; audio stream 1,
  162 decoded audio frames, and 165,888 decoded audio samples.
- External API calls and model downloads: 0.
- Standard fallback: preserved and still selected by default.

Implementation commit: `11ec012`.

Remote push: not attempted; repository rules require explicit authorization
for this exact repository.
