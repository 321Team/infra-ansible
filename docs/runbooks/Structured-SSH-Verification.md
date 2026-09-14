# Issue #7 구조화 SSH 검증

Status: 구현·로컬 시험 완료, 실제 두 엔진 CLI 시험·실제 노드 비교·독립 리뷰 대기.
이 문서는 운영 설정 적용이나 엔진 전환 지시가 아니다. #6 Done 및 PR #4 Closed를 유지한다.

## 결과 수집과 판정

공개 `ansible-playbook`이 저장소의 `fds_verification` stdout callback을 로드한다.
callback은 Ansible의 v2 이벤트를 JSON Lines로 기록한다. 판정기는 Ansible을 import하지
않으며, stdout 문구나 PLAY RECAP을 해석하지 않는다. `--tree`나 set_stats 파일 생성을 사용하지 않는다.

- `start`: schema_version=1, code_sha, 실제 engine, run_id, stage_id, seq.
- `task`: host, task_id, action, outcome, rc, changed, failed, condition, ignored,
  no_log 및 loop item별 rc/상태. 변수·모듈 인자·stdout/stderr·exception 본문은 수집하지 않는다.
- `complete`: completed=true와 실제 노드별 ok/changed/failed/unreachable/skipped/rescued/ignored.
- 별도 최종 Play의 `fds_stage_complete` 태스크가 노드별 run_id/stage_id/completed를 기록한다.
- SSH 읽기 단계는 `fds_ssh_verified` 태스크의 구조화된 키 개수 1/1·root·파일 불변 확인도 요구한다.

코드 SHA와 깨끗한 Git 상태는 실행 전후에 확인한다. 결과 디렉터리는 checkout 밖의 새 경로여야
하며 기존 결과를 덮어쓰지 않는다. 각 단계의 context.json, events.jsonl, stdout.log, stderr.log,
report.json을 보존한다. stdout/stderr는 재인코딩하지 않은 원본 바이트이며 report의 origin에
원본 파일 SHA256과 실행 명령·출처가 연결된다. callback의 원본은 전체 모듈 결과 덤프가 아니라
위 허용 필드의 이벤트 원본이다. 전체 결과를 수집했다고 해석하지 않는다.

다음 중 하나라도 발생하면 REVIEW_REQUIRED이며 전체 실행은 nonzero다.

- 6대의 정확한 집합 불일치, 완료 표시 누락·중복, 이벤트 seq 누락·중복, 같은 host/task_id 중복.
- JSON 문법/자료형 오류·중복 key·잘림, 다른 실행/코드/엔진/단계의 결과.
- CLI nonzero/시간 초과, failed/unreachable/rescued/ignored, 평가 오류 또는 command/loop rc 누락·nonzero.
- SSH 증명 누락·잘못된 개수, 예상 밖 변경 수 또는 task와 summary 변경 수 불일치.

check 단계는 이미 제한된 키를 전제로 노드별 changed 0/1(기존 백업 유무 차이)만 허용한다.
다른 원격 단계는 changed=0이다. command의 failed_when=false도 nonzero rc를 숨기지 못한다.
기존 DNS 검증에서 없는 서비스의 systemctl rc를 허용하던 환경도 새 판정에서는 중단될 수 있다.
실제 6대 비교에서 확인할 보수적 변경이며, 로그 문구로 예외 처리하지 않는다.

## 지원 경계와 의존성

- Python 3.12와 `tests/requirements-verification-2.16.19.txt` / `2.21.3.txt`의 정확한 버전을 사용한다.
  #6 승인 환경의 버전 목록이며 실행기가 실제 설치 버전을 검사한다. 자동 설치는 하지 않는다.
