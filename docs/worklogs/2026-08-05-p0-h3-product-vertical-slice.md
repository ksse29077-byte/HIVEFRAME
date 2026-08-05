# P0 — MiniMax H3 Product Vertical Slice

Date: 2026-08-05

Issue: [#53](https://github.com/ksse29077-byte/HIVEFRAME/issues/53)

Branch: `product/p0-h3-vertical-slice`

Source main: `4ddb6a5c7e47b776c9904d32e33c85a63b4ad526`

Decision: `P0_VERTICAL_SLICE_READY` for Draft review

## Product question and bounded scope

Can a user create one 3–8 second, one-person generation request on one local
screen, see backend job state, save/download a result, and record
accept/reject/retry feedback?

The maximum scope was one `standard` profile, one offline Mock H3 path, one
manual retry, SQLite metadata, external local artifacts, and one web screen.
The maximum correction budget was one bounded implementation correction. The
exit condition was one passing focused test invocation covering the core flow,
fallback, and release-blocking safety boundaries. Failure fallback was an
explicit failed job plus at most one manual retry; a live H3 failure cannot
silently fall through because live mode is disabled.

## Implemented

- a Python standard-library HTTP server bound to loopback only;
- plain local HTML/CSS/JavaScript with no remote assets or build step;
- prompt, optional PNG/JPEG/WebP reference image, duration, generation
  consent, and separated backend-transfer consent;
- persisted job states `queued`, `running`, `succeeded`, and `failed`;
- required job identifiers, timestamps, backend/model contract, provider job
  ID, errors, output asset, receipt, profile, and retry count in SQLite;
- deterministic `MockH3Backend` success, timeout, rate-limit, provider-failure,
  and no-result fixtures without network access;
- `MiniMaxH3Backend` interface with `create_job`, `get_job_status`,
  `get_result`, unsupported cancellation, normalized errors, and receipts;
- result and receipt files created exclusively under a configurable external
  artifact root; the Mock result explicitly states that no video or network
  call occurred;
- feedback decisions `accepted`, `rejected`, and `retry_requested`, including
  the seven bounded rejection reasons;
- distinct generation consent, training opt-in, training eligibility,
  deletion request, and retention status;
- maximum one manual retry and no automatic retry loop;
- P0 placeholder structures for terms, AUP, privacy, backend transfer,
  training opt-in, retention, and deletion. They are explicitly not legal
  text.

The MiniMax policy state is recorded exactly as:

```text
excluded_territory_authorization = verified_private_evidence
commercial_product_use = authorized_with_conditions
safeguards_required = true
end_user_flow_down_required = true
output_training_rights = unknown_pending_written_confirmation
```

Training eligibility defaults to `evaluation_only`. An opt-in remains
`preference_only` while output training rights are unknown. A deletion request
becomes `quarantined` with `pending_deletion`. `training_allowed` requires both
explicit user opt-in and separately confirmed written output rights; P0 never
asserts those rights.

## Run locally

Use Python 3.10 or newer. No package installation is required.

```bash
PYTHONPATH=python python hiveframe_product.py \
  --host 127.0.0.1 \
  --port 8765 \
  --artifact-root <external-artifact-root>
```

Open `http://127.0.0.1:8765`. Enter a prompt, optionally select a supported
reference image, choose 3, 5, or 8 seconds, accept local generation/storage,
and create the Mock request. The result panel exposes a download after success.
Use the final panel to accept, reject with a reason, request one retry, opt in
to future training separately, or request deletion.

If `--artifact-root` is omitted, the service uses the operating system's local
application-data directory outside the repository. `HIVEFRAME_ARTIFACT_ROOT`
may set another external path. A path inside the Git repository is rejected.

## Focused validation

The same focused command was used at two distinct code checkpoints:

```bash
PYTHONPATH=python python3 -m unittest python/tests/test_product_vertical_slice.py
```

The initial development checkpoint passed 5 tests in 1.743 seconds. Product
code then changed to enforce feedback/job-state compatibility and to extend
missing-key and artifact-save fallback coverage. The final invocation passed
5 tests in 1.960 seconds. This was the single bounded correction, not a repeat
against unchanged code.

| Check | Result |
|---|---|
| focused job/feedback/training/error contracts | passed |
| server start, UI access, Mock job create smoke | passed |
| prompt → Mock success → saved/downloaded result → feedback E2E | passed |
| provider failure → partial receipt → one manual retry only | passed |
| API-key persistence, traversal upload, external artifact boundary | passed |

The test created only temporary external artifacts. It performed no network,
model, GPU, provider, or paid operation.

## Skipped validation and evidence reuse

```text
status: skipped
reason: not release-blocking
evidence: the existing Python/Rust research and M0/M1 surfaces were unchanged
```

The full Python suite, full Rust suite, M0/model checks, B0 measurements,
benchmarks, and repeated input/hash validation were not rerun. PR #52 merge
commit `4ddb6a5...` and the existing M0/M1 reports remain immutable evidence.
The first documentation commit for this task is `c430daf`; the product evidence
commit is the commit introducing this worklog and is identified by branch/PR
Git history after publication.

## Security, rights, and failure boundaries

- live H3 mode defaults to false and P0 contains no HTTP provider transport;
- `MINIMAX_API_KEY` is read only as an environment-presence check by the
  disabled contract shell and is never written to source, configuration, log,
  SQLite, artifact, or receipt;
- the local server binds only to loopback and sends a restrictive CSP;
- prompt and request size are bounded, database statements are parameterized,
  and reference filenames reject traversal and unsupported suffixes;
- artifact creation is exclusive and cannot overwrite an existing user file;
- user content and product artifacts remain outside Git;
- no external user-content transfer occurs in Mock mode;
- no infinite retry exists; `max_retry=1` and retry is manual;
- provider timeout, rate limit, provider failure, missing result, disabled live
  mode, missing key, bad input, and artifact-save failure have explicit error
  semantics.

## Known limitations

- The result is a deterministic JSON Mock artifact, not a generated MP4.
- The MiniMax H3 adapter is a contract shell; official endpoint names,
  request/response fields, cancellation, pricing, and policy must be rechecked
  in P1 before a live call.
- There is no authentication, payment, cloud deployment, admin surface, or
  multi-user isolation.
- Deletion requests are recorded but not executed automatically in P0.
- Terms, AUP, privacy, and consent copy are UI structure placeholders, not
  legal documents.
- SQLite is suitable only for the local single-user vertical slice.
- No selective-compute, speed, GPU-work, or VRAM benefit is claimed.

## Operation counts and next product work

Live H3 API calls: 0. API keys used by the product: 0. Paid calls: 0. Model
downloads: 0. Model loads: 0. CUDA runs: 0. Backend research runs: 0. M1-B1/B2
runs: 0. External personal-data transfers: 0.

Next is separately approved **P1 — Live MiniMax H3 Integration**: recheck the
official API and terms, require an environment-only key, establish an explicit
cost cap and live-call count, require backend-transfer consent, and perform one
bounded live admission. Do not start it automatically.
