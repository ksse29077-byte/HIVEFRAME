# HIVEFRAME Agent Rules

This file defines repository-local operating rules for Codex and other
automation agents. The Product-First Execution Constitution below is the
single normative copy and has priority over the subordinate repository
safeguards that follow it.

# HIVEFRAME 제품 출시 우선 헌법
# Product-First Execution Constitution

이 헌법은 HIVEFRAME의 모든 Roadmap, RFC, 실험계획,
작업지시문 및 문서 규칙보다 우선합니다.

HIVEFRAME의 최우선 목표는 논문, 백서 또는 완전한 연구 증거를
만드는 것이 아닙니다.

최우선 목표는:

“사용자가 실제로 사용할 수 있는 HIVEFRAME 프로그램을
가장 짧은 시간 안에 출시하고, 실제 사용 결과를 바탕으로 개선하는 것”

입니다.

## 제1조 — 출시 우선

모든 작업은 다음 순서로 판단합니다.

1. 출시 기능을 직접 구현하는가
2. 출시를 막는 기술적 장애를 제거하는가
3. 사용자에게 제공할 실행경로를 완성하는가
4. 실패 시 안전한 fallback을 제공하는가
5. 실제 사용자 피드백을 수집할 수 있게 하는가

위 항목과 직접 관련 없는 연구, 비교, 문서, 실험 및 최적화는
출시 이후로 연기합니다.

완전한 기술 증명을 기다리느라 제품 출시를 지연하지 마십시오.

## 제2조 — 검증 최소화

검증은 기능 출시를 위해 필요한 최소 범위로 제한합니다.

다음 검증만 기본적으로 수행합니다.

- 변경한 코드의 직접 기능검증
- 프로그램이 실행되는지 확인하는 smoke test
- 사용자 핵심 흐름의 end-to-end 확인
- 치명적인 오류와 데이터 손실 가능성 확인
- fallback 작동 확인
- 배포 또는 실행을 차단하는 보안 문제 확인

다음 검증은 필요성이 명확하지 않으면 생략합니다.

- 이미 통과한 전체 테스트의 반복 실행
- 동일 입력·동일 코드·동일 환경의 재측정
- 여러 threshold, tile, worker 조합의 반복 탐색
- 결과에 영향을 주지 않는 문서 정합성 재검사
- 이미 확인된 해시와 환경정보의 반복 수집
- 논문 수준의 통계적 반복
- 출시 결정을 바꾸지 않는 추가 benchmark
- 선택적 dependency 검사
- 장기 일반화를 위한 확장 실험
- 모든 corner case의 사전 검증

## 제3조 — 반복검증 금지

다음 조건이 모두 동일하면 기존 통과 증거를 재사용하고
같은 검증을 반복하지 않습니다.

- 코드 또는 설정이 변경되지 않음
- 입력 데이터가 변경되지 않음
- 실행환경이 변경되지 않음
- 관련 dependency가 변경되지 않음
- 기존 결과에 실패 또는 불확실성이 없음

단지 새로운 PR, commit 또는 작업단계가 시작됐다는 이유만으로
전체 테스트를 다시 실행하지 마십시오.

문서만 변경된 경우:

- 관련 링크
- diff
- 문구 정합성

만 확인하고 Python·Rust 전체 테스트는 기본적으로 생략합니다.

부분 코드만 변경된 경우:

- 변경된 모듈의 focused test
- 핵심 smoke test

만 실행합니다.

전체 테스트는 다음 경우에만 실행합니다.

- 공통 runtime 또는 핵심 계약 변경
- release candidate
- 여러 모듈에 영향을 주는 변경
- 기존 테스트 실패
- 사용자가 명시적으로 요청한 경우

## 제4조 — 기존 증거 재사용

이미 검증된 다음 자료는 immutable evidence로 재사용합니다.

- 입력 파일 SHA-256
- 모델 및 도구 digest
- 환경 fingerprint
- 기존 테스트 결과
- 기존 benchmark
- 권리·동의·개인정보 검토
- Backend capability 조사 결과
- 기존 receipt와 report

변경되지 않은 증거를 새 작업마다 다시 생성하지 마십시오.

기존 증거를 사용할 때는 다음만 기록합니다.

- evidence reference
- 원래 commit 또는 report
- 현재 작업에서 변경되지 않았다는 확인

동일한 내용을 새 문서에 반복 복사하지 마십시오.

