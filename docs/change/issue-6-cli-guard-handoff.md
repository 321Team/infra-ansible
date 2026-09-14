# Issue #6 — 공개 CLI SSH guard 회귀시험 완료 인계

현재 상태: **Done (2026-09-14)**. 두 엔진의 실제 시험과 이하영님(@hayeounglee)의
독립 승인을 확인하고, 사용자 최종 병합 지시에 따라 코드·증적 PR을 병합했다.
P1-ANS-01 Done / PR #4 Merged·Closed 및 기존 승인 범위를 유지한다.
운영 apply·운영 엔진 전환·실제 6노드 SSH 검증은 이번 범위에 포함하지 않는다.

## 승인·병합 근거

| 구분 | 승인·시험 HEAD | 병합 commit |
|---|---|---|
| [코드 PR #13](https://github.com/321Team/infra-ansible/pull/13) | `37544b443fc9b11a35210ee087cb17811e23362d` | `2fb1e83a865711f8a4becbabdd95d48b3f27acf0` |
| [증적 PR #10](https://github.com/321Team/fds-project-evidence/pull/10) | `f68dd4bb76c7593ab9e52d44594ea6d10d3f4a36` | `f739b4b0dbc3522f973d416b7ae30041b5ffca0f` |

[코드 APPROVED 리뷰](https://github.com/321Team/infra-ansible/pull/13#pullrequestreview-5194336527) /
[증적 APPROVED 리뷰](https://github.com/321Team/fds-project-evidence/pull/10#pullrequestreview-5194320114)의
commit_id가 각 병합 대상 HEAD와 일치한다. 각 main의 병합 tree가 승인 HEAD tree와
동일함을 확인했다. [Issue #6 완료 기록](https://github.com/321Team/infra-ansible/issues/6)에
Acceptance Criteria와 실제 결과·실패 사례·독립 리뷰·완료일을 연결했다.

## 구현

- fixture·원본 guard 추출을 PyYAML 전용 모듈로 분리하고 Ansible 내부 import를 제거했다.
- 공개 ansible-playbook CLI로 7입력 × 2guard를 실행한다.
- boolean failed_when_result/failed, 실제 정수 rc 및 문자열 stdout의 독립 기대값을 검사한다.
- 식 오류·누락·잘못된 자료형은 ERROR, 기대값 불일치는 FAIL, 의도한 거부는 PASS다.
- OR→AND, 독립 or 목록 오류, undefined 식을 guard별로 재주입한다.
- export의 regression.yml / ssh-guards.yml / source-vars.json 및 fixture 생성 계약을 유지한다.
- 연결 실행기에 CLI·엔진 경로를 명시하고 단계·JSON 이름을 _expressions에서 _cli_guards로 이관했다.

## 2026-09-14 최종 검증

실제 Linux 실행 환경은 Python 3.12.14 / PyYAML 6.0.2이며,
SOURCE_STATUS는 비어 있고 기록된 소스 SHA는 위 시험 HEAD와 일치한다.

| 검사 | 최종 결과 |
|---|---|
| 호스트 독립 unittest | 10/10 PASS |
| Python compileall | PASS |
| 내부 Ansible API 참조 | 대상 tests/scripts에 없음 |
| 원본 태스크·변수 export / fixture 생성 | PASS |
| 실제 ansible-core 2.16.19 baseline | 14/14 PASS |
| 실제 ansible-core 2.21.3 baseline | 14/14 PASS |
| 두 엔진 baseline 동일성 | true |
| 실제 두 엔진 결함 재주입 | 12개 변형 검출 PASS |
| 전체 MATRIX | PASS / exit 0, 14회 CLI 실행·196개 관찰 |
| 제출 압축본·내부 manifest | 해시 일치 / 398개 내부 해시 일치 |
| 독립 리뷰 | 이하영님 코드·증적 모두 APPROVED |
| 코드·증적 PR | Merged / Closed |
| GitHub CI | NOT RUN — #5 후속 범위 |

각 엔진에서 and-0은 FAIL 4개, and-1은 FAIL 1개를 검출했다.
broken-list-0은 ERROR 1개, broken-list-1은 ERROR 4개를 검출했고,
undefined는 guard별 ERROR 7개를 검출했다. 모든 변형에서 수정하지 않은
guard의 7개는 PASS다. baseline CLI rc=0, 결함 변형 CLI rc=2다.

[실측 결과·실패 사례·원문 열람 시작점](https://github.com/321Team/fds-project-evidence/blob/f68dd4bb76c7593ab9e52d44594ea6d10d3f4a36/evidence/infra-ansible-issue-6/received-20260914-review/README.md).
단위시험의 subprocess 대체 출력은 실제 CLI 시험과 구분한다.
최종 PASS는 수정 HEAD의 새 서버 실행이며 기존 로그 재판정만을 뜻하지 않는다.

## 이전 실패 및 수정 이력

초기 로컬 시험은 8/8 PASS였지만 Linux CLI는 아직 실행하지 않은 상태였다.
이후 코드 `3fdcc6badf6e5cd2294f2e229451589197e86821`의 첫 서버 MATRIX는
FAIL / exit 1이었다. 당시 2.16.19 baseline은 14/14 PASS였고, 2.21.3 baseline은
CLI rc=0인데도 Python 판정에서 PASS 4 / ERROR 10으로 기록됐다.

2.21.3은 정상적인 failed_when=True 거부에도 exception 진단 필드를 포함한다.
이를 무조건 ERROR로 보던 판정기를 boolean 조건식 결과·failed 및 grep rc/stdout
계약에 따라 판정하도록 수정했다. 누락·비문자열 stdout 검사도 강화했다.
기존 관찰 196개의 재판정과 단위시험 10/10 PASS를 확인한 뒤,
최종 검증 표에 기재한 수정 HEAD의 새 서버 실행을 수행했다.
원본 FAIL 증적을 PASS로 덮어쓰지 않는다.

- 최초 FAIL 압축본 SHA256:
  `3a068a18e95dc8d2a10899435926c8450e94eb8357569d223d427823307e3d5b`.
- 최종 PASS 압축본 SHA256:
  `e06a8d6cd3f871f4ceccfd2a97a052b4982e9180b3f6806f7a2189a4aecce3e5`.

## 보존 범위와 잔여 한계

- 전체 399개 원본 파일은 수신·검증했으며, Git에는 독립 승인된 선별 34개 자료를
  편입했다. 폴더 SHA256SUMS는 나머지 등록 파일 33개를 검증한다.
- 압축본 자체는 Git/Release Asset에 올리지 않았다. 현재 원격 보관 존재·장기 보관은
  재확인하지 않았고 루트 REGISTRY_SHA256SUMS도 이번 선별 폴더를 아직 포함하지 않는다.
  리뷰어는 이를 현재 범위의 병합 차단 사항으로 보지 않았다.
- export는 호스트별 절대 경로를 포함한다. 실행 호스트에서 새 결과 디렉터리에
  생성하며 동시 실행끼리 디렉터리를 공유하지 않는다.
- 두 고정 엔진의 이번 기대 결과만 검증했으며 미래 버전 호환을 주장하지 않는다.
- 서버 6노드 결과 스키마, 재현 배포 키트, CI 자동화 및 운영 엔진 전환은 별도 후속이다.

## #7 다음 착수 지점

#6의 코드·실측 결과·독립 승인·병합 근거가 확보되어 #7 구조화 결과 작업을 진행할 수 있다.
`scripts/verify-ssh-main.py`의 원격 판정은 아직 PLAY RECAP 정규식과
SSH_READONLY_PASS 문구 개수에 의존한다. #7에서 스키마 버전·코드 SHA·엔진·
단계 ID·정확한 6개 노드 집합·완료 표시와 rc/failed/unreachable/rescued/ignored/
변경 개수를 명시하는 별도 수집 계약으로 이관한다.

누락·중복·잘림·잘못된 노드·시간 초과·nonzero 및 공백/문구 변화 음성시험을
추가하고 raw 로그 SHA256·원본 출처를 보존한다. 공개 CLI와 지원되는
callback/직렬화 방식을 선택하고 의존성을 고정한다. 미지원 --tree 또는
set_stats 자체 파일 생성을 가정하지 않는다. 운영 키·Token은 포함하지 않는다.
후속 순서는 #7 → #8 → #5 → #9이며 운영 변경 승인을 자동으로 확대하지 않는다.
