# Artifact export 수정 후 격리 CI 준비

2026-09-17. 상태: 준비 문서. 새 시험 브랜치/PR/Run/토큰/서버 세션은 이 변경에서 생성하지 않는다.
독립 검토·일반 Workflow 활성화·병합·운영 Apply와 시험 전용 격리 실행을 구분한다.

## 변경 영향과 근거

- 수정 commit: `a9785da3485ffd61840a82a3e9bd14ceb4edb50b`, parent `9b019ad4213539e9a6edf2409e1d0bd0d4ef46f6`.
- 변경 파일: `tools/run-ansible-ci.py`, `tests/test_ci_regression.py` 두 개.
- 실행기 blob `3cfc253ca61a190b06a2af3ed1cf019e8f23114a`; 시험 blob `88711431014812f4365044bd72b67155300e2b0e`.
- 공개된 수정 source 68개 파일을 복원하여 LOCAL 58/58 PASS. 별도 수정안 통합 LOCAL/MOCK 157/157과 바이트 동일성 확인.
- 저장 장애 12개 시나리오는 합성 I/O 오류 주입이다. 7개 쓰기 가능한 장애 경로의 잔존 PASS를 FAIL로 보완했다.
  지속 쓰기 장애 1개에서는 파일을 재기록하지 못하며 rc1·불완전 manifest로 인수를 거부한다.
- 원자적 publication·SIGKILL/전원 손실 내구성은 구현하지 않았다. 이 한계를 신규 병합 차단 AC로 임의 승격하지 않는다.
- SSH guard/fixture 기대값/엔진 버전/Workflow 실행 단계/Runner PR19는 변경되지 않았다.

기존 정상·count 결함의 실제 증적은 [Actions 인수 기록](ACTIONS_ACCEPTANCE.md)에 연결돼 있다.
수정 코드가 포함된 새 HEAD의 실제 CI 결과는 아직 없다. 문서 갱신 commit은 위 두 blob 동일성으로 로컬 결과와 연결한다.
문서 HEAD가 확정되면 증적 PR13에 전체 source HEAD와 비교 결과를 기록한다.

## 다음 정상 시험 준비 순서

1. 최종 PR17 HEAD를 다시 조회하고 독립 리뷰의 대상 HEAD를 갱신한다. 자체 시험과 사람의 승인을 구분한다.
   제한된 격리 시험 준비에는 기존 [착수 기준](https://github.com/321Team/infra-ansible/blob/2750634766862d7fe19479acacc4259ee8315061/docs/ci/ISOLATED_ACTIONS_ENTRY.md)의 적용 범위를 유지한다.
2. 최종 source에서 새 TEST ONLY / DO NOT MERGE 브랜치를 만들 때 새 브랜치 이름과 전체 commit을 고정한다.
   과거 PR20/21을 새 코드 시험으로 재표기하거나 과거 Run을 단순 rerun하지 않는다.
3. 기존 격리 Workflow blob `71b22ee6443af9fea10da033a7d2e5a5651edd90`을 비교 기준으로 사용한다.
   새 전용 브랜치 허용 조건 및 현재 착수 기록만 명시적으로 갱신한다. 이전 날짜의 두 ref를 그대로 사용하지 않는다.
   다음 계약을 원문과 대조한다: pull_request·동일 저장소·main 대상·지정 ref만, contents:read,
   고정 5개 labels, 30분 timeout, exact source checkout, persist-credentials:false, 고정 Action SHA,
   양 엔진 실행 및 always 조건의 artifact 보존. 일반 enable 변수나 main Workflow는 이 시험 때문에 변경하지 않는다.
4. 새 PR 생성 전 source 대비 변경 집합과 Workflow 조건을 검토한다. 새 PR/Run이 생성되면
   PR/head/ref/repo·Run/Attempt·regression Job/labels·queued 상태와 경쟁 작업 유무를 다시 수집한다.
   현재 준비 단계에는 새 Run/Attempt/Job 값이 없으므로 토큰 발급·serve 실행 명령을 제공하지 않는다.
5. 호스트 연결 전 PREPARED/bundle/image와 launcher의 실행 시 검사를 확인한다.
   기존 Runner PR19가 불변이라는 이유만으로 현재 서버 상태가 동일하다고 단정하지 않는다.
   일치하면 기존 검증 이미지의 재사용을 검토한다. 불일치하면 증적을 확인하고 원인에 맞는 조치를 정한다.
6. 하나의 ephemeral Runner에서 정상 Job을 수행하고 source/Run/Attempt/Job/Check·원본 ZIP·완전한 manifest·
   fixture·세션 정리·새 Runner ID/name 원격 부재를 함께 인수한다. 이전 ID5/6 부재는 대체 증명이 아니다.

Start v1.1은 과거의 시작용 wrapper 버전이고 v1.3은 Runner bundle 버전이다.
특히 기존 `01-admin-token.sh`의 PR20/정상 Run 고정값은 새 시험에 맞지 않는다.
새 실행 대상을 검증한 전용 절차가 준비될 때까지 그 명령을 복사해 실행하지 않는다.
`PREPARED` 수기 변경, 홈 권한 변경, 전체 Runner 삭제, `podman prune`은 해결 절차에 포함하지 않는다.

## 시험 범위와 인수 기준

| 범위 | 다음 수행/판정 |
|---|---|
| 수정 코드 정상 실제 Actions | 권장 필수: syntax32/32, unit58 OK, guard/contract 완전 집합, DNS 양 엔진 rc0, CI PASS/rc0, Job/Check success, 완전한 artifact |
| export 저장 장애 | 기존 LOCAL/MOCK 12개 및 새 회귀시험의 원문 검토; 정상 CI 성공만으로 실제 디스크 장애를 시험했다고 주장하지 않음 |
| count 실제 결함 재시험 | 기존 두 엔진 실제 실패 전파 증적과 변경 영향 검토 후 범위 확정; 이번 준비만으로 면제 또는 자동 재실행을 확정하지 않음 |
| count 재시험을 선택하는 경우 | 새 정상 source에서 count 한 줄만 변경, 양 엔진 baseline5 FAIL/나머지9 PASS/ERROR0, CI FAIL/rc1, Job/Check failure, 정상 artifact 업로드 및 세션 정리 |
| 취소/동시성·실제 디스크 고갈 | 이번 준비 범위 밖; 별도 시험 설계와 실행 범위가 필요 |

저장 장애의 불완전 artifact는 결과 파일이 PASS여도 인수하지 않는다. 정상 Job·CI_RESULT·digest·전체 manifest·
source/attempt 결합을 모두 만족해야 한다. Workflow의 retention-days:14는 실제 만료 보장이 아니므로 API expires_at을 확인한다.
운영 inventory/SSH, 운영 Apply, 엔진 전환, 일반 PR 자동 실행, 자동 병합은 이 격리 시험의 결과로 완료 처리하지 않는다.