## 제5조 — 검증 생략 기준

다음 질문에 모두 “아니오”라면 해당 검증을 생략합니다.

1. 이 검증이 실패하면 출시를 중단해야 하는가?
2. 사용자 데이터 또는 결과물이 손상될 수 있는가?
3. 핵심 기능이 작동하지 않을 가능성이 있는가?
4. 비용이 통제 불가능하게 증가할 수 있는가?
5. 개인정보·저작권·보안 문제가 발생할 수 있는가?
6. fallback이 실패할 가능성이 있는가?
7. 이번 변경이 기존 통과 증거를 무효화하는가?

검증을 생략한 경우 실패가 아니라 다음처럼 기록합니다.

```text
status: skipped
reason: not release-blocking
evidence: existing evidence or not required
```

생략된 검증값을 숫자 0으로 기록하지 마십시오.

## 제6조 — 생략할 수 없는 검증

다음은 출시 속도와 관계없이 생략할 수 없습니다.

- 개인정보 및 사용자 콘텐츠 외부 전송
- 학습 데이터 사용동의와 권리 확인
- 자격증명·API key 노출
- 결제·과금·사용량 폭증 가능성
- 사용자 파일 삭제·덮어쓰기
- 저장 결과 손상 가능성
- 악성 입력 또는 명령 실행 가능성
- 모델·API 라이선스 위반 가능성
- 제품의 핵심 생성 흐름
- 치명적 OOM·crash·무한 retry
- fallback 실패

단, 이미 같은 조건으로 검증됐고 관련 변경이 없다면
기존 증거를 재사용할 수 있습니다.

## 제7조 — 연구 확장 금지

현재 기능 구현 중 다음 작업을 자동으로 추가하지 마십시오.

- R2, R3 등 후속 연구단계
- 추가 threshold 탐색
- 더 많은 데이터셋
- 추가 Backend 비교
- 추가 camera compensation
- optical flow 연구
- adaptive planner 연구
- 논문용 ablation
- 새로운 RFC
- 백서 수준의 문서
- 범용화 실험
- 완벽한 Backend 독립성

새 실험은 다음 조건을 모두 만족할 때만 제안합니다.

- 현재 제품기능이 해당 문제로 실제 막힘
- 기존 fallback으로 해결 불가
- 해결 시 출시 일정이 단축됨
- 구현 범위와 종료조건이 명확함

제안만 할 수 있으며 사용자 승인 없이 실행하지 마십시오.

## 제8조 — 한 작업, 한 결정

각 작업은 하나의 제품 질문에만 답해야 합니다.

예:

- 이 Backend를 사용할 수 있는가?
- 이 selector가 실제로 작동하는가?
- 이 경로가 Full Compute보다 실용적인가?
- 사용자에게 결과를 전달할 수 있는가?
- fallback이 작동하는가?

작업 완료 후에는 반드시 다음 중 하나로 종료합니다.

- SHIP
- INTEGRATE
- KEEP_AS_OPTIONAL
- FALLBACK_ONLY
- REVISE_ONCE
- DROP

계속 연구하거나 검증을 반복하는 상태를 기본값으로 두지 마십시오.

`REVISE_ONCE` 이후에도 실패하면 기본적으로 `DROP` 또는
`FALLBACK_ONLY`로 전환합니다.

## 제9조 — 출시형 구현 원칙

첫 번째 제품에서는 가장 쉬운 작동경로 하나만 구현합니다.

- Backend 1개
- 핵심 사용자 시나리오 1개
- 실행 프로필 최소 구성
- selector 또는 cache 방식 최대 1개
- fallback 1개
- 목표 하드웨어 1종
- 결과 저장과 피드백 수집

완성되지 않은 고급기능은 숨겨진 실험옵션 또는 후속버전으로 미룹니다.

지원되지 않는 기능 때문에 전체 출시를 막지 말고:

```text
지원됨
→ 최적화 경로

지원되지 않음
→ Full Compute 또는 외부 Backend fallback
```

으로 처리합니다.

## 제10조 — 문서 최소화

작업일지는 유지하되 하나의 상세 worklog를 단일 진실원으로 사용합니다.

필수 기록:

- 무엇을 구현했는가
- 무엇을 생략했는가
- 생략 이유
- 핵심 테스트 결과
- 알려진 제한
- fallback
- commit SHA
- push 결과
- 다음 제품작업

다음을 금지합니다.

