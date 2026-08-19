# H3 Row/Region Safety Evidence CONTROL Retry

Date: 2026-08-19  
Issue: pending GitHub authentication  
Draft PR: pending GitHub authentication  
Branch: `codex/h3-row-region-safety-evidence-control-retry`  
Base: `8455f479cf2a26dd301a2b0a27cfee5fa2474758` (Draft PR #103 head)  
Implementation commit: `e590f91cf1181e8993e24c96b2d9d44e5fa118ed`  
Decision: `H3_ROW_REGION_TRANSFER_BUDGET_FAILED`

## 1. Exception and Scope

The user granted a one-time constitution exception for
`H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_RETRY`, covering Articles 7, 13,
16.1, and 28. It authorized ownership checks and normal shutdown of one idle
HIVEFRAME ComfyUI runtime, one dedicated Full Compute H3 CONTROL, at most 640
bounded evidence records, one generation-batched Rust CachePlan ABI V2 call,
model-free replay, and isolated GitHub work.

SELECTIVE, partial-Q, retries after submission, automatic Standard reruns,
threshold changes, product UI/backend, LTX, Wan, installer, ROADMAP, TASKS,
and changes to PRs #91/#95/#97/#99/#101/#103 were prohibited. No prohibited
work ran. The exception ended after the single CONTROL failed.

## 2. Start State and Runtime Ownership

Draft PR #103 local and remote heads both matched `8455f47...` and its
worktree was clean. The dedicated retry branch and worktree were created from
that exact head. GitHub CLI authentication was invalid and the in-app browser
was logged out, so Issue and Draft PR creation remain pending authentication.
The implementation branch itself was pushed successfully.

The pre-existing loopback ComfyUI queue reported running 0 and pending 0. Port
8188 belonged to PID 34616 under the same login session and HIVEFRAME P1-A1
runtime path; PID 29364 was its same-session launcher. The user stated the
video work was complete and authorized normal shutdown after ownership and
queue checks. Only those two verified PIDs were stopped. Foreign job
termination count is zero.

After shutdown, port 8188 was free and GPU state was 10 MiB used, 12,104 MiB
free, and 0% utilization. Available host RAM was 46,671,405,056 bytes and free
disk was 587,948,924,928 bytes. The dedicated CONTROL used port 8191 and was
stopped by its owning runner after failure.

## 3. Frozen CONTROL Profile

- H3 I2V, Standard Full Compute only;
- P1-A2 Standard I2V prompt selected by exact database predicates, digest
  `080156aaa4e5c9369bf2a91d9676d973cabed1a354f008c061b25ec36a50cede`;
- P1-A2 input image digest
  `493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411`;
- installed H3 source digest
  `882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024`;
- installed Attention source digest
  `a540a0b487eb5979c4dbc38c72926e3a38b5e41480a038a98707e2eef7e038d9`;
- approved workflow digest
  `31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6`;
- seed 101, 864x480, 124 frames, 24 FPS, 20 steps, simple scheduler,
  res_multistep sampler, denoise 1.0, Sage disabled;
- external API calls 0, retry 0, job-level fallback 0.

The API graph added only the frozen P1-A2 `LoadImage` first-frame edge and the
repository-owned observation sampler. It retained the Standard H3 model,
conditioning, Full Attention, output projection, MLP, VAE, audio, and encode
path.

## 4. Evidence Design

The design admitted 40 fixed `(block, region)` keys across 34 blocks. Region
0 covered blocks 0 through 31 plus blocks 48 and 49; all four regions were
retained for blocks 48 and 49 so the known risk blocks could not escape
regional observation. Sixteen age-one source intervals bounded the theoretical
record count at exactly 640.

The BF16 pinned-host payload was 1,889,398,784 bytes, below the 2 GiB cap.
Q/K/V and full Attention tensors were never sent to Rust. Regional metric
accumulation ran on GPU and the partial failure receipt used one compact scalar
D2H transfer of 12,276 bytes. The CONTROL never replaced the Full Attention
output and never called partial Attention.

## 5. Pre-Generation Verification

The new seven-test row/region suite passed, including the exact 640-record and
1,889,398,784-byte bounds, P1-A2 prompt selection, scalar ABI layout, overflow
fail-open behavior, real PyO3 3% fixture, and deterministic replay. Existing
G1D tests passed 22/22 and CachePlan ABI V2 Python/PyO3 tests passed 8/8.
The Rust cache-plan subset passed 12/12. Source admission, workflow digest,
input digest, clean ports, clean queue, VRAM, RAM, disk, branch, and remote
head checks passed before submission.

Two runner invocations stopped before ComfyUI launch and before submission:
one private-directory permission rejection and one obsolete prompt-cardinality
precondition. They are not job retries. The P1-A2 prompt selector was narrowed
to the unique successful Standard I2V job with a reference asset. The official
CONTROL lifecycle below contains the only workflow submission.

## 6. Official CONTROL Lifecycle

| Counter | Value |
|---|---:|
| CONTROL submission | 1 |
| CONTROL GPU execution started | 1 |
| CONTROL completed generation | 0 |
| Retry | 0 |
| Job-level fallback | 0 |
| SELECTIVE execution | 0 |
| Partial-Q execution | 0 |
| External API calls | 0 |
| Foreign job termination | 0 |

The sampler reached 17 model forwards and 850 exact Full Attention block
calls. Partial Attention calls remained zero. The transfer hard cap rejected
the next observation transfer and raised `EvidenceBudgetError`; the job ended
without a SaveVideo artifact. ComfyUI reported 507.15 seconds for the failed
prompt lifecycle. This is not a completed-generation or performance baseline.

## 7. Cache and Transfer Failure

| Metric at stop | Bytes |
|---|---:|
| Host cache | 1,889,398,784 |
| D2H observation payload | 30,057,990,144 |
| H2D observation payload | 12,856,610,816 |
| Total actual observation transfer | 42,914,600,960 |
| Hard transfer budget | 42,949,672,960 |
| Remaining before rejected transfer | 35,072,000 |

The host-cache cap passed. The completed transfers remained just below 40
GiB, but the next required region payload could not fit. The collector stopped
instead of truncating or using a partial batch. The run therefore fails the
full-generation transfer-budget Gate.

## 8. Partial Diagnostic Evidence

The failure callback contains 279 materialized regional records from the
incomplete run. They are diagnostic only and were not used for admission,
planned reduction, Rust compilation, or replay. The partial confusion matrix
contains 19 false-safe and 45 false-unsafe observations; false-unsafe status
was collected. The 19 false-safe observations independently violate the fixed
zero-false-safe Gate. Thresholds were not relaxed.

Because the run stopped at 17/20, no `GenerationEvidenceBatch` was admitted.
Rust CachePlan ABI V2 generation compile count is zero and deterministic replay
count is zero. Planned Q reduction is unverified, not zero. No selected cache
plan, eviction order, or promotion claim exists.

## 9. Output Integrity

No MP4 reached `SaveVideo`, so output integrity is `NOT_EXECUTED`. Decoded
frames, codec, FPS, audio, black-frame count, corrupted-frame count, and file
size are unavailable. No partial media was promoted or committed.

## 10. Evidence Integrity and Runner Defect

The private callback receipt is preserved outside Git with SHA-256
`2baf0159f08a4b5e6a07e1f01db2e94160c26c4ee8d120efab7c0c7ae28a5dda`.
The runtime log SHA-256 is
`f78866de400aabe327f21eec22b36af654018cfebff5309de1c37796ff5f4399`.
Neither private path, prompt text, input image, model, output, nor raw tensor is
tracked by Git.

After the runtime had already failed and stopped, the runner's top-level
summary writer called `measured()` without its required `scope` argument.
That prevented creation of the redundant private/public runner summary but did
not alter the preserved node callback or runtime log. The failure-path writer
was corrected without another Generation and now maps
`EvidenceBudgetError` to `H3_ROW_REGION_TRANSFER_BUDGET_FAILED`.

## 11. Decision

Final decision: `H3_ROW_REGION_TRANSFER_BUDGET_FAILED`.

The CONTROL did not complete, the actual schedule exceeded the fixed transfer
design before the final three steps, partial diagnostic evidence contained
false-safe observations, Rust replay did not run, planned Q reduction is
unverified, and output integrity was not executed. Therefore
`H3_ROW_REGION_SAFETY_EVIDENCE_READY_FOR_SELECTIVE_GPU_PROOF` is not claimed.

No automatic follow-up, additional CONTROL, SELECTIVE, partial-Q, threshold
change, product integration, LTX, Wan, or installer work was started. A future
attempt requires a separate constitution conflict review and explicit user
approval. Diagram impact: none; the new path remains research-only and failed.
