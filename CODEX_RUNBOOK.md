# Codex Runbook — HIVEFRAME

## 1. Repository orientation

```powershell
git status -sb
git rev-parse HEAD
git branch --show-current
git remote -v
git worktree list
git log --oneline --decorate -12
```

Stop before mutation if the branch, HEAD, or dirty state differs from the
handoff record and the difference is unexplained.

## 2. Model-free verification

In WSL or another Python environment with NumPy:

```bash
PYTHONPATH=python python -m compileall -q python
PYTHONPATH=python python -m unittest discover -s python/tests
```

Rust and diff checks:

```powershell
cargo check --workspace --locked
git diff --check
```

Expected test count at RFC commit `041311b...`: 59. A later count may be higher;
never treat a lower count as acceptable without explaining which tests moved.

## 3. Compound-eye reference probe

Use a new or empty output directory:

```bash
PYTHONPATH=python python -W error -m hive_probes.compound_eye_v0 \
  --seed 101 \
  --output-dir /tmp/hiveframe-eye-v0
```

Expected artifacts:

- `eye_contracts.json`
- `eye_observations.json`
- `shared_visual_state.json`
- `compute_plan.json`
- `observation_receipt.json`

The probe must report no model load and no CUDA use. It cannot satisfy an M0
backend gate.

## 4. M0 read-only/preflight commands

Set the approved external paths for the current machine before using M0:

```bash
export HIVEFRAME_WAN_CODE_DIR=/home/ksse2/src/Wan2.1
export HIVEFRAME_MODEL_DIR=/home/ksse2/ai/models/Wan2.1-T2V-1.3B
export HIVEFRAME_HF_CACHE_DIR=/home/ksse2/ai/cache/huggingface
export HIVEFRAME_M0_REPORT_DIR=/home/ksse2/hiveframe-m0-state
```

Model-free checks:

```bash
python hiveframe_m0.py preflight
python hiveframe_m0.py smoke --run-id UNIQUE_ID --plan
python hiveframe_m0.py run \
  --profile baseline-memory-admission \
  --prompt-id static-speaking-person \
  --output-dir UNIQUE_OUTPUT_DIR \
  --plan
```

Do not execute the returned plan unless the user separately authorizes the
exact GPU run and settings hash.

## 5. Git publication

Publication changes external state and requires approval for the exact target.
Verify first:

```powershell
git status -sb
git log -1 --oneline
git remote get-url origin
git push --dry-run origin agent/compound-eye-architecture-v1
git push --dry-run origin pre-compound-eye-v1
```

Only after explicit approval:

```powershell
git push -u origin agent/compound-eye-architecture-v1
git push origin pre-compound-eye-v1
```

Then create the RFC Issue and a draft PR. Record their URLs, base/head branches,
CI state, and review state in `docs/WORKLOG.md`.

## 6. Failure handling

- Do not retry a failed GPU run unless explicitly authorized.
- Do not lower frames, steps, resolution, dtype, or safety thresholds to turn
  an admission failure into success.
- Preserve partial receipts and complete logs.
- Mark external-authentication failures as `blocked`, not completed.
- Mark unsupported backend selectors as `unsupported`, not emulated success.
