# HIVEFRAME M0 다른 PC 인수인계서

작성 기준일: 2026-07-30  
현재 단계: **M0 — Reproducible Baseline**  
현재 브랜치: `agent/m0-baseline-runner`  
검증 완료된 M0 상태의 필수 조상 커밋:
`943deb5072fab2014bbc194b94f23b63725b42e8`

이 문서는 다른 Windows PC의 WSL2 Ubuntu 환경에서 현재 HIVEFRAME M0
상태를 그대로 이어가기 위한 인수인계서다. Patch Scheduler, Boundary Bus,
Temporal Cache, LoRA, 분산 실행, GUI는 현재 범위가 아니다.

## 1. 현재 완료 상태

완료된 항목:

- HIVEFRAME 초기 저장소, 문서, M0 실행기 및 receipt 구조
- RTX 3060 12GB가 연결된 WSL2 Ubuntu 24.04 실행 환경 검증
- Python 3.10.20 전용 환경
- PyTorch 2.4.1+cu124, TorchVision 0.19.1+cu124
- FlashAttention 2.7.4.post1 BF16 실제 연산 검증
- 공식 Wan 2.1 코드 revision 고정
- 공식 Wan 2.1 T2V 1.3B checkpoint 다운로드 및 전체 파일 검증
- offline M0 preflight `ready=true`, blocker 0개
- 모델 없는 M0 단위 테스트 10개 통과

아직 실행하지 않은 항목:

- smoke 영상 생성
- cold/warm baseline
- 동일 seed 재현성 검사
- canonical 10-prompt benchmark
- 모델 변환, 양자화 또는 설정 완화

따라서 새 PC에서도 첫 GPU 작업은 별도 승인 후 실행하는 smoke test다.

## 2. 고정된 구성요소

| 항목 | 고정값 |
|---|---|
| HIVEFRAME 필수 조상 commit | `943deb5072fab2014bbc194b94f23b63725b42e8` |
| Wan 공식 코드 | `Wan-Video/Wan2.1` |
| Wan 코드 revision | `9737cba9c1c3c4d04b33fcad41c111989865d315` |
| Checkpoint | `Wan-AI/Wan2.1-T2V-1.3B` |
| Checkpoint revision | `37ec512624d61f7aa208f7ea8140a131f93afc9a` |
| Checkpoint payload | `17,573,837,064` bytes, 22 files |
| Python | 3.10.20 |
| PyTorch | 2.4.1+cu124 |
| TorchVision | 0.19.1+cu124 |
| FlashAttention | 2.7.4.post1 |
| 권장 dtype | BF16 |
| 권장 실행 옵션 | model CPU offload, T5 on CPU |

다른 checkpoint, mutable `main`, Diffusers 변환판, 양자화판 또는 제3자
재배포 모델로 대체하면 이 인수인계의 재현성 범위를 벗어난다.

## 3. 새 PC 최소 조건

- Windows 11 또는 WSL2를 정상 지원하는 Windows
- BIOS/UEFI 가상화 활성화
- WSL2와 Ubuntu 24.04
- NVIDIA Ampere 이상 GPU
- 실용 최소 VRAM 12GB, 권장 24GB
- 시스템 RAM 최소 32GB, 권장 64GB
- WSL Linux 파일시스템 여유 공간 최소 47GB, 권장 60GB 이상
- Windows용 NVIDIA 드라이버가 WSL CUDA를 지원해야 함

CUDA Toolkit 전체 설치는 기본 요구사항이 아니다. 현재 환경은 PyTorch
CUDA runtime과 공식 FlashAttention wheel만 사용하며 `nvcc` 없이
검증됐다.

## 4. 무엇을 옮겨야 하는가

반드시 별도로 옮길 항목:

1. HIVEFRAME Git 저장소와 로컬 커밋
2. 공식 Wan 코드 checkout
3. 17.57GB checkpoint 디렉터리
4. Python 환경을 재구축할 경우 package lock
5. 필요하면 `/home/ksse2/hiveframe-m0-state`의 로컬 preflight 기록

현재 최신 커밋은 GitHub에 push되지 않았다. GitHub에서 단순 clone하면
`943deb5`가 없을 수 있으므로, push가 승인되기 전에는 Git bundle 또는
전체 WSL 배포판 이동을 사용한다.

## 5. 권장 이동 방식 A — Git bundle + 모델 tar

이 방식은 새 PC에서 환경을 깨끗하게 다시 검증할 수 있어 권장한다.

