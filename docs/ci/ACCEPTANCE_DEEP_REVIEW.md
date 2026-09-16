# Actions 인수 준비 딥리뷰 — 패치 작성 전

기준: PR17 `5ed6d3947a15d59cf6c360c0419f961b8143c707`, PR19 `2fae52a9e09e33b8c8bff6c653b8533d8b52dc47`.
자체 검토이며 독립 승인이나 실제 Actions 결과가 아니다.

## 발견한 인수 절차 결함

현재 runbook은 첫 SSH guard의 `or`를 `and`로 바꾼 commit을 실제 음성 Actions 사례로 제시한다.
그러나 `tests/run-ssh-guard-matrix.py`는 모든 guard의 failed_when에 ` or `가 있는지 먼저 확인한다.
조건을 바꾸면 `Source changed: mutation requires explicit OR`가 발생해 baseline CLI 실행 전에 중단한다.
이 nonzero만으로 guard 회귀 탐지 성공을 주장하면 실패 원인을 잘못 인수하게 된다.
실제 Actions에서 이 문제가 발생했다고 주장하지 않는다. 아직 비활성 템플릿 단계다.

## 변경할 인수안

- 기존 guard/mutation 시험기는 유지한다.
- 고의 결함 패치는 `playbooks/harden_svc_ansible_key.yml` 첫 guard의 count 비교 `!= 1` 한 곳만 `!= 2`로 바꾼다.
  OR, 두 번째 guard, 기대값 정의와 판정기는 유지한다. 테스트를 느슨하게 만들지 않는다.
- 로컬 fresh checkout에서 패치 적용 전후 blob/변경 집합을 대조한다. 패치는 기존 파일 한 줄만 변경해야 한다.
- 기존 public CLI harness로 정상과 결함을 같은 2.16.19 실행기에서 비교한다.
  예상 결함: one_plain/one_restricted는 부당하게 거절되고 two_plain/two_restricted/mixed는 부당하게 허용된다.
  첫 guard 5 FAIL, 남은9 PASS, ERROR0, harness rc1이 기대값이다.
- OR 전제조건을 유지하고 기존 matrix의 variant 생성 단계를 통과하는지 별도로 확인한다.
  이 준비 시험은 전체 양 엔진 matrix 또는 실제 Actions Job 실행의 대체가 아니다.
- 2.21.3은 이전 로컬 IPC 제한이 확인된 환경이므로 이번 준비의 필수 실행으로 반복하지 않는다.
  승인된 Runner의 실제 Actions 정상/결함 인수에서는 양 엔진 원문 결과를 확인한다.

## 활성화 패치와 증적 인수

- 검토용 patch 파일만 게시한다. `.github/workflows/ansible-regression.yml`을 새로 추가하는 패치는
  현재 docs/ci 템플릿과 동일 바이트여야 한다. 이 패치를 실제 원격 브랜치에 적용하지 않는다.
- 설정 disabled/unset 시 skip은 정상 실행 PASS가 아니다. 변수 변경·serve·merge는 이번 범위 밖이다.
- source SHA, workflow SHA, event SHA, Check SHA를 별도 기록한다. PR 이벤트의 GITHUB_SHA는 merge SHA일 수 있으므로
  모든 SHA가 같다는 조건을 만들지 않는다. exact checkout 소스는 PR head SHA와 연결한다.
- Run ID와 attempt가 같은 jobs/check/artifact를 수집하고 upload 성공 여부도 확인한다.
  환경/설치/권한/취소 오류, artifact 부재를 기대한 결함 탐지 PASS로 표시하지 않는다.
- 운영자 수집 증적은 기존 로그인 홈의 새로운 디렉터리에만 만든다. 임의 입력 경로 chmod나 재귀 삭제 명령은 넣지 않는다.
- PR17/19 검토 대상 소스, 새 activation commit, 정상/결함 commit과 인수 결과를 구분한다.

## 공식 근거

- [PR event SHA와 head SHA](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
- [특정 Run attempt의 Jobs API](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt)
- [Artifact ID·digest·workflow_run 메타데이터](https://docs.github.com/en/rest/actions/artifacts#list-workflow-run-artifacts)