- 같은 상태를 여러 문서에 장문 반복
- 병합 사실만 기록하기 위한 반복 publication-sync PR
- 기능 없이 문서만 확장하는 RFC
- 이미 존재하는 증거의 재서술
- 완료된 단계를 다시 검증하는 작업

Roadmap, TASKS, Master Work Order에는 상태와 링크만 짧게 반영합니다.

## 제11조 — 테스트 실행 예산

기본 테스트 예산은 다음과 같습니다.

일반 기능 변경:

- focused unit test 1회
- smoke test 1회
- 핵심 실행경로 1회

통합 변경:

- 관련 integration test 1회
- 핵심 end-to-end 1회
- fallback 1회

Release Candidate:

- 전체 테스트 1회
- 설치·실행·결과저장 확인 1회
- 치명적 보안검사 1회

같은 commit에서 동일 테스트를 이유 없이 반복하지 마십시오.

성능 측정은 warmup을 제외하고
출시 결정을 내릴 수 있는 최소 반복만 수행합니다.

측정 잡음 때문에 결론을 내릴 수 없을 때만 추가 반복합니다.

## 제12조 — 시간제한

모든 실험과 기술 스파이크는 시작 전에 다음을 선언합니다.

- 제품 질문
- 최대 작업범위
- 최대 수정 횟수
- 종료조건
- 실패 시 fallback

범위가 계속 늘어나면 자동으로 중단하고
현재 가능한 가장 단순한 제품경로를 선택합니다.

완벽한 해결보다 작동하는 fallback을 우선합니다.

## 제13조 — HIVEFRAME 우선순위

현재 HIVEFRAME의 우선순위는 다음과 같습니다.

1. 사용자에게 작동하는 프로그램 제공
2. MiniMax H3 기반 생성경로 완성
3. 생성·저장·피드백 흐름 완성
4. 실패 시 Full Compute 또는 H3 fallback
5. 가장 간단한 선택적 계산 기능 1개 적용
6. 속도 또는 VRAM 이득이 있으면 제품에 통합
7. 이득이 없으면 해당 최적화를 출시조건에서 제외
8. 실제 사용자 데이터로 후속 개선
9. 자체 모델 학습과 고급 최적화는 출시 이후 확장

M1-B1과 M1-B2는 논문 수준의 완전한 검증이 아니라
제품에 적용할 기능을 빠르게 선택하는 Launch Blocker Spike로 수행합니다.

## 제14조 — 현재 M1-B0 처리

현재 진행 중인 M1-B0는 이미 사전 선언된 프로토콜이 있으므로
중간에 범위를 변경하지 않고 한 번 완료합니다.

M1-B0 완료 후:

- 추가 B0 연구를 자동 실행하지 않음
- 반복 benchmark를 하지 않음
- 전체 결과에 대한 대형 감사 작업을 하지 않음
- 치명적 오류와 결과 무결성만 확인
- 실용 후보 1개를 선정
- 즉시 M1-B1/B2 출시형 스파이크로 이동

M1-B0의 부족한 일반화는 출시 후 데이터로 보완합니다.

## 제15조 — Codex 행동규칙

Codex는 작업 중 다음을 스스로 판단해야 합니다.

- 기존 증거로 충분하면 재검증 생략
- 출시와 무관한 검증 생략
- 반복 테스트 생략
- 문서 중복 생략
- 추가 연구 생략
- 구현 가능한 가장 단순한 경로 선택
- 치명적 위험에는 fallback 적용
- 작업범위가 커지면 기능을 줄여서라도 완료
- 사용자 개별 지시가 헌법과 충돌하면 즉시 실행하지 않음
- 충돌하는 조항과 출시 영향을 사용자에게 보고
- 명시적인 유지·일회성 예외·영구 개정 선택을 받기 전까지 중단
- 일반적인 “진행해” 또는 “알아서 해”를 예외 승인으로 해석하지 않음
- 진행 중 충돌을 발견하면 결과를 삭제하지 않고 안전한 상태로 보존

검증을 생략한 사실은 숨기지 말고 짧게 기록합니다.

Codex는 “더 완벽하게 만들기 위해” 작업범위를 자동 확장하지 않습니다.

사용자의 명시적 승인 없이 다음 단계 연구로 넘어가지 않습니다.

## 저장소 반영 방법

이 헌법은 별도의 대형 RFC나 docs-only PR로 만들지 마십시오.

