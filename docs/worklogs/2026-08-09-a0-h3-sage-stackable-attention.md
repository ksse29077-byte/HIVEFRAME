# A0 — H3 SageAttention Stackable Component Admission

Date: 2026-08-09

Issue: [#80](https://github.com/ksse29077-byte/HIVEFRAME/issues/80)

Draft PR: [#81](https://github.com/ksse29077-byte/HIVEFRAME/pull/81)

Branch: `accel/a0-h3-sage-stackable-attention`

Base `main`: `e8ba897033db6658d4114ffdf3a9060cf9a7d8a5`

Contract commit: `91114dc5def016418df96b9de053f4b317883ec1`

Status: `A0_SAGE_STACKABLE_COMPONENT_READY_FOR_VISUAL_REVIEW`

## Product question and constitutional boundary

A0 asks whether the immutable F0 SageAttention result may be retained as a
quality-screened, optional attention acceleration component in a cumulative
stack while Standard Full Compute remains the fallback. It does not ask
whether SageAttention alone reaches the final product goal, and it does not
reinterpret the historical F0 decision.

The work follows the Product-First, Quality-First, and Model-Replaceable Core
rules. `QUALITY FAILURE OVERRIDES SPEEDUP`; observation does not grant compute
authority; uncertain evidence falls back to Full Compute. The final integrated
target remains accepted-result end-to-end speedup of at least 2.0x with quality
at least Standard Full Compute. Independently measured component ratios must
not be multiplied to claim that target.

SageAttention is an external attention kernel, not a HIVEFRAME invention.
The optional component remains outside the generic Core and does not alter the
Compound Eye contracts, Rust ABI, tensor boundary, workflow defaults, cache,
or training policy.

## Immutable F0 evidence

The original F0 result remains `F0_SAGE_NO_GAIN`. A0 does not delete, edit, or
supersede that evidence. The former standalone candidate rule was 1.3x; the
observed submit-to-terminal ratio was 1.207148x, so F0 correctly rejected a
standalone product accelerator under that contract. A0 removes neither that
threshold nor that conclusion. It poses a different, cumulative-stack product
question in which an individual optional component need not independently
reach 1.3x or 2.0x.

The reused fixed-profile evidence is:

| Metric | Standard | SageAttention | Comparison |
|---|---:|---:|---:|
| Submit-to-terminal | 586.972500 s | 486.247216 s | 1.207148x; 17.160137% reduction |
| Runner total | 595.482869 s | 497.111835 s | 1.197885x |
| NVIDIA sampled peak VRAM | 12,460,611,508 B | 12,460,611,508 B | no measured reduction |

Both outputs are H.264, 864x480, 124/124 decoded frames, 24 FPS, with one audio
stream, zero black/corrupt frames, zero OOM, and zero retry. Output hashes,
workflow identity, fixed profile, and prompt hash matched the historical F0
records before reuse was admitted.

## Artifact reuse and execution count

The private F0 summaries, videos, and pair manifest were located through the
known evidence contract rather than a broad filesystem search. Their recorded
and actual SHA-256 values matched, their terminal states were successful, and
their output contracts were intact. Therefore the reuse result is
`F0_ARTIFACTS_REUSED`.

- new model Generation: 0;
- retry: 0;
- CUDA Generation: 0;
- new performance benchmark: 0;
- model download/load: 0;
- external API and paid service call: 0.

One offline CPU analysis read the already existing output pair. It did not
invoke ComfyUI, load a model, execute CUDA, or alter the historical artifacts.

## Predeclared automatic regression screen

The first commit fixed the source hashes, output contract, thresholds, review
frames, decision names, component status, fallback, and claim limits before
the offline comparison was run. The screen required exact container/frame
integrity plus:

- normalized MAE <= 0.06;
- motion-energy ratio in [0.80, 1.25];
- spatial-gradient-energy ratio in [0.80, 1.25];
- temporal-difference-energy ratio in [0.80, 1.25].

SSIM was predeclared as diagnostic only. It cannot establish that quality is
at least Standard or that the outputs are visually equivalent.

## Offline comparison result

| Metric | Result | Gate role |
|---|---:|---|
| Mean SSIM | 0.9731167693 | diagnostic only |
| p05 SSIM | 0.9636989394 | diagnostic only |
| Minimum SSIM | 0.9541882650 | diagnostic only |
| Normalized MAE | 0.0180652791 | pass |
| Motion-energy ratio | 0.9861993840 | pass |
| Spatial-gradient-energy ratio | 1.0293416258 | pass |
| Temporal-difference-energy ratio | 1.0339983527 | pass |
| Output integrity | exact | pass |

The bounded automatic result is `AUTOMATIC_REGRESSION_SCREEN_PASSED`. This is
not a human quality verdict. `quality_at_least_standard_proven` remains false
and `visual_equivalence` remains `not_proven`.

## Private human-review package

A repository-external package contains Standard, SageAttention, and absolute
difference views for fixed frames 0, 31, 62, 93, and 123 plus the three
highest Standard-motion transition frames 67, 68, and 69. The contact-sheet
SHA-256 is
`99c3d98e09ccdec5c35896ed8d04c132f04c269803b0f9f20e244816b81071d4`;
the review-manifest SHA-256 is
`1e2ab0daaf5a426d23cd77310d93682e156308074b82e196f8ad09d3a5ff8fbf`.

The package, videos, complete private receipt, prompt, logs, and local paths
remain outside Git. Human review is `PENDING_HUMAN_REVIEW`; no human decision
has been inferred or recorded.

## Decision and product meaning

The automatic decision is
`A0_SAGE_STACKABLE_COMPONENT_READY_FOR_VISUAL_REVIEW` with disposition
`KEEP_AS_OPTIONAL`. Component state is `AVAILABLE_OPTIONAL`; product default
is false. Standard Full Compute remains the independently available fallback.

This decision means only that the historical 1.207148x result survived the
fixed catastrophic-regression screen and is worth human review as one
stackable component. It does not establish final 2.0x acceleration, quality
parity, attention workload removal, VRAM savings, a product default, or a
product promotion. Speedup claim and product promotion counts remain zero.

The C4-S0 observation that global attention accounted for 70.2245% of the
measured adapter surface explains why an external attention-kernel component
is economically relevant. It does not prove independence from other future
components, authorize multiplying ratios, or change C4's Full Compute safety
boundary.

## Failure contract and next candidate

No A0 failure branch was triggered. Had provenance, integrity, fixed metrics,
runtime compatibility, or the automatic Gate failed, A0 would have preserved
the failing evidence, kept Sage disabled, and stopped without switching modes
or retrying. The next candidate question is human visual review of the fixed
package. A future additional stack component requires a separate Issue,
contract, and approval; A1 was not started.

## Validation and repository evidence

Thirteen focused model-free tests passed in 0.060 seconds. They cover plan
purity, immutable provenance, output contracts, exact metric thresholds,
diagnostic-only SSIM semantics, decision boundaries, public sanitization, and
private review selection. Two earlier sandboxed test invocations were blocked
by temporary-directory ACLs before executing the tests; the identical suite
then passed in the approved unrestricted process. No full Python suite, Rust
build/test, model validation, Generation, CUDA run, or performance benchmark
was repeated.

Configuration parsing, Python compilation, YAML/JSON parsing, focused result
validation, `git diff --check`, relative-link, secret, absolute-path, and
binary-tracking checks are the publication checks. Public records contain no
prompt, credential, user identifier, private local path, model binary, media,
or full runtime log.

Diagram impact: `updated`. A0 adds a bounded optional external attention
component and human-review Gate to the evidence state. It does not change the
solid Full Compute product flow.
