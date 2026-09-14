SSH 키 조건식 수정 및 실제 서버 검증
===================================

main의 `harden_svc_ansible_key.yml`에서 `failed_when` 목록에 독립된 `or`를
작성해 키 개수 검증을 건너뛰거나 표현식 오류가 발생하던 문제를 수정한다.
최초·최종 검사를 각각 단일 OR 표현식으로 변경한다. 키 경로, 제한 옵션,
교체 정규식, 백업 방식은 기존과 같다.

로컬 회귀 시험:

```bash
python3 tests/test-ssh-key-guards.py --output /tmp/ssh-guard-test.json --export-dir /tmp/ssh-guard-generated --ansible-playbook /absolute/venv/bin/ansible-playbook --expect-engine 2.16.19
```

빈 파일, 제한 전 키 1개, 제한된 키 1개, 각각의 중복, 혼합, 파일 부재를
두 원본 검사 태스크에 적용한다. 14개 사례의 기대 결과는 fixture 계약으로
정의한다. 혼합 입력은 최초 검사에서 차단된다. 최종 검사만 단독 평가하면
제한된 키가 1개이므로 통과하는 것이 해당 검사 범위의 기대값이다.
fixture 생성·원본 추출은 `tests/ssh_guard_fixtures.py`가 담당하며 Ansible을 import하지 않는다.
시험은 공개 CLI를 호출하고 localhost Playbook의 등록 결과를 JSON 파일로 기록한다.
`failed_when_result`와 `failed`의 boolean 타입·기대값, 실제 grep rc·개수를 검사한다.
표현식 오류·누락 결과는 ERROR이며 예상 음성시험 PASS로 처리하지 않는다.
14개 관찰을 모두 수집한 뒤 최종 assert와 실행기 양쪽에서 실패를 반환한다.
`regression.yml`, `ssh-guards.yml`, `source-vars.json`과 fixture 생성 계약은 유지된다.
export 결과는 절대 fixture 경로를 포함하므로 실행할 호스트에서 생성해야 한다.
실행 중에는 전용 결과 디렉터리를 사용하고 동시에 재사용하지 않는다.
원격 실행기의 기존 `_expressions` 단계/JSON 파일명은 `_cli_guards`로 이관했다.
export의 `result-*.json`·`regression.log`는 합성 fixture 실행 결과이며,
stdout 문구 파싱이나 Ansible 내부 Python API는 로컬 판정에 사용하지 않는다.

실제 서버 검증은 ansible01의 `server01_ansible` 사용자로 실행한다.
배포 패키지의 `run-server-verify.sh`가 독립 2.21.3 venv를 준비하고 아래 실행기를 호출한다.

```bash
python3 scripts/verify-ssh-main.py --python221 /absolute/venv/bin/python --output /absolute/new-results
```

시스템 Ansible은 2.16.19인지 확인하며, 별도 2.21.3과 같은 절차를 비교한다.
기존 `/home/server01_ansible/.ssh/p1_ansible_ed25519`와 `known_hosts`를 사용한다.
키·host key가 없거나 SSH/sudo가 실패하면 로그를 남기고 해당 엔진의 후속 단계를 중단한다.
암호를 묻지 않으며, 기존 SSH 연결을 재사용하지 않는다.

각 버전에서 수행하는 단계:

1. 공개 CLI 원본 guard 14개 fixture 및 export된 localhost 태스크 재실행.
2. 실제 6대 전체의 SSH·Python·sudo, 계정과 호스트 일치 확인.
3. 기존 authorized_keys의 소유자·그룹·0600 모드 확인.
4. 수정한 원본 검사 태스크 2개 실행: 관리 키 1개, 제한된 키 1개 확인.
5. 파일의 전후 SHA-256·mtime·권한·소유자 일치 확인.
6. 수정한 hardening Playbook을 `--check`로 실행. 백업 등 변경 예상값은 별도 기록.
7. 기존 main의 OS precheck와 DNS verify를 실제 노드에서 실행.

SSH 검증에서 키가 이미 `from="10.250.10.10",restrict`로 제한돼 있지 않으면
자동으로 수정하지 않고 실패를 기록한다. 실제 파일 내용은 출력하지 않으며,
수정 Playbook의 copy/replace 단계도 check mode로만 실행한다.
Ansible 전송용 임시 파일과 시스템 접속 로그는 정상적으로 발생할 수 있다.

결과 해석:

- `PASS_READONLY_SCOPE`: 두 엔진의 모든 단계가 정상 완료됐으며 원격 단계는 6대 전체 recap까지 확인.
- `REVIEW_REQUIRED`: 누락·실패·시간 초과 또는 기대한 6대 전체 결과 부족.
- hardening check의 changed는 예상 변경이며 실제 파일 적용을 뜻하지 않는다.
- 이 절차는 실제 SSH·sudo·원본 검사·main의 읽기 전용 검증이다. 설정 적용,
  적용 후 멱등성, DNS Rollback, 운영 Ansible 버전 전환 승인은 포함하지 않는다.
- PR #3의 Gate 0 코드는 이 변경과 검증 범위에 포함하지 않는다.


두 엔진 격리 회귀·결함 재주입 (#6)
--------------------------------

Linux와 grep, Python 3.12, PyYAML 6.0.2를 사용한다. 아래 설치는 개발용 venv에만 수행한다.

```bash
python3.12 -m venv /tmp/ssh-216
python3.12 -m venv /tmp/ssh-221
/tmp/ssh-216/bin/python -m pip install ansible-core==2.16.19 PyYAML==6.0.2
/tmp/ssh-221/bin/python -m pip install ansible-core==2.21.3 PyYAML==6.0.2
/tmp/ssh-216/bin/python tests/run-ssh-guard-matrix.py \
  --python216 /tmp/ssh-216/bin/python \
  --python221 /tmp/ssh-221/bin/python \
  --output /tmp/new-ssh-matrix
```

출력 디렉터리는 새 경로여야 한다. 각 엔진에서 baseline 14개를 검사하고,
각 guard에 OR→AND, 잘못된 목록의 독립 `or`, undefined 표현식을 별도로 주입한다.
AND는 FAIL, 표현식 오류는 ERROR를 적어도 하나 발생시켜야 하며,
수정하지 않은 guard의 7개는 모두 PASS여야 한다. 엔진 부재는 결함 검출 성공이 아니다.
두 baseline의 기대·관찰 결과가 같고 총 14회 실행이 계약을 충족해야 MATRIX.json이 PASS다.
이 시험은 원본 hardening Playbook 전체나 서버 검증 실행기를 실행하지 않는다.

호스트 독립 시험:

```bash
python -m unittest discover -s tests -p test_ssh_guard_harness.py -v
```

이 단위시험의 subprocess 대체 결과는 실제 엔진 PASS 증거가 아니다.
실제 두 버전 로그와 결함 재주입 결과, 독립 리뷰를 확보하기 전에는 #6을 Done으로 판정하지 않는다.
원본 실행 증적의 정식 편입은 fds-project-evidence에서 별도로 관리한다.