### 5.1 기존 PC에서 HIVEFRAME Git bundle 만들기

Windows PowerShell 예시:

```powershell
New-Item -ItemType Directory -Force D:\HIVEFRAME-HANDOFF
git -C "C:\Users\ksse2\Documents\Codex\2026-07-30\referenced-chatgpt-conversation-this-is-untrusted-2\outputs\HIVEFRAME" `
  bundle create D:\HIVEFRAME-HANDOFF\HIVEFRAME-handoff.bundle `
  agent/m0-baseline-runner
git -C "C:\Users\ksse2\Documents\Codex\2026-07-30\referenced-chatgpt-conversation-this-is-untrusted-2\outputs\HIVEFRAME" `
  bundle verify D:\HIVEFRAME-HANDOFF\HIVEFRAME-handoff.bundle
```

### 5.2 기존 PC에서 모델과 Wan 코드를 묶기

Ubuntu에서:

```bash
tar -C /home/ksse2/ai/models \
  -cf /mnt/d/HIVEFRAME-HANDOFF/Wan2.1-T2V-1.3B.tar \
  Wan2.1-T2V-1.3B

tar -C /home/ksse2/src \
  -cf /mnt/d/HIVEFRAME-HANDOFF/Wan2.1-code-9737cba.tar \
  Wan2.1
```

외장 저장장치에는 bundle과 tar 두 개를 합쳐 약 18GB 이상의 여유가
필요하다. 복사 중 손상을 검출하려면 기존 PC에서 전달 파일 자체의
SHA-256도 별도로 기록한다.

```bash
sha256sum \
  /mnt/d/HIVEFRAME-HANDOFF/HIVEFRAME-handoff.bundle \
  /mnt/d/HIVEFRAME-HANDOFF/Wan2.1-T2V-1.3B.tar \
  /mnt/d/HIVEFRAME-HANDOFF/Wan2.1-code-9737cba.tar
```

### 5.3 새 PC에서 저장소 복원

새 PC의 Ubuntu에서:

```bash
mkdir -p ~/src
git clone \
  -b agent/m0-baseline-runner \
  /mnt/d/HIVEFRAME-HANDOFF/HIVEFRAME-handoff.bundle \
  ~/src/HIVEFRAME

git -C ~/src/HIVEFRAME rev-parse HEAD
git -C ~/src/HIVEFRAME merge-base --is-ancestor \
  943deb5072fab2014bbc194b94f23b63725b42e8 HEAD
git -C ~/src/HIVEFRAME status --short
test -f ~/src/HIVEFRAME/docs/M0_OTHER_PC_HANDOFF_KO.md
```

`merge-base --is-ancestor`와 `test`는 종료 코드 0이어야 하며, status는
비어 있어야 한다. 인수인계 문서를 추가한 커밋 때문에 HEAD는
`943deb5`보다 새 값인 것이 정상이다.

### 5.4 새 PC Linux 파일시스템에 모델과 Wan 코드 복원

```bash
mkdir -p ~/ai/models ~/ai/cache/huggingface ~/src
tar -xf /mnt/d/HIVEFRAME-HANDOFF/Wan2.1-T2V-1.3B.tar \
  -C ~/ai/models
tar -xf /mnt/d/HIVEFRAME-HANDOFF/Wan2.1-code-9737cba.tar \
  -C ~/src
```

모델과 캐시는 `/mnt/c` 또는 `/mnt/d`에서 직접 실행하지 말고 WSL ext4
내부에 둔다. Windows 마운트 경로는 많은 파일과 대형 weight 로딩에서
성능이 불리할 수 있다.

## 6. 대안 이동 방식 B — WSL 배포판 전체 export/import

동일한 Python 환경과 모델까지 한 번에 옮기려면 기존 PC의 Windows
PowerShell에서:

```powershell
wsl --shutdown
wsl --export Ubuntu-24.04 D:\HIVEFRAME-HANDOFF\Ubuntu-24.04-HIVEFRAME.tar
```

새 PC에서:

```powershell
wsl --import HIVEFRAME-Ubuntu C:\WSL\HIVEFRAME `
  D:\HIVEFRAME-HANDOFF\Ubuntu-24.04-HIVEFRAME.tar `
  --version 2
