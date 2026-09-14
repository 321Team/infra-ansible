# Issue #6 — 공개 CLI SSH guard 회귀시험 인계

기준 main: `5cbf3b657014b32a20cb5816d90d3ea5fe4951ab`.
P1-ANS-01 Done, PR #4 Merged/Closed 및 기존 승인 범위를 유지한다.
운영 apply·운영 엔진 전환·실제 서버 SSH 검증은 수행하지 않았다.

## 구현

- fixture/원본 추출을 PyYAML 전용 모듈로 분리. Ansible 내부 import 제거.
- 공개 ansible-playbook으로 7입력 × 2guard를 실행.
- 등록 결과를 builtin copy/to_json으로 저장하고 boolean 조건식 결과,
  실패 여부, 독립 기대 grep rc·개수 및 CLI 종료코드를 함께 검사.
- 식 평가 오류·누락은 ERROR, 기대값 불일치는 FAIL, 의도한 음성 결과는 PASS.
- OR→AND, 독립 or 목록 오류, undefined 식을 guard별로 재주입하는
  두 엔진 matrix 실행기 추가. baseline 동일성 및 미변경 guard 7개 PASS도 요구.
- export 3개 파일과 fixture 보존. 기존 연결 실행기의 명시적 CLI/엔진 고정 및
  단계명 `_expressions` → `_cli_guards` 동시 이관.

## 2026-09-14 로컬 검증

Windows / bundled Python 3.12 / PyYAML 6.0.2:

| 검사 | 결과 |
|---|---|
| 호스트 독립 unittest | 8/8 PASS |
| Python compileall | PASS |
| 내부 Ansible API 참조 검색 | 대상 tests/scripts에서 없음 |
| 기존 서버 실행기 --plan | PASS (실행 계획 출력만) |
| 원본 태스크·변수 export / fixture 생성 | 단위시험 PASS |
| 실제 2.16.19 CLI 14개 | NOT RUN |
| 실제 2.21.3 CLI 14개 | NOT RUN |
| 실제 두 엔진 결함 재주입 증명 | NOT RUN |
| 독립 리뷰 | PENDING |

단위시험은 일부 subprocess를 대체한다. 단위시험의 합성 PASS 출력은
실제 Ansible 엔진 검증 증적이 아니다.
로컬 Git 인증이 없어 GitHub 연결을 사용했다. 이 PC에는 사용할 Linux/WSL
배포판과 Docker가 없어 Ansible controller 실행은 검증하지 못했다.
재현 명령은 SSH-Key-Guard-Verification runbook에 있다.
두 엔진 시험·독립 리뷰 전까지 Draft 및 #6 Open 상태를 유지한다.
원본 실행 로그의 정식 증적 편입은 fds-project-evidence에 남아 있다.

## 잔여 위험

- 두 고정 엔진의 실제 registered result 형태와 ERROR 분류는 matrix 실행으로
  확인해야 한다. 미래 Ansible 버전 호환을 주장하지 않는다.
- export는 호스트별 절대 경로를 포함한다. 실행 호스트에서 새 결과 디렉터리에
  생성하며 동시 실행끼리 디렉터리를 공유하지 않는다.
- 로컬 회귀의 구조화 결과는 서버 6개 노드 결과 스키마를 대체하지 않는다.
- CI 자동화(#5), 재현 배포 키트(#8), 운영 엔진 전환(#9)은 미완료다.

## #7 다음 착수 지점

`scripts/verify-ssh-main.py`의 원격 판정은 아직 PLAY RECAP 정규식과
SSH_READONLY_PASS 문구 개수에 의존한다. #7에서 스키마 버전·코드 SHA·엔진·
단계 ID·정확한 6개 노드 집합·완료 표시와 rc/failed/unreachable/rescued/ignored/
변경 개수를 명시하는 별도 수집 계약으로 이관한다.

누락·중복·잘림·잘못된 노드·시간 초과·nonzero 및 공백/문구 변화 음성시험을
추가하고 raw 로그 SHA-256·원본 출처를 보존한다. 공개 CLI와 지원되는
callback/직렬화 방식을 선택하고 의존성을 고정한다. 미지원 --tree 또는
set_stats 자체 파일 생성을 가정하지 않는다. 운영 키·Token은 포함하지 않는다.

#7 설계와 로컬 구현은 시작 가능하지만, #6 두 엔진 검증 완료를 전제한
완료 판정이나 후속 운영 전환 승인은 할 수 없다.
