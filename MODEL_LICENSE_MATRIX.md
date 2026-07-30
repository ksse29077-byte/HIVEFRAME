# Model and License Matrix

> This is an admission checklist, not legal advice. Verify each checkpoint's original model card, repository license, weight terms, acceptable-use restrictions, and transitive components again at implementation time. Do not infer that repository code terms automatically govern weights.

| Backend / asset | Intended role | Reported upstream status to verify | Admission status | Required evidence |
|---|---|---|---|---|
| Wan 2.1 T2V 1.3B | M0 primary baseline | Official code and model are Apache-2.0 | Verified for research baseline; download not approved | Model `37ec512624d61f7aa208f7ea8140a131f93afc9a`; code `9737cba9c1c3c4d04b33fcad41c111989865d315`; exact large-file sizes and SHA-256 pinned; dependency lock awaits compatible NVIDIA host |
| Wan 2.1 14B family | scale/reference experiments | Official repository reported as Apache-2.0 | Deferred | same evidence plus hardware and redistribution review |
| Wan 2.2 TI2V-5B | 720p/24fps reference path | Official card reported as Apache-2.0 with a 4090-class path | Blocked pending verification | checkpoint-specific license/card; digest; runtime requirements; output restrictions |
| LTX-2 | control and audio-video research | Official repository, inference, and trainer available; commercial terms require explicit review | Blocked pending legal/terms review | exact license version; commercial thresholds/conditions; trainer and weight terms; audio data considerations |
| LoRA / IC-LoRA adapters | minimal targeted training | Derived-artifact terms depend on base model and data | Blocked until training gate | base-model permission; dataset provenance; adapter license; evaluation target |
| Canonical synthetic prompts | internal benchmark | Project-authored text | Allowed after provenance entry | author, revision, intended use |
| Canonical clips | quality and edit benchmark | TBD: synthetic, commissioned, or separately licensed | Blocked until ledger entry | source, rights holder, consent where relevant, permitted transformations, retention |
| YouTube/API-derived media | not a default data source | Downloading, caching, or scraping may violate API/platform policy | Denied by default | explicit policy-compatible acquisition and rights review |
| Creative Commons media | possible evaluation/training input | Rights vary by license; attribution, commercial, and derivative conditions differ | Case-by-case | exact license, attribution, source snapshot, modification permission, compatibility |

## Hard admission gate

A model, adapter, dataset, clip, reference image, or audio asset may enter an experiment only when its ledger entry contains:

- stable source URL and acquisition date;
- exact artifact identifier and cryptographic digest;
- license name, version, and preserved source text;
- allowed research, commercial, modification, and redistribution uses;
- attribution requirements;
- restrictions and acceptable-use obligations;
- provenance and rights holder;
- reviewer and decision date;
- retention and deletion policy;
- downstream outputs or adapters affected by the asset.

Unknown or conflicting terms result in `blocked`, not presumed permission.

## Version pinning

Every receipt must link to:

- backend code revision;
- checkpoint digest;
- model-card snapshot;
- license snapshot;
- Python/CUDA/PyTorch/Diffusers versions;
- adapter revision and training-data ledger IDs, if applicable.

## Data ledger

Use [`data_ledger/README.md`](data_ledger/README.md) for the required record format. Do not commit private data, credentials, personal information, or licensed media binaries to this repository.