wsl -d HIVEFRAME-Ubuntu -u ksse2
```

이 방식은 빠르지만 기존 Ubuntu 사용자 파일과 캐시를 함께 전달한다.
export 파일을 제3자에게 넘기기 전에는 SSH 키, shell history, 토큰,
환경변수 등 개인 정보가 포함됐는지 확인해야 한다. 새 PC의 NVIDIA
Windows 드라이버와 WSL GPU 연결은 별도로 다시 검증해야 한다.

## 7. 새 PC에 환경을 새로 구축하는 경우

Ubuntu 24.04 기본 Python은 그대로 두고 별도 Python 3.10.20을 사용한다.
CPython 공식 source SHA-256:

```text
de6517421601e39a9a3bc3e1bc4c7b2f239297423ee05e282598c83ec0647505
```

전용 환경의 목표 경로:

```text
~/.local/python-3.10.20
~/.venvs/hiveframe-m0
```

Python 환경 생성 후:

```bash
~/.local/python-3.10.20/bin/python3.10 \
  -m venv ~/.venvs/hiveframe-m0
source ~/.venvs/hiveframe-m0/bin/activate

python -m pip install \
  torch==2.4.1 torchvision==0.19.1 \
  --index-url https://download.pytorch.org/whl/cu124

python -m pip install \
  --extra-index-url https://download.pytorch.org/whl/cu124 \
  -r ~/src/HIVEFRAME/python/requirements-m0.wsl2.lock.txt

python -m pip check
```

정확한 package lock은
`python/requirements-m0.wsl2.lock.txt`를 사용한다. FlashAttention
wheel은 Python 3.10, CUDA 12, PyTorch 2.4, Linux x86-64 조합으로
고정돼 있다.

## 8. 새 PC GPU 및 패키지 검증

```bash
nvidia-smi
source ~/.venvs/hiveframe-m0/bin/activate

python -c "import torch; \
print(torch.__version__, torch.version.cuda); \
print(torch.cuda.is_available()); \
print(torch.cuda.get_device_name(0)); \
print(torch.cuda.get_device_capability(0)); \
print(torch.cuda.get_device_properties(0).total_memory); \
print(torch.cuda.is_bf16_supported())"

python -c "import torchvision, diffusers, transformers, accelerate, flash_attn; \
print(torchvision.__version__); \
print(diffusers.__version__); \
print(transformers.__version__); \
print(accelerate.__version__); \
print(flash_attn.__version__)"
```

필수 기대값:

- `torch.cuda.is_available()` → `True`
- GPU 이름 → 새 PC의 NVIDIA GPU
- PyTorch CUDA → `12.4`
- BF16 지원 → Ampere 이상이면 `True`
- TorchVision → `0.19.1+cu124`
- FlashAttention → `2.7.4.post1`

하나라도 다르면 checkpoint를 로드하지 말고 환경 차이를 먼저 기록한다.

## 9. 코드와 checkpoint 검증

### 9.1 Wan 코드

```bash
git -C ~/src/Wan2.1 rev-parse HEAD
git -C ~/src/Wan2.1 status --short
```

HEAD는 다음 값이어야 하며 status는 비어 있어야 한다.

```text
9737cba9c1c3c4d04b33fcad41c111989865d315
```

### 9.2 전체 checkpoint SHA-256

```bash
cd ~/ai/models/Wan2.1-T2V-1.3B
sha256sum -c \
  ~/src/HIVEFRAME/data_ledger/models/wan21_t2v_1_3b_37ec512.sha256
```

22개 항목이 모두 `OK`여야 한다. 파일별 크기와 hash 목록은
`data_ledger/models/wan21_t2v_1_3b_37ec512.files.tsv`에 있다.

다음 대형 파일도 반드시 일치해야 한다.

| 파일 | Bytes | SHA-256 |
|---|---:|---|
| `Wan2.1_VAE.pth` | 507,609,880 | `38071ab59bd94681c686fa51d75a1968f64e470262043be31f7a094e442fd981` |
| `diffusion_pytorch_model.safetensors` | 5,676,070,424 | `96b6b242ca1c2f24e9d02cd6596066fab6d310e2d7538f33ae267cb18d957e8f` |
| `models_t5_umt5-xxl-enc-bf16.pth` | 11,361,920,418 | `7cace0da2b446bbbbc57d031ab6cf163a3d59b366da94e5afe36745b746fd81d` |

## 10. 새 PC 경로 설정

새 PC의 Linux 사용자명이 달라도 환경변수만 바꾸면 된다.

```bash
export HIVEFRAME_ROOT="$HOME/src/HIVEFRAME"
export PYTHONPATH="$HIVEFRAME_ROOT/python"
export HIVEFRAME_WAN_CODE_DIR="$HOME/src/Wan2.1"
export HIVEFRAME_MODEL_DIR="$HOME/ai/models/Wan2.1-T2V-1.3B"
export HIVEFRAME_HF_CACHE_DIR="$HOME/ai/cache/huggingface"
export HIVEFRAME_M0_REPORT_DIR="$HOME/hiveframe-m0-state"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