현재 M1-B0를 중단하거나 변경하지 마십시오.

M1-B0 완료 후 시작되는 첫 번째 기능 작업에서 다음에 반영하십시오.

- AGENTS.md:
  `Product-First Execution Constitution`을 최우선 규칙으로 추가
- README_FIRST.md:
  출시 우선 원칙에 대한 짧은 링크 추가
- HIVEFRAME_MASTER_WORK_ORDER.md:
  반복검증 금지와 최소 검증 원칙 추가
- TASKS.md:
  연구확장보다 출시기능 우선임을 상태 수준으로 반영

상세 헌법은 AGENTS.md 한 곳에만 두고
다른 문서에는 링크와 짧은 요약만 넣으십시오.

해당 기능 작업의 기존 branch와 PR에 함께 포함하고,
헌법만을 위한 별도 Issue·branch·PR은 생성하지 마십시오.

작업일지는 반드시 갱신하고,
commit과 원격 push까지 완료하십시오.

## 제16조 — 사용자 지시와 헌법의 충돌 처리

이 헌법은 사용자가 사전에 부여한 상시 작업지시입니다.

이후 전달되는 개별 사용자 지시가 이 헌법과 충돌하거나,
충돌 여부가 불명확한 경우 Codex는 가장 최근 지시라는 이유만으로
개별 지시를 바로 실행해서는 안 됩니다.

Codex는 먼저 충돌을 감지하고 작업을 중지한 뒤
사용자에게 한 번 더 명시적으로 확인해야 합니다.

### 16.1 충돌로 판단하는 경우

다음 중 하나라도 해당하면 헌법 충돌 후보로 판단합니다.

- 이미 통과한 검증을 같은 조건으로 다시 실행하라는 지시
- 출시와 직접 관계없는 검증을 추가하라는 지시
- 작업범위를 자동으로 확장하는 지시
- 별도 R2, R3, RFC 또는 추가 연구를 시작하라는 지시
- 하나의 기능작업에 여러 연구 질문을 함께 넣는 지시
- 문서만 변경했는데 전체 Python·Rust 테스트를 반복하라는 지시
- 이미 검증된 해시·환경·권리 증거를 다시 생성하라는 지시
- 출시 결정에 영향을 주지 않는 benchmark를 추가하라는 지시
- 한 번 실패한 실험을 명확한 변경 없이 반복하라는 지시
- 현재 제품경로보다 완전한 일반화·범용화를 먼저 수행하라는 지시
- 한 작업에서 Backend, selector, profile 또는 하드웨어를 여러 개
  동시에 비교하라는 지시
- 검증되지 않은 기능 때문에 전체 출시를 지연시키는 지시
- 제6조의 생략 불가능한 검증을 생략하라는 지시
- 기존 immutable evidence를 삭제·변경·덮어쓰라는 지시
- 사용자 데이터·권리·비용·보안·fallback 위험을 무시하라는 지시

표현이 다르더라도 실질적인 작업 결과가 위 항목에 해당하면
충돌 후보로 처리합니다.

### 16.2 충돌 발견 시 즉시 중단

충돌이 작업 시작 전에 발견되면 다음 행위를 하지 않습니다.

- 파일 수정
- Issue 생성
- branch 생성
- commit
- push
- PR 생성 또는 갱신
- 테스트 실행
- benchmark 실행
- 모델·API 실행
- 유료 호출
- 외부 데이터 전송

충돌이 작업 도중 발견되면 현재 진행 중인 원자적 작업을
안전하게 마칠 수 있는 최소 지점에서 중단합니다.

중단 시 다음을 수행하지 않습니다.

- reset
- clean
- stash
- rebase
- force-push
- amend
- history rewrite
- 생성된 결과 삭제
- 사용자 변경 덮어쓰기

현재 상태와 생성된 증거를 그대로 보존하고 보고합니다.

### 16.3 사용자 재확인 형식

충돌을 발견하면 다음 형식으로만 보고합니다.

```text
CONSTITUTION_CONFLICT_CONFIRMATION_REQUIRED

1. 현재 사용자 지시
2. 충돌하는 헌법 조항
3. 실제 충돌 내용
4. 그대로 실행할 경우 예상되는 시간·범위·출시 영향
5. 헌법을 유지할 경우의 최소 대안
6. 현재 Git·작업 상태
7. 아직 실행하지 않은 항목
```

그리고 사용자에게 다음 세 가지 중 하나를 선택하도록 요청합니다.

