# Export 수정 코드의 정상 격리 Actions 착수 검토

2026-09-17. 사용자 “착수” 지시에 따라 새 정상 시험을 실행한다. 기존 테스트 전용 격리 실행의 범위를 유지한다.

## 변경 전 판단

PR17 source `6b2ac7a80be1acd187ac73cbd1cf957f708edf85`의 69개 blob/mode를 그대로 보존한다.
이 source에는 export 실패 상태 보완과 LOCAL 58/58 PASS 회귀시험이 포함된다.
그 성적을 실제 Actions로 승계하지 않는다. 이전 정상/negative는 각각 과거 source의 증적이다.

기존 [격리 시험 착수 기준](https://github.com/321Team/infra-ansible/blob/2750634766862d7fe19479acacc4259ee8315061/docs/ci/ISOLATED_ACTIONS_ENTRY.md)의
정본 근거·일회성 격리·운영 권한 미노출·실패 차단·독립 최종 검토 통제를 유지한다.
모든 격리 시험에 독립 승인을 일괄 선행조건으로 추가하지 않는다. 이번 자체 검토는 독립 승인이 아니다.

## 이번 시험의 고정 범위

- 브랜치: `test/issue-5-export-fix-positive-20260917` 한 개만 허용. 같은 저장소·main 대상 pull_request만 실행.
- parent에서 이 문서와 `.github/workflows/ansible-isolated-acceptance.yml` 두 파일만 추가한다.
- 기존 Workflow blob `71b22ee6443af9fea10da033a7d2e5a5651edd90`과 비교하여 설명 주석과 허용 ref만 변경한다.
  steps/Action SHA/permissions/labels/timeout/concurrency/checkout/artifact 계약은 유지한다.
- CI_SOURCE_SHA는 새 시험 PR의 전체 HEAD이며 최종 생성 후 PR 본문·시작 키트 EXPECTED.json에 기록한다.
- `contents: read`, 고정 labels `[self-hosted, Linux, X64, fds-ci, ansible-isolated]`, 30분 Job,
  exact source checkout, persist-credentials:false, 외부 Action 전체 SHA 고정을 유지한다.
- 일반 Workflow/enable 변수/main/PR17/PR19를 변경하지 않는다. 별도 TEST ONLY / DO NOT MERGE Draft PR이다.
- Runner bundle v1.3, Admin Token v1.1.1, Input Guard v1.0 payload는 기존 검증본의 동일 bytes를 사용한다.
  새 wrapper는 과거 PR20/Run 고정값 대신 이번 PR/Run/Attempt/Job/source에 고정한다.

## 현장 시작 순서

1. cicd-runner01의 일반 계정으로 토큰 없이 PREPARED 및 전용 계정의 현재 image ID/label을 읽기 확인한다.
   전체 Runtime·격리 검사는 이후 기존 launcher에서 다시 수행한다. 이 사전 확인을 전체 격리 PASS라고 하지 않는다.
2. ansible01 일반 계정에서 현재 PR/HEAD/Run/Attempt/Job·고정 labels·미배정·queued 상태와 경쟁 queued/in_progress를 GET 확인한 뒤에만 단기 token packet을 발급한다.
   페이지 조회가 완결되지 않았거나 상태가 바뀌면 중단한다. API 조회와 Runner 배정 사이의 원자성은 보장하지 않는다.
3. packet 한 파일만 비공개 전달하고 기존 safe_input/launcher로 ephemeral Runner 한 번을 실행한다.
   검증된 PREPARED/image 불일치 시 새 prepare를 자동 반복하거나 영수증을 수정하지 않는다.
4. 새 Runner ID/name과 실제 Job/Check/source/attempt, artifact 원본, 로컬 정리, 종료 후 원격 부재를 인수한다.
   이전 ID5/ID6 부재를 이번 세션에 재사용하지 않는다.

## 기대 결과와 중단

정상: syntax32/32 rc0, unit58 OK, guard/contract 완전 집합, DNS 양 엔진 rc0,
CI_RESULT PASS/실행기0·Job/Check success·원본 artifact/전체 manifest 일치.
새 회귀시험 내부의 합성 export 실패 출력은 unittest 성공 여부와 구분한다.
저장 장애 주입 전체 matrix는 이전 LOCAL/MOCK 증적이며 정상 실제 CI가 그 장애들을 실제 파일시스템에서 재현한 것은 아니다.

환경 오류·skipped·timeout·cancel·artifact 누락·격리/정리 실패를 정상 PASS로 처리하지 않는다.
count 결함 재시험 범위는 정상 인수 이후 변경 영향·리뷰로 판단하며 이번에 병행 Run을 만들지 않는다.
독립 승인·병합·Issue5 종결·운영 Apply·엔진 전환·일반 자동 CI 활성화는 별도다.