- callback 확장 자체는 [공식 개발 문서](https://docs.ansible.com/projects/ansible/latest/dev_guide/developing_plugins.html#callback-plugins)를 따른다.
- 2.16.19의 결과 접근은 [해당 버전 기본 callback](https://github.com/ansible/ansible/blob/v2.16.19/lib/ansible/plugins/callback/minimal.py)의
  `_host/_task/_result`, 2.21.3은 [해당 버전 callback](https://github.com/ansible/ansible/blob/v2.21.3/lib/ansible/plugins/callback/minimal.py)의
  `host/task/result`를 사용한다. 이 어댑터에만 버전별 접근을 제한한다. 내부 Conditional/Templar 평가를 재도입하지 않는다.
- 추가 Collection 의존성은 없다. wheel hash·폐쇄망 배포·완전한 재현 키트는 #8에서 추적한다.
- 다른 엔진 버전이나 임의 playbook/strategy 조합을 지원한다고 주장하지 않는다.

## 로컬 및 두 엔진 격리 시험

```bash
python3 -B -m unittest discover -s tests -p 'test_*py' -v
/absolute/venv-216/bin/python -B tests/run-verification-contract-matrix.py \
  --python216 /absolute/venv-216/bin/python \
  --python221 /absolute/venv-221/bin/python \
  --output /absolute/new-issue-7-results
```

두 번째 명령은 Linux의 깨끗한 Git checkout에서 실행한다. `fixture-1`~`fixture-6`은 모두
local connection을 쓰는 합성 별칭이며 운영 inventory·SSH 키를 사용하지 않는다.

- 엔진별 실제 CLI 13회: baseline, 문구/공백 변화, serial, 기대 실패, 일반 실패,
  ignored, rescued, 표현식 오류, 숨긴 rc, 예상 밖 changed, 로컬 transport 오류, 노드 제한, timeout.
- baseline 원본에서 엔진별 13개 파생 입력: 완료/노드/표시 누락·중복·잘림·다른 코드/엔진/단계,
  JSON 중복 key와 공백 변화. 출처를 mutated callback fixture와 원본 해시로 구분한다.
- 총 26회 실제 CLI + 26개 파생 검증 = 52개 판정과 두 baseline 동일성이 모두 맞아야 MATRIX PASS다.
- 기대 실패는 테스트 전용 명시 태그·rc=7·boolean condition=true·ignored 1개/노드가 모두 일치해야
  EXPECTED_FAILURE_CONFIRMED다. 운영 읽기 단계에서는 이 옵션을 활성화하지 않는다.
- 엔진 부재나 callback 미로딩은 음성시험 성공으로 처리하지 않는다.

2026-09-14 Windows 로컬 단위시험은 25/25 PASS다. 이 중 callback 객체는 버전별 모양을 대체한
합성 객체이며, 실제 프로세스 시험은 Python의 원본 바이트·종료·timeout을 검사한다.
실제 Ansible CLI matrix와 실제 6대 비교는 아직 NOT RUN이다. 이전 #6 로그를 #7 PASS로 재사용하지 않는다.

## 실제 서버 읽기 검증 (별도 실행)

두 엔진 격리 matrix를 확인한 뒤 승인된 읽기 범위에서 다음을 실행한다.

```bash
python3 -B scripts/verify-ssh-main.py \
  --python216 /absolute/venv-216/bin/python \
  --python221 /absolute/venv-221/bin/python \
  --output /absolute/new-server-results
```

기존 SSH key/known_hosts를 사용하며 미등록 host key·대화형 인증을 허용하지 않는다.
각 엔진에서 version/runtime/guard fixture/exported localhost/readonly SSH/hardening check/
OS precheck/DNS verify의 8단계를 수행한다. 총 16단계와 실행 종료 시 소스 상태가 맞아야
PASS_READONLY_SCOPE다. 실제 apply, rollback, 운영 엔진 전환 및 #8/#5/#9 완료는 포함하지 않는다.

Issue #7은 실제 두 엔진 결과·실제 노드 차이 검토·실패 증거·독립 리뷰·증적 편입까지 연결한 뒤 종결한다.