A. 헌법 유지

- 충돌하는 개별 지시를 실행하지 않음
- 헌법에 맞는 최소 작업으로 진행

B. 일회성 예외 승인

- 사용자가 명시한 이번 작업에만 예외 적용
- 헌법 자체는 변경하지 않음
- 예외 범위 밖의 작업은 계속 금지

C. 헌법 영구 개정

- 사용자가 특정 조항의 변경 내용을 명시
- 헌법을 먼저 수정
- 수정된 헌법을 기준으로 작업 재개

사용자가 명시적으로 선택하기 전에는 작업을 재개하지 않습니다.

### 16.4 명시적 확인 문구

일반적인 “진행해”, “알아서 해”, “그냥 해”는
헌법 충돌에 대한 예외 승인으로 간주하지 않습니다.

충돌 작업을 실행하려면 사용자가 다음과 같이
범위를 명확히 표시해야 합니다.

일회성 예외:

```text
헌법 일회성 예외 승인:
- 예외 조항:
- 허용 작업:
- 허용 범위:
- 종료조건:
```

영구 개정:

```text
헌법 영구 개정 승인:
- 변경 조항:
- 기존 내용:
- 변경 내용:
- 적용 시점:
```

명확한 범위가 없으면 다시 확인하고 실행하지 않습니다.

### 16.5 부분 충돌 처리

사용자 지시의 일부만 헌법과 충돌하는 경우
전체 작업을 무조건 폐기하지 않습니다.

다음처럼 분리해 보고합니다.

- 헌법과 일치하는 작업
- 헌법과 충돌하는 작업
- 충돌 없이 즉시 가능한 최소 작업
- 사용자 확인이 필요한 작업

다만 충돌하는 부분과 비충돌 부분이 기술적으로 분리되지 않거나,
비충돌 작업을 먼저 수행하면 사용자의 선택을 사실상 강제하게 되는 경우
전체 작업을 중지하고 확인합니다.

### 16.6 지시가 모호한 경우

사용자 지시가 다음처럼 해석될 가능성이 둘 이상이면
범위가 더 작은 쪽을 임의로 선택해 실행하지 말고 확인합니다.

예:

- “전체적으로 다시 검증해”
- “확실하게 다 확인해”
- “완벽하게 만들어”
- “필요한 테스트는 모두 해”
- “문제없게 최대한 검증해”
- “이전 결과도 다시 확인해”

이러한 표현은 자동으로 전체 테스트·반복 benchmark·추가 연구를
허용하는 지시가 아닙니다.

Codex는 어떤 검증이 실제로 필요한지,
기존 증거로 대체 가능한 것은 무엇인지 먼저 제시하고 확인받습니다.

### 16.7 충돌이 아닌 경우

다음은 헌법 충돌로 보지 않고 바로 진행할 수 있습니다.

- 기존 범위를 더 작게 줄이는 지시
- 출시 일정을 단축하는 지시
- 지원 기능을 하나로 좁히는 지시
- 반복검증을 생략하라는 지시
- 기존 증거를 재사용하라는 지시
- 치명적 오류 수정
- fallback 추가
- 사용자 데이터·권리·보안을 강화하는 변경
- 현재 작업을 안전하게 중단하고 상태를 보고하라는 지시

단, 범위를 줄이는 과정에서 제6조의 생략 불가능한 검증까지
삭제되는 경우에는 충돌 확인 절차를 적용합니다.

### 16.8 생략 불가능한 검증의 우선순위

제6조의 생략 불가능한 검증은 일반적인 일회성 예외로
자동 생략할 수 없습니다.

다음과 관련된 검증은 계속 유지합니다.

- 개인정보
- 학습동의
- 콘텐츠 권리
- API key와 자격증명
- 결제와 과금
- 사용자 파일 손상·삭제
- 치명적 crash·OOM·무한 retry
- fallback 실패
- 라이선스
- 핵심 사용자 흐름

사용자가 이를 생략하라고 지시하면 반드시 중단하고
위험과 결과를 설명한 뒤 다시 확인합니다.

법률, 서비스 약관, 보안정책 또는 상위 실행환경이 금지하는 작업은
사용자의 예외 승인만으로 실행하지 않습니다.

### 16.9 작업지시 작성 단계의 자체 점검

Codex는 새 작업을 시작하기 전에 다음을 한 번만 확인합니다.

