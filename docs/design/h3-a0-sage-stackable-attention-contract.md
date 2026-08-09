# A0 SageAttention Stackable Component Contract

Status: predeclared before offline artifact analysis

## Product question

Can the immutable F0 SageAttention observation be retained as an independent,
optional attention-kernel component after an offline catastrophic-regression
screen, while Standard Full Compute remains the safe fallback and future
Compound Eye/Rust work remains separately authorized?

This is not a new selective-attention experiment and is not a final 2.0x
product admission. The integrated product target remains Quality at least as
good as Standard Full Compute and accepted-result end-to-end speedup of at
least 2.0x. A single component is not required to reach that target alone,
and component ratios are never multiplied to claim integrated performance.

## Immutable handoff

The historical decision `F0_SAGE_NO_GAIN`, its 1.3x standalone-candidate Gate,
the fixed profile, runtime values, output hashes, and private artifacts remain
immutable. A0 does not reinterpret that decision. It asks a new, narrower
stack-component question and explicitly does not reuse either a standalone
1.3x or 2.0x Gate.

Existing F0 Standard and Sage artifacts must be reused when their run IDs,
workflow hash, output hashes, fixed output contract, pair manifest, contact
sheet, and side-by-side hashes match. A new pair is allowed only if reuse is
invalid; it is capped at one Standard and one Sage Generation with no retry.

## Fixed automatic screen

The frame-aligned offline screen records decoded frame count, dimensions,
codec, FPS, audio, black/corrupt frames, global grayscale SSIM, normalized
MAE, adjacent-frame motion energy, spatial-gradient energy, and temporal
difference energy. The catastrophic-regression Gate requires:

- normalized MAE at most 0.06;
- motion, gradient, and temporal-difference ratios each in [0.80, 1.25];
- the complete fixed output-integrity contract.

SSIM is diagnostic only and cannot independently reject or admit the
component. An automatic pass means only
`AUTOMATIC_REGRESSION_SCREEN_PASSED`; visual equivalence and Quality >=
Standard remain unproven until human review.

## Review and decision boundary

The private review package uses frames 0, 31, 62, 93, and 123 plus up to three
highest-motion Standard transitions, deduplicated. Each row shows Standard,
Sage, and amplified absolute difference. Repository content stores only
sanitized aggregate metrics, logical artifact IDs, hashes, and review state.

An automatic pass yields
`A0_SAGE_STACKABLE_COMPONENT_READY_FOR_VISUAL_REVIEW`, disposition
`KEEP_AS_OPTIONAL`, component status `AVAILABLE_OPTIONAL`, product default
false, and human review `PENDING_HUMAN_REVIEW`. Failure uses the predeclared
matrix without claiming all attention acceleration is impossible. Standard
Full Compute remains independently available in every outcome.

Compound Eye execution, Rust attention policy/ABI, attention workload
omission or reuse, product Fast Mode, model training, and the next A1 stage are
outside this contract.
