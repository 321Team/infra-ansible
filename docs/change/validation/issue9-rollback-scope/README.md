# DNS rollback 단일 대상 격리 검증

2026-10-09 13:48:39~13:49:12 KST, ansible01/server01_ansible, 별도 `/home/server01_ansible/issue9-rollback-scope.W7a4KvOl`. 전체 명령·시각·rc·source hash는 `VALIDATION.json`, 원 출력은 각 `.stdout`/`.stderr`다. 이 폴더의 `SHA256SUMS`는 수신 파일 무결성 목록이다.

| 검사 | 2.16.19 | 2.21.3 |
|---|---|---|
| 변경 playbook 기반 local-only scope fixture | 10 tests PASS | 10 tests PASS |
| 실제 playbook syntax | rc0 | rc0 |
| 기존 main5111c66 playbook에 단일 대상 회귀 검사 | 예상 rc1, 대상 외 facts 검출 | 예상 rc1, 대상 외 facts 검출 |

회귀 검사는 한 test method 안의 worker02/control01 두 선택을 확인한다. 실패는 기존 코드 결함을 탐지한 기대 결과이며 정상 코드 CI 성공이 아니다. fixture는 실제 leading assert/end_host를 유지하고 그 뒤 원격 파일 읽기·nmcli·서비스 조작을 marker로 대체한다. 기존 코드에서 비대상 facts가 먼저 실행되는 점을 확인하며, 기존 코드가 모든 노드를 실제 rollback했다고 주장하지 않는다.

수신 후 `VALIDATION.json`의4 source hash를 playbook·test·이 runner·base5111c66 Git blob과 대조했다. 실제 복구 태스크 전체가 base와 동일하고 remote hosts 선택과 선행 controller guard만 바뀌었음을 YAML 객체 비교로 확인했다.

재현은 같은 승인 계정의 별도 작업 폴더에서 수행한다. 저장소의 `tests/test_dns_rollback_scope.py`와 `playbooks/cr-p1-ans-01-01-rollback.yml`을 동일 상대 경로로 복사하고, `git show 5111c66f233fe0f84e2d63cef3837fe091a2a268:playbooks/cr-p1-ans-01-01-rollback.yml` 원 bytes를 `base-rollback.yml`로 보존한다. 이 폴더의 `run-rollback-scope-validation.py`를 작업 폴더 루트에 놓고 고정 두 venv가 검토된 설치물인지 확인한 뒤 Python3.12 `-I -B`로 실행한다. 스크립트는 ansible01/non-root를 확인하며 두 engine의 fixture·syntax·base 회귀만 실행한다. 운영 checkout에 적용하거나 실제 rollback wrapper를 호출하지 않는다.

운영 SSH/sudo/DNS 변경·백업 복원·엔진 전환은 **NOT_RUN**이다. controller의 local facts 조회와 사용자 임시 폴더/로그 생성만 있었다. GitHub CI와 독립 리뷰는 별도다.

두 `*-base-regression.stderr` 첫 줄의 unittest 출력 공백은 원 bytes를 보존했다. 이2줄의 diff whitespace 경고를 제외한 코드·문서는 diff check를 통과했다.