mkdir -p "$HIVEFRAME_HF_CACHE_DIR" "$HIVEFRAME_M0_REPORT_DIR"
cd "$HIVEFRAME_ROOT"
```

checkpoint가 이미 복사됐다면 새 PC 검증 중에는 offline 변수를 유지한다.
Hugging Face에서 자동으로 다른 revision을 받도록 허용하지 않는다.

## 11. M0 인수 확인 명령

```bash
source ~/.venvs/hiveframe-m0/bin/activate
cd "$HIVEFRAME_ROOT"

python -m unittest discover -s python/tests -v
python hiveframe_m0.py verify-model --full
python hiveframe_m0.py preflight \
  --output "$HIVEFRAME_M0_REPORT_DIR/preflight.handoff.json"
```

인수 성공 조건:

- 단위 테스트 10개 통과
- `verify-model --full`의 세 key file size/hash 일치
- preflight `ready=true`
- `blockers=[]`
- `warnings=[]` 또는 새 PC 환경 차이가 명확하게 설명된 warning만 존재
- HIVEFRAME와 Wan Git revision 일치
- 모델 파일이 HIVEFRAME Git 저장소 밖에 있음

## 12. 다음 작업과 금지선

인수 직후 자동으로 다음 명령을 실행하지 않는다.

```bash
python hiveframe_m0.py smoke
python hiveframe_m0.py run --profile smoke-cold-warm --prompt-id static-speaking-person --plan
python hiveframe_m0.py run --profile smoke-cold-warm --prompt-id static-speaking-person --expect-settings-hash SETTINGS_HASH_FROM_PLAN
python hiveframe_m0.py run-suite
```

다음 순서를 별도 승인 후 지킨다.

1. 832x480, 17프레임, 4 steps smoke
2. cold 실행
3. 같은 프로세스의 warm 실행
4. 동일 seed output hash 재현성 판정
5. 앞선 gate가 모두 통과한 경우에만 canonical 10-prompt suite

설정 변경, 프레임 축소, 양자화 또는 다른 모델로 성공 판정을 우회하지
않는다. RTX 3060 12GB에서는 BF16, model CPU offload, T5 CPU 설정을
유지한다.

## 13. 핵심 기록 위치

| 기록 | 저장소 내 경로 |
|---|---|
| 현재 다운로드 receipt | `data_ledger/downloads/wan21_t2v_1_3b_37ec512.json` |
| 전체 SHA-256 manifest | `data_ledger/models/wan21_t2v_1_3b_37ec512.sha256` |
| 파일별 크기와 SHA | `data_ledger/models/wan21_t2v_1_3b_37ec512.files.tsv` |
| 모델 라이선스 ledger | `data_ledger/models/wan21_t2v_1_3b.json` |
| 검증된 Python lock | `python/requirements-m0.wsl2.lock.txt` |
| WSL 환경 fingerprint | `data_ledger/environments/wsl2_ubuntu2404_rtx3060_m0.json` |
| M0 실행 안내 | `docs/M0_BASELINE.md` |
| CUDA host 안내 | `docs/M0_CUDA_HOST_HANDOFF.md` |

`docs/M0_WSL2_RTX3060_SETUP.md`는 checkpoint 다운로드 전 환경 검증
시점의 기록이다. 다운로드 완료 상태는 최신 download receipt가
우선한다.

## 14. 인수 완료 체크리스트

- [ ] `943deb5072fab2014bbc194b94f23b63725b42e8`가 Git HEAD의 조상임
- [ ] Git worktree가 깨끗함
- [ ] WSL2 Ubuntu 24.04
- [ ] NVIDIA GPU와 VRAM 인식
- [ ] PyTorch CUDA 12.4와 BF16 확인
- [ ] FlashAttention import 및 최소 BF16 연산 통과
- [ ] Wan 코드 revision 일치
- [ ] checkpoint 22개 SHA-256 전부 일치
- [ ] 모델이 Git 저장소 외부에 있음
- [ ] offline preflight `ready=true`
- [ ] blocker 0개
- [ ] smoke는 별도 승인 전 미실행