- 이번 작업이 출시 기능과 직접 연결되는가
- 기존 증거를 다시 검증하려는 것은 아닌가
- 작업범위가 하나의 제품 질문을 넘지 않는가
- 이미 존재하는 fallback으로 충분하지 않은가
- 사용자의 최신 지시가 헌법과 충돌하지 않는가

충돌이 없으면 별도의 승인 절차 없이 바로 진행합니다.

이 점검 자체를 장문의 문서나 별도 검증 작업으로 만들지 않습니다.

## 제17조 — 지시 우선순위와 예외 기록

HIVEFRAME 저장소 안에서 작업지시를 해석할 때 다음 순서를 적용합니다.

1. 법률·서비스 약관·보안·실행환경의 강제 제한
2. 사용자가 승인한 Product-First Execution Constitution
3. 현재 작업의 명시적 제품 목표와 출시조건
4. 개별 작업지시문
5. 기존 Roadmap·RFC·권장 연구계획

개별 작업지시문이 상위 항목과 충돌하면
제16조의 재확인 절차를 적용합니다.

승인된 일회성 예외가 있는 경우 작업일지에 다음만 짧게 기록합니다.

- 예외 승인 문구
- 예외가 적용된 조항
- 허용된 범위
- 실제 수행 내용
- 종료 시점

일회성 예외를 다음 작업에 자동으로 재사용하지 않습니다.

영구 개정은 헌법 본문을 실제로 변경하고 commit한 이후에만
다음 작업부터 적용합니다.

## Subordinate repository safeguards

The remaining rules preserve existing evidence and repository discipline.
If they conflict with the constitution, the constitution governs.

## Required reading order

Before changing the repository, read:

1. `README_FIRST.md`
2. `docs/HIVEFRAME_EXECUTION_CONTEXT.md`
3. `TASKS.md`
4. `docs/WORKLOG.md`
5. `HIVEFRAME_MASTER_WORK_ORDER.md`
6. the architecture or M0 document relevant to the requested task

Do not infer completion from plans. Verify the current Git state and the
evidence linked from the worklog.

## Assets that must be preserved

- the existing repository and full Git history;
- M0 Wan baseline code, configuration, environment records, receipts, videos,
  smoke gates, reproducibility evidence, and memory-admission evidence;
- `schemas/run_receipt.schema.json` compatibility and existing receipt
  meanings;
- backend adapters, evaluators, model/license records, and data ledger;
- the legacy patch-centric design and tag `pre-compound-eye-v1`;
- user changes and unrelated files in a dirty worktree.

Never rewrite historical receipts or reinterpret an admission run as an
official quality or performance baseline.

## Research truthfulness

- Compound-eye execution is a falsifiable hypothesis, not a proven speedup.
- A `ComputePlan` is not proof that backend computation was skipped.
- Count observation, fusion, planning, generation, boundary, audit, repair,
  fallback, and output costs.
- Keep CUDA event span separate from profiler GPU-kernel duration.
- Unsupported or uncollected metrics use `null`, status, reason, and method;
  never substitute zero.
- Use same-condition comparisons for checkpoint, resolution, frames, FPS,
  steps, scheduler, precision, seed policy, VAE scope, and hardware class.

## Change discipline

- Use the smallest change that satisfies the current milestone.
- Do not add model training, new checkpoints, model downloads, CUDA kernels,
  multi-GPU, or GUI work unless the user explicitly expands the scope.
- Do not load Wan or run GPU generation during model-free architecture work.
- Run model-free tests before committing.
- Stage only files belonging to the task.
- Do not amend or rewrite commits that predate the current task.
- Do not push, tag remotely, create an Issue, or create a PR without explicit
  authorization for the exact GitHub repository.

## Verification budget

Apply Articles 2, 3, 5, 6, and 11. Run focused tests for the changed product
surface plus its smoke, core end-to-end, fallback, and release-blocking
security checks. Run the full Python/Rust suite only when the constitution's
full-suite conditions apply. If a required tool is missing, record the check
as skipped or unavailable with its reason rather than reporting a pass or a
numeric zero.

## Worklog update

Every intentional change must update `docs/WORKLOG.md` when it changes:

- verified state;
- architecture decisions;
- milestone or gate status;
- commands or test results;
- failures, blockers, unsupported capabilities, or reversibility.

Keep plans in `TASKS.md` and evidence in the worklog. Do not duplicate full
design documents in the log.
