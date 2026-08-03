# M1-A2 Protocol Revision Decision

Current decision: **ORACLE_PROTOCOL_REVISE**

The previous **RIGHTS_REVIEW_BLOCKED** decision is preserved in
`admission-report.json` as the decision produced before the claim-boundary
correction. It is not deleted or rewritten. The current decision supersedes it
for future work because visible pixel change and human-reviewed movement boxes
do not establish backend compute relevance or safe skip.

Official current counts:

- investigated clips: 12;
- phase-one rights/scene/privacy review: 12/12;
- deterministic derivatives: 12;
- safe-skip truth: 0;
- verified compute-relevance Oracles: 0;
- eligible backend selective-compute results: 0.

The Guided Oracle exports are auxiliary observed-change evidence and
human-reviewed-or-partially-reviewed. They are not compute-relevance truth,
safe-skip truth, or eligible backend skip evidence. Blind re-review,
adjudication, and final verified-Oracle promotion under that superseded
protocol are stopped.

This is a metadata/protocol Gate only. It is not topology performance, generation quality, speedup, GPU savings, product evidence, or M1 completion.

No model was downloaded or loaded; CUDA, paid services, backend integration, and external personal-data transfer were not used.
