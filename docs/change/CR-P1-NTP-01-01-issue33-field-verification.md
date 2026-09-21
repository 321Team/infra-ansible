# 이슈 #33 kernel topology STOP receipt — 실서버 검증 가이드

상태: **가이드 작성만 완료 / 실제 서버 실행 NOT RUN.**
이 문서를 작성한 사실은 실서버 검증, 이슈 #33 종결 또는 CI PASS가 아니다.
아래 명령은 실제 접근 권한을 가진 담당자가 판단 후 직접 실행한다.

## 목적과 범위

- [PR #36](https://github.com/321Team/infra-ansible/pull/36)(병합 `0f9f9440e2b8fe46d5a10d2e3c3d177e2dcbbd71`)에서
  `tools/ntp-onepass-remote.py`의 `kernel_topology()`가 실패 시 `family`, `table`, `stage`,
  `connection_form`, `expected`/`actual`, 크기 상한 원문(`raw`)을 `details['kernel_topology']`에
  남기도록 바뀌었다.
- 이 가이드는 **그 진단 코드 경로가 실제 6대 호스트의 커널/firewalld 상태를 대상으로
  예외 없이 동작하는지**만 확인한다. 이 범위를 벗어나는 것은 다루지 않는다:
  - `egress`/`verify`/`rollback_egress` 경로에서의 진단 필드 동작 (별도 검증 필요)
  - 실제 STOP 상황에서 receipt 필드의 정확성 (LOCAL/MOCK 53/53 PASS로만 검증됨, PR #36 참조)
  - CI (이 저장소에 활성 Workflow 없음, 이슈 #5 별도 추적)
  - 이슈 #37의 `BASE_SHA256` 재승인

## 사전 조건

1. PR #36이 독립 리뷰·승인·병합된 상태([review 5264401539](https://github.com/321Team/infra-ansible/pull/36#pullrequestreview-5264401539),
   [review 5264465944](https://github.com/321Team/infra-ansible/pull/36#pullrequestreview-5264465944) 모두 APPROVED, 병합 완료).
2. 실행자는 기존 controller 계정 `server01_ansible@ansible01`, 기존 SSH 키
   `/home/server01_ansible/.ssh/p1_ansible_ed25519`, 기존 `known_hosts`, ansible-core 2.16.19
   환경을 그대로 사용한다. 이 문서는 새 계정·새 키·새 권한을 요구하지 않는다
   ([field-runbook](CR-P1-NTP-01-01-field-runbook.md)와 동일 전제).
3. 대상 6대 호스트(`k8s-control01`~`03`, `k8s-worker01`~`03`)는 이미 CR-P1-NTP-01-01 egress 구성이
   적용되어 있다고 가정한다. 이 문서는 새로 적용하지 않는다.
4. `tools/ntp-onepass.py`의 `OnePass.remote()`가 실제 운영에서 사용하는 전송 방식(검토된 소스
   전체를 인라인 `exec`해 `ansible.builtin.command` + stdin으로 전달)과 **동일한 구조**를 아래에서
   최소 형태로 재현한다. 다만 다중 호스트 orchestrator(controller 잠금, `--input` 승인 JSON,
   ingress/egress 적용 순서)는 사용하지 않는다 — 이번 확인은 상태를 바꾸지 않는 `snapshot`
   action 하나만 필요하기 때문이다.

## 왜 `snapshot` action인가, 그리고 무엇을 하는지 정확히

`tools/ntp-onepass-remote.py`의 액션 중 `snapshot()`은:

1. 호출될 때마다 `self.topology()` → `self.kernel_topology()`를 실행한다 — 이번에 바뀐 진단
   코드 경로를 항상 지나간다.
2. `firewall-cmd --list-all-zones` 등 조회, `nft list ruleset`, `iptables-save`/`ip6tables-save`,
   `chronyc tracking`/`sources`, 관련 설정 파일 읽기 등 **읽기 전용** 명령만 실행한다.
   규칙 추가/삭제, `--reload`, 서비스 재시작, 패킷 전송은 **하지 않는다**.
3. 매 호출은 새 `run_id`로 실행되며, 그 `run_id` 전용 journal 파일
   (`/var/lib/fds-ntp-onepass/<run_id>/state.json`, root 소유 0700)을 새로 생성한다.
   **"기존 snapshot 재사용"은 같은 `run_id`를 다시 쓸 때만 일어난다** — 이 문서는 매번 새
   `run_id`를 쓰므로 매번 전체 읽기 전용 수집이 실행된다. 실제 방화벽/NTP 상태는 바뀌지 않지만
   "아무 것도 안 한다"고 표현하지 않는다.
4. 호스트별 advisory lock(`/var/lib/fds-ntp-onepass/.lock`, `flock` 비차단)을 잡는다. 같은 호스트에서
   다른 onepass 작업이 진행 중이면 즉시 `Stop('Another onepass action holds the host lock')`로
   실패한다 — 즉 이 확인이 실제 운영 실행과 충돌하면 **조용히 섞이지 않고 명시적으로 거부**된다.

## 실행 절차

### 0. 준비 (한 번만)

검토·병합된 main의 정확한 HEAD로 이동한다.

```bash
cd <reviewed-checkout-root>   # tools/ntp-onepass-remote.py 포함
git fetch origin main
git checkout main && git reset --hard origin/main   # 담당자 판단하에, 기존 로컬 변경 없는 clean checkout에서만
git rev-parse HEAD
# 기대값: 0f9f9440e2b8fe46d5a10d2e3c3d177e2dcbbd71 (또는 그 이후 별도 검토·병합된 HEAD)
git status --short   # 반드시 빈 출력
python3 -c "import hashlib; print(hashlib.sha256(open('tools/ntp-onepass-remote.py','rb').read()).hexdigest())"
# 기대값: 28e59bfd517661439f2a2c794824b0d19de3218e5101e143656ff5a865e3f1b2
```

두 값이 다르면 **즉시 중단**한다 — checkout이 리뷰된 HEAD와 다르다는 뜻이다.

`tools/ntp-onepass.py`가 실제로 만드는 것과 동일한 형태의 고정 inventory를 만든다
(호스트별 `ansible_host`는 스크립트의 `HOSTS` 상수와 동일: control01 `.102`, control02 `.103`,
control03 `.104`, worker01 `.105`, worker02 `.107`, worker03 `.108`).

```bash
umask 077
python3 - <<'PYEOF'
import json
HOSTS = {'k8s-control01': '10.1.93.102', 'k8s-control02': '10.1.93.103',
         'k8s-control03': '10.1.93.104', 'k8s-worker01': '10.1.93.105',
         'k8s-worker02': '10.1.93.107', 'k8s-worker03': '10.1.93.108'}
ssh = ' '.join(['-o BatchMode=yes', '-o PreferredAuthentications=publickey',
                 '-o PasswordAuthentication=no', '-o KbdInteractiveAuthentication=no',
                 '-o StrictHostKeyChecking=yes', '-o IdentitiesOnly=yes', '-o IdentityAgent=none',
                 '-o GlobalKnownHostsFile=/dev/null',
                 '-o UserKnownHostsFile=/home/server01_ansible/.ssh/known_hosts',
                 '-o ControlMaster=no', '-o ControlPath=none', '-o ControlPersist=no',
                 '-o ConnectTimeout=10', '-o ServerAliveInterval=10', '-o ServerAliveCountMax=2'])
variables = {'ansible_user': 'svc_ansible', 'ansible_connection': 'ssh',
             'ansible_ssh_executable': '/usr/bin/ssh', 'ansible_python_interpreter': '/usr/bin/python3',
             'ansible_ssh_private_key_file': '/home/server01_ansible/.ssh/p1_ansible_ed25519',
             'ansible_ssh_common_args': ssh,
             'ansible_become': True, 'ansible_become_method': 'sudo',
             'ansible_become_user': 'root', 'ansible_become_flags': '-H -S -n'}
inv = {'all': {'children': {'k8s_nodes': {'hosts': {h: {'ansible_host': ip} for h, ip in HOSTS.items()}}},
               'vars': variables}}
open('issue33-inventory.json', 'w').write(json.dumps(inv))
PYEOF
chmod 600 issue33-inventory.json
```

이 inventory는 실제 `tools/ntp-onepass.py`의 `OnePass.prepare()`(337~344행)가 만드는 것과 동일한
필드를 그대로 옮긴 것이다 — `inventory/hosts.yml`을 신뢰하는 대신, 저장소의 고정 `HOSTS` 상수 값을
직접 사용한다.

### 1. 호스트 하나씩 확인 (한 번에 한 호스트만)

아래 스크립트는 `tools/ntp-onepass.py`의 `OnePass.remote()`(358~377행)가 실제로 만드는 payload와
동일한 구조 — 검토된 소스 전체를 인라인 `exec`한 뒤 `main(request)`를 호출 — 를 그대로 재현한다.

```bash
(
set -euo pipefail
umask 077
export ANSIBLE_PRIVATE_KEY_FILE=/home/server01_ansible/.ssh/p1_ansible_ed25519
export ANSIBLE_STDOUT_CALLBACK=json
HOST="$1"   # 예: k8s-control01
RUN_ID="ntp-issue33-$(date -u +%Y%m%d%H%M%S)-$(head -c4 /dev/urandom | xxd -p)"

python3 - "$HOST" "$RUN_ID" <<'PYEOF' > "command-${HOST}.json"
import json, sys
host, run_id = sys.argv[1], sys.argv[2]
code = open('tools/ntp-onepass-remote.py', encoding='utf-8').read()
request = {"schema_version": 1, "action": "snapshot", "run_id": run_id, "host": host}
payload = ('import json\n_scope = {"__name__": "fds_onepass_remote"}\n'
           + 'exec(compile(' + repr(code) + ', "ntp-onepass-remote.py", "exec"), _scope)\n'
           + 'raise SystemExit(_scope["main"](json.loads(' + repr(json.dumps(request)) + ')))\n')
print(json.dumps({"argv": ["/usr/bin/python3", "-I", "-B", "-"],
                   "stdin": payload, "stdin_add_newline": False}))
PYEOF

ansible "$HOST" -i issue33-inventory.json --become \
  -m ansible.builtin.command -a "$(cat "command-${HOST}.json")" \
  > "response-${HOST}.json"

echo "완료: $HOST, run_id=$RUN_ID, 원본 응답 response-${HOST}.json 저장"
)
```

호출: `bash <위 스크립트를 저장한 파일> k8s-control01` — 이후 `k8s-control02` … `k8s-worker03`까지
**한 번에 하나씩**, 이전 호스트 완료를 확인한 뒤 다음 호스트로 진행한다.

> `command-${HOST}.json`에는 검토된 소스 전체가 문자열로 들어 있어 수십 KB 크기다.
> `-a "$(cat ...)"`로 명령줄 인자에 그대로 펼치면 셸의 `ARG_MAX` 한도에 걸릴 수 있다.
> 실행 전 `getconf ARG_MAX`로 한도를 확인하고, 걸리면 `ansible.builtin.command`를 직접
> 호출하는 대신 최소 ad-hoc playbook(`vars_files`로 이 JSON을 읽어 `command` 모듈에 전달)으로
> 바꿔야 한다 — 이 문서는 그 대체 경로의 정확한 문법까지 검증하지 않았다(NOT VERIFIED).

### 2. 응답 확인

`response-<host>.json`(`ANSIBLE_STDOUT_CALLBACK=json` 결과)에서 실제 원격 stdout을 꺼낸다.

```bash
python3 -c "
import json
r = json.load(open('response-k8s-control01.json'))
task = r['plays'][0]['tasks'][0]['hosts']['k8s-control01']
print('rc:', task.get('rc'))
value = json.loads(task['stdout'])
print(json.dumps(value, indent=2, sort_keys=True))
"
```

정상(성공) 응답의 형태:

```json
{"schema_version": 1, "action": "snapshot", "host": "k8s-control01", "run_id": "...",
 "status": "OK", "changed": false,
 "details": {"snapshot_created": true, "files_sha256": {...}, "created_at": "..."},
 "journal_receipt": {...}}
```

`details`에 `kernel_topology` 키가 **없어야** 정상이다.

## 판정 기준

| 관찰 | 의미 | 처리 |
|---|---|---|
| `status: OK`, `details`에 `kernel_topology` 없음 | 정상 — 진단 코드가 실행됐고 STOP되지 않음 | PASS로 기록, 다음 호스트 진행 |
| `status: STOP`, `error`가 커널 topology 관련 메시지, `details.kernel_topology` 존재 | 실제 운영 topology 이상을 이번에 새로 노출한 것일 수 있음 (이번 PR이 원인을 만든 게 아니라 기존 상태를 더 상세히 보여준 것) | **자동 복구·재실행 시도 금지.** `journal_receipt`와 `details.kernel_topology` 원문을 그대로 보존하고 즉시 보고 |
| `status: STOP`, `error`가 커널 topology와 무관(바인딩/락 실패 등) | 이번 변경과 무관한 사전 조건 문제 | 호스트 상태·권한·동시 실행 여부 재확인 후 재시도 |
| ansible 자체 실패(`unreachable`, timeout) | 전송 실패 | 재시도 전 네트워크/키/known_hosts 확인 |

## 증적 기록

- 각 호스트의 `response-<host>.json`(원본, 가공하지 않음)을 보존한다.
- 6대 전체 완료 후 이슈 [#33](https://github.com/321Team/infra-ansible/issues/33)에 실행 일시, 사용한
  `run_id` 목록, 6/6 PASS 여부(또는 STOP 상세와 원문)를 코멘트로 남긴다.
- 이 절차의 완료만으로 이슈 #33을 Done으로 전환하지 않는다. `egress`/`verify` 경로의 진단 필드
  동작, CI(이슈 #5), 이슈 #37(`BASE_SHA256` 재승인)은 별도로 남는다.

## 알려진 부작용

- 각 실행은 대상 호스트에 새 `run_id` journal 디렉터리(`/var/lib/fds-ntp-onepass/<run_id>/`,
  root 소유 0700)를 남긴다. 기존 CR 적용 상태(`FILES` 목록의 chrony/firewalld 설정, 실제
  방화벽 규칙)는 바꾸지 않는다. 이 문서는 해당 journal 디렉터리의 정리 절차를 정의하지 않는다 —
  필요하면 기존 운영 정리 관행을 따른다.
