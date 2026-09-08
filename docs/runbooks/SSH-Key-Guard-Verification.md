SSH 키 조건식 수정 및 실제 서버 검증
===================================

main의 `harden_svc_ansible_key.yml`에서 `failed_when` 목록에 독립된 `or`를
작성해 키 개수 검증을 건너뛰거나 표현식 오류가 발생하던 문제를 수정한다.
최초·최종 검사를 각각 단일 OR 표현식으로 변경한다. 키 경로, 제한 옵션,
교체 정규식, 백업 방식은 기존과 같다.

로컬 회귀 시험:

```bash
python3 tests/test-ssh-key-guards.py --output /tmp/ssh-guard-test.json --export-dir /tmp/ssh-guard-generated
ansible-playbook -i localhost, /tmp/ssh-guard-generated/regression.yml
```

빈 파일, 제한 전 키 1개, 제한된 키 1개, 각각의 중복, 혼합, 파일 부재를
두 원본 검사 태스크에 적용한다. 14개 사례의 기대 결과는 fixture 계약으로
정의한다. 혼합 입력은 최초 검사에서 차단된다. 최종 검사만 단독 평가하면
제한된 키가 1개이므로 통과하는 것이 해당 검사 범위의 기대값이다.
localhost Playbook은 예상한 실패를 rescue로 기록하고, `failed_when_result`
값까지 검사해 정상적인 실패와 표현식 오류를 구분한다.

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

1. 원본 조건식 14개 fixture 및 localhost 원본 태스크 14개 회귀 시험.
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
