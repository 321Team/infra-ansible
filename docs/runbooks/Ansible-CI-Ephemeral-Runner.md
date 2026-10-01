# Ansible CI — Ephemeral Runner 운영 Runbook

대상: `321Team/infra-ansible`의 `ansible-isolated` self-hosted Runner  
연계: infra-ansible #61, 기존 Runner v1.3 launcher, `.github/workflows/ansible-regression.yml`

이 문서는 상시 Runner 운영 절차가 아니다. 승인된 CI Job 1건에 대해 **필요 시 1회 등록 → Job 수행 → 자동 deregister/cleanup**하는 기존 격리 모델을 표준화한다.  
`infra-cicd`의 장기 실행 `cicd-runner01`과 혼용하지 않는다.

## 1. 실행 전 read-only 확인

Runner 공급 전에 다음을 확인한다.

- 대상 PR exact HEAD와 대상 Run/Attempt/Job ID
- Job 상태가 실제로 `queued`인지
- required labels가 `self-hosted, Linux, X64, fds-ci, ansible-isolated`인지
- 같은 Job을 소비할 matching Runner가 이미 online인지
- 기존 Runner 세션이 in-progress인지
- workflow condition이 통과한 Job인지
- token 발급 전 관리 호스트와 launcher 준비 상태가 기존 승인 범위와 일치하는지

queued 상태 분류에는 다음 read-only 도구를 사용한다.

```bash
python3 -I -B tools/ansible-ci-queue-watch.py \
  --job-id <JOB_ID> \
  --threshold-minutes <APPROVED_OR_OPERATOR_SELECTED_THRESHOLD> \
  --expected-source-sha <PR_EXACT_HEAD> \
  --output <NEW_EVIDENCE_PATH>.json
```

`--threshold-minutes`는 프로젝트 승인값을 코드가 임의로 정하지 않는다. 운영자가 현재 결정에 따라 명시한다.

분류 의미:

| classification | 의미 | 조치 |
|---|---|---|
| `QUEUED_WITHIN_GRACE` | threshold 미도달 | 공급 판단 유보 |
| `EPHEMERAL_RUNNER_NOT_SUPPLIED` | threshold 초과 + matching online Runner 없음 | Runner 공급 담당자 확인 |
| `QUEUED_WITH_MATCHING_RUNNER_ONLINE` | matching online Runner 존재 | 중복 공급 금지, 다른 원인 확인 |
| `JOB_IN_PROGRESS` | 이미 실행 중 | 추가 Runner 공급 금지 |
| `JOB_COMPLETED` | 종료됨 | 새 Runner 공급 금지 |
| `NOT_ANSIBLE_ISOLATED_JOB` | required labels 불일치 | 본 절차 적용 금지 |

도구는 token 발급, Runner 등록/삭제, Job rerun/cancel, repository 설정 변경을 수행하지 않는다.

## 2. STOP 조건

다음 중 하나면 Runner를 공급하지 않는다.

- exact HEAD가 바뀌었거나 대상 Job과 결속되지 않음
- Job이 `queued`가 아님
- matching Runner가 이미 online 또는 Job이 in-progress
- required labels가 승인된 5개 라벨과 다름
- 동일 Job을 위한 다른 공급 세션이 확인됨
- launcher/prepare 상태가 검증 기준과 불일치
- fresh registration/removal token을 안전하게 발급할 수 없음
- token/PAT/private key가 증적·로그·명령 인자에 노출될 가능성이 있음

## 3. Runner 공급과 Job 확인

기존 승인된 v1.3 launcher 경로를 재사용한다. 새 상시 서비스 Runner를 만들지 않는다.

운영 순서:

1. preflight 증적 저장
2. fresh registration/removal token 발급
3. 기존 v1.3 launcher의 prepare 상태 확인
4. 대상 Job 1건용 ephemeral Runner serve
5. Runner name/ID와 Job ID 결속 확인
6. Job `in_progress` 전환 확인
7. exact source checkout과 regression 실행 확인
8. regression 결과와 artifact upload 결과를 **분리 판정**
9. Job 종료 후 deregister/container/workspace cleanup 확인
10. 동일 Runner ID/name의 원격 부재를 read-only로 재확인
11. token packet 폐기 및 증적 archive/hash 생성

`SESSION_ENDED_REQUIRES_CI_REVIEW` 또는 launcher rc=0은 CI PASS 판정이 아니다.  
Regression PASS와 artifact upload FAIL도 서로 다른 상태로 기록한다.

## 4. 실패 원인 분류

운영 기록에는 최소 다음 상태를 분리한다.

- `RUNNER_SUPPLY_FAILURE`: registration/prepare/serve/Job 수신 단계 실패
- `REGRESSION_FAILURE`: Job 수신 후 syntax/engine/fixture 등 회귀검사 실패
- `ARTIFACT_UPLOAD_FAILURE`: regression 성공 후 artifact upload 실패
- `JOB_CANCELLED_OR_REPLACED`: concurrency 또는 사람 조치로 대상 Job이 교체/취소됨
- `CLEANUP_FAILURE`: Job 종료 후 deregister/container/workspace/absence 검증 실패

한 상태의 PASS를 다른 단계의 PASS로 확대하지 않는다.

## 5. 증적 필수 필드

세션별 evidence에는 아래 값을 추적 가능하게 남긴다.

| 구분 | 필수 값 |
|---|---|
| 대상 | repository, PR, exact source SHA |
| Actions | Run ID, Attempt, Job ID, Job name |
| 시간 | queue 관측, Runner 공급 시작, Job 시작/종료, cleanup/absence 확인 시각 |
| Runner | runner name, runner ID, required labels |
| 실행 | regression conclusion, artifact upload conclusion |
| 정리 | deregister 결과, container/workspace cleanup 결과, 원격 absence 결과 |
| 무결성 | evidence archive/file SHA256 |
| 범위 | production apply 여부, 운영 변경 여부 |
| 보안 | token/PAT/private key 원문이 저장되지 않았음을 확인 |

등록/removal token 값, PAT, private key, token hash는 증적에 저장하지 않는다.

## 6. 완료 조건

#61 P0 운영절차 기준 완료 조건:

- queued read-only 분류 도구가 unit test를 통과한다.
- runbook 절차와 STOP 조건이 독립 리뷰된다.
- 실제 다음 ephemeral 세션에서 위 필드가 모두 수집되고, Job/Runner/cleanup 결속이 확인된다.
- 동일 Job 중복 공급이 없었음을 확인한다.
- 실패 시 원인이 supply/regression/upload/cleanup 중 하나로 구분된다.

본 문서 반영만으로 실제 Runner Runtime 인수나 #61 전체 Close를 선언하지 않는다.
