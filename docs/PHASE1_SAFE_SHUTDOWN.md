# Phase 1 팀 전체 정상 종료·교육장 보관 절차

작성 기준: 2026-10-10 KST. **코드 작성·검증용 산출물이며 실제 17대 종료는 미실행**이다. 코드 독립 리뷰·병합과 실제 종료 회차의 Lead 판단은 별개다. 원본 데이터·컨테이너·설정·보안 통제를 유지하며 Windows 물리 PC 전원 종료는 자동화하지 않는다.

**Chrome 원격 데스크톱을 유지하기 위해 server01~server08 호스트 PC는 켜 둔다.** 종료 대상은 게스트 VM뿐이다. Windows 실행 경계는 VMware의 VM 목록/Tools 확인과 명시적 `.vmx`의 `soft` 종료만 허용한다. Windows shutdown/Stop-Computer/재부팅/절전 및 VMware hard stop은 사용하지 않는다. 관리 VM 두 대도 호스트 PC가 아닌 게스트다.

사용자 확인에 따라 원격 접속 방식은 Chrome 원격 데스크톱이다. 호스트의 원격제어 서비스와 인터넷 연결을 유지하며, 이 도구는 해당 서비스나 호스트 네트워크 설정을 변경하지 않는다. Chrome 원격 데스크톱에는 [인터넷 연결이 필요하다](https://support.google.com/chrome/answer/1649523?hl=ko). 호스트 인터넷 경로가 종료 대상 게스트의 VPN/게이트웨이에 의존하는지는 아직 확인하지 않았으므로 실제 종료 전 확인한다. 의존성이 있으면 그 게스트를 유지하는 별도 종료 계획을 검토한다.

자원 기준은 [Baseline v3.1.21 §§6.1·6.3·6.4](https://github.com/321Team/fds-project-baseline/blob/151a60536e6c18a9f6f3b0a1d20bf61db950b763/baseline/FDS_Project_Implementation_Baseline_v3.1.21.md)이다. 10.1.93.56 Egress는 Phase 1 변경결정을 반영한다. 기준 자원과 **현재 VM의 실제 신원·서비스 설정은 구분**하며 실행 전 별도로 측정한다.

## 대상과 고정 순서

전체 서비스 중단을 전제로 하는 제안 절차다. 평상시 부분 재시작·롤링 유지보수용으로 사용하지 않는다. 물리 PC는 VM 수신 담당을 나타내며 Windows 계정명으로 추정하지 않는다.

| 단계 | 순서 / 대상 / 서비스 주소 | 물리 PC |
|---|---|---|
| 1 consumers | cicd-runner01 10.250.10.20 → edge01 10.1.93.50 | server01 / server08 |
| 2 workers | worker01 .105 → worker02 .107 → worker03 .108 | server05 / server06 / server07 |
| 3 control-plane | control03 .104 → control02 .103 → control01 .102 | server04 / server03 / server02 |
| 4 data | db01 .55 → harbor01 .54 | server08 |
| 5 observation | monitor01 10.250.10.30 → egress-proxy01 .56 | server01 / server08 |
| 6 infrastructure | k8s-api-lb01 .109 → dns02 .53 → dns01 .52 | server01 / server08 / server01 |
| 7 management | ansible01 10.250.10.10 → mgmt-gw01 10.250.10.1 | server01 (Windows에서 마지막 실행) |

축약된 .주소는 10.1.93.0/24이다. mgmt-gw01의 물리망 주소는 .58이고 관리 SSH 대상은 10.250.10.1이다. **17대**이며 10.1.93.51 Phase 2 VPN, .57/.59/.106 예약 주소, 오프라인 CA 자산, Harbor 격리 시험 사본은 포함하지 않는다. 이미 보관한 Harbor 시험 사본을 운영 harbor01 대신 지정해서는 안 된다. 별도 CA/Phase 2 VM 등이 켜져 있으면 해당 소유자가 따로 종료·보관한다.

중앙 담당은 이권욱, VM 신원 측정·전원 관측은 각 물리 PC 사용 담당, 업무 중단·복구 자료 확인은 해당 서비스 담당이 수행하는 안이다. 새로운 담당자 권한이나 팀 정책을 부여하지 않는다.

## 실행 전 반드시 확보할 입력

1. 전체 서비스 중단·타 세션 비중첩·CI dispatch 중지 기록. 정상 Runner Listener/Worker/서비스 및 CI 컨테이너를 기존 회수 절차로 먼저 정리한다. 이 도구는 Runner 강제 종료·작업 취소·컨테이너 삭제를 하지 않는다.
2. 앱/모니터링의 복원 가능한 업무 중단 기록(원 replica 수·설정 및 재개 담당 포함). 도구가 임의 scale/delete/drain하거나 PDB를 무시하지 않는다. control01에서 첫 전체 preflight가 비시스템·비DaemonSet 실행 Pod가 없는지 읽어 확인한다. 시스템 namespace/DaemonSet 예외는 업무 중단 증명 자체가 아니므로 예외에 앱이 있으면 담당자가 함께 중단해야 한다.
3. etcd·DB·Harbor의 승인된 복구 자료 참조와 최신 보관 위치. **참조 문자열은 백업 검증/복원 시험 PASS가 아니다.** 데이터 담당이 백업 무결성·필요한 복구 가능성을 확인하고 회차 기록에 연결한다. 이 스크립트가 새 백업·복원 시험을 수행하지 않는다.
4. 17개 VM의 실제 `hostname`, `/etc/machine-id`, 정상 SSH 계정, VMX 절대 경로, VMX `uuid.bios`, 각 Windows의 `$env:COMPUTERNAME`. DB의 실제 PostgreSQL service unit/psql 위치도 확인한다. 암호·개인키·Token은 JSON에 넣지 않는다. 원본 파일은 읽기만 한다.
5. Linux ansible01에서 승인된 SSH 키/known_hosts와 정상 계정의 sudo, 승인된 Ansible 엔진 2.16.19 또는 2.21.3의 기존 절대 경로. `--ssh-key-file`은 실행자 소유의 기존 기본 키를 명시한다. 다른 기존 키가 필요한 대상은 비공개 binding의 `ssh_key_file`에 controller의 절대 경로를 기록한다. 키 내용은 읽거나 증적에 복사하지 않는다. 도구는 새 계정·키·sudo 정책·SSH 예외를 만들지 않는다. 암호가 필요하면 `--ask-become-pass`로 **터미널에서만** 입력한다.
6. 각 PC에 설치된 VMware Workstation/vmrun, 관리 VM의 VMware Tools, 회차 JSON의 승인된 비공개 전달 경로. 기존 승인된 팀 보관처를 사용할 수 있으나 SMB ACL과 원본 접근 권한을 유지한다. 새 공유/방화벽/게스트 공유폴더/마운트는 만들지 않는다. 다른 PC 자료를 server01로 모으고 기존 SSH stdin 전달을 사용할 수 있다.

공개 템플릿은 `docs/examples/phase1-shutdown-bindings.template.json`이다. 측정값과 회차 기록은 체크아웃 밖의 비공개 사본에 작성한다. 빈 입력/추정값으로 실행하지 않는다. 템플릿은 빈 신원·false 확인값 때문에 실행이 거부된다. Linux 입력은 실행자 소유 0600, 디렉터리는 0700이어야 한다. Windows는 운영자가 승인된 사용자만 읽고 쓸 수 있는 ACL을 확인해야 한다(도구가 ACL을 자동 인증하지 않는다).

## 자동 차단 조건

- 신원·IP·물리 PC·고정 순서·소스 SHA·회차 digest 불일치, root 직접 SSH 또는 측정 계정 외 sudo.
- kubelet의 실제 PID/사용 config 불일치, 명시적 초 단위 `shutdownGracePeriod`/`shutdownGracePeriodCriticalPods` 미설정·0·역전, GracefulNodeShutdown 비활성, logind 유예 부족 또는 해당 kubelet PID의 shutdown delay inhibitor 부재. **기본값 0에서는 정상 Pod 종료를 보장할 수 없어 HOLD**한다. 2m 등 다른 형식도 이 버전에서는 해석을 추정하지 않고 HOLD한다. 통과를 위해 설정을 자동 바꾸지 않는다. 필요한 경우 별도 변경·리뷰 후 새 회차로 진행한다. [Kubernetes 정상 노드 종료](https://kubernetes.io/docs/concepts/cluster-administration/node-shutdown/)
  logind의 실제 inhibitor PID·mode와 유예 속성은 [systemd D-Bus 원본 문서](https://github.com/systemd/systemd/blob/main/man/org.freedesktop.login1.xml)의 `ListInhibitors`/`InhibitDelayMaxUSec` 인터페이스로 확인한다.
- Runner/빌드/스캔 프로세스·컨테이너, Edge/Harbor 80·443 ESTABLISHED 연결, DB 외부 client backend 세션이 남음.
- DB unit이 active/loaded가 아니거나 정지 timeout에 SIGKILL을 보낼 수 있음. 정상 `systemctl stop` 후 inactive/dead 확인 실패. PostgreSQL 버전/위치는 실제 입력으로 확인한다.
- Harbor 컨테이너가 정확한 10개와 다르거나 기존 복구/자동기동 manager unit이 발견됨. **새 Harbor manager와 이 스크립트를 동시에 사용하지 않는다.** 담당 세션의 검토된 HOLD·graceful stop 계약을 통합하기 전에는 Harbor 단계가 차단된다. 기존 단순 Compose 자원에만 적용한다.
- Linux 종료는 `systemd-run`의 일회성 5초 timer에서 정상 `systemctl poweroff`를 요청한다. 정상 응답은 요청 확인일 뿐 전원 종료 PASS가 아니다.
- Harbor는 nginx부터 앱을 역순으로 정상 정지하고 harbor-log를 마지막에 정지한다. `docker stop --timeout -1`은 image의 StopSignal을 존중하고 daemon의 timeout SIGKILL을 막는다. 각 컨테이너 비실행·OOM 없음·종료코드 0/130/143을 확인한다. 클라이언트의 120초 대기는 서버 작업 취소가 아니다. [Docker stop](https://docs.docker.com/reference/cli/docker/container/stop/)
- Windows 관측은 고정 VMX UUID + 현재 vmrun 목록에서 부재 + 최신 vmware.log의 cleanShutdown/PoweredOff/VMX exit 0 + suspend 파일/체크포인트 부재를 요구한다. **SSH 끊김·vmrun 목록 부재만으로는 PASS하지 않는다.** 로그가 없거나 VMware 버전의 형식이 다르면 UNKNOWN으로 멈추고 사람이 콘솔·로그를 확인한다.
- receipt는 해당 회차/신원과 일치하고 5분 이내여야 한다. 향후 시각·이전 회차·예전 기록은 거부한다. 각 다음 VM 직전에 선행 VM의 최신 OFF를 다시 확인한다. NTP 서버 control01은 control-plane의 마지막에 종료하며 이후 PC/서버 시각 드리프트도 확인한다.

## 1. 계획 생성 — 서버 접속/종료 없음

이후 명령의 경로는 **운영자가 확인한 실제 값으로 대체**한다. `/approved/...`는 준비된 경로를 설명하는 표기이며 자동 생성된 설치 경로가 아니다. 체크아웃은 정확한 리뷰·병합 SHA의 깨끗한 상태여야 한다. Python 3.9+가 필요하다.

ansible01의 정상 운영 계정에서:

```bash
umask 077
python3 -B tools/phase1-shutdown.py plan \
  --bindings /approved/private/bindings.json \
  --operation-id p1-shutdown-YYYYMMDD-round1 \
  --state /approved/private/p1-round1
```

`OFFLINE_PLAN_ONLY`와 고정 순서, `POWER_OFF:<회차>:<digest>` 확인문이 출력된다. `plan.json`을 비공개 경로로 각 PC에 전달한다. 계획은 24시간 유효하며 입력/코드 변경 시 새 회차가 필요하다. 모든 PC는 동일 소스 SHA를 사용한다.

## 2. Windows 전원 관측 및 기존 SSH를 통한 결과 전달

각 물리 PC에서 해당 PC 사용자의 PowerShell로 실행한다. Python은 기존 설치의 실제 실행 파일을 사용한다.

```powershell
python -B tools/phase1-workstation.py observe `
  --plan C:/Approved/p1-round1/plan.json --physical-host server01 `
  --receipts C:/Approved/p1-round1/receipts `
  --export C:/Approved/p1-round1/server01-observations.json
```

다른 PC는 `--physical-host server02` 등 실제 값으로 실행한다. 실제 COMPUTERNAME도 plan과 일치해야 한다. `--watch-seconds 3600`은 최대 1시간 5초 간격 관측만 반복한다. 상주 서비스·예약 작업을 만들지 않는다. UNKNOWN이면 종료하지 말고 확인한다. `unmanaged_running_vms`는 대상 밖 VM이므로 자동 종료하지 않는다.

**Linux에 receipt를 최신으로 전달할 경로가 확보되기 전에는 execute하지 않는다.** 공유 경로가 Linux와 Windows에서 이미 승인·연결돼 있다면 그 경로의 원자적 receipt 파일을 사용한다. 그렇지 않으면 각 PC의 export를 server01 비공개 경로로 모은 뒤 기존 `fds-ansible01` SSH 별칭으로 전달한다. Windows에 JSON을 담은 임시 공유폴더를 추가할 필요는 없다.

PowerShell 5.1에서도 UTF-8 stdin을 정확히 전달하는 예시:

```powershell
$py = @'
import pathlib, subprocess
payload = pathlib.Path(r'C:/Approved/p1-round1/server01-observations.json').read_bytes()
cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', 'fds-ansible01',
       'python3 -B /approved/infra-ansible/tools/phase1-shutdown.py receive --state /approved/private/p1-round1 --receipts /approved/private/p1-round1-receipts']
raise SystemExit(subprocess.run(cmd, input=payload).returncode)
'@
$py | python -B -
```

다른 PC의 export도 파일명을 바꾸어 각 단계에서 새 관측을 전달한다. 단독 작업창을 유지하며 대상 VM을 도중에 기동하지 않는다. Linux `receive`는 별도 lock을 사용해 `execute`의 대기 중에도 수신한다. `RECEIPTS_IMPORTED_ONLY`는 전달 완료이며 종료 판정이 아니다. 오래된 입력으로 최신 관측을 덮어쓰지 않는다.

## 3. 전체 17대 읽기 preflight

관리 VM을 포함한 전체 대상의 신원·역할 점검을 먼저 실행한다. 이미 정상 OFF가 새 receipt로 확인된 VM은 접속을 시도하지 않고 외부 종료 확인 상태로 기록한다. 전체 점검이 끝나기 전에 한 대도 종료하지 않는다.

```bash
python3 -B tools/phase1-shutdown.py preflight \
  --state /approved/private/p1-round1 \
  --receipts /approved/private/p1-round1-receipts \
  --engine-dir /approved/existing-venv/bin --engine-version 2.21.3 \
  --ssh-key-file /approved/existing-ssh-key \
  --ask-become-pass
```

`READY_FOR_EXPLICIT_PHASE`를 확인한다. 첫 종료 시작은 전체 점검 후 5분 이내여야 한다. 이는 점검 조건을 충족한 기록이며 독립 승인·백업 복원 검증이 아니다. 점검에서 발견한 조건은 기존 담당 절차로 해소하고 재점검한다. 종료 claim이 생긴 뒤에는 전체 preflight를 덮어쓰지 않는다.

## 4. 앞선 종료를 확인하며 한 단계씩 명시 실행

실제 종료는 회차 Lead가 SHA/digest·입력·영향·복구 자료를 확인한 범위에서 실행한다. 이 문서 작성·PR 발행은 Runtime GO가 아니다.

```bash
python3 -B tools/phase1-shutdown.py execute \
  --state /approved/private/p1-round1 \
  --receipts /approved/private/p1-round1-receipts \
  --engine-dir /approved/existing-venv/bin --engine-version 2.21.3 \
  --ssh-key-file /approved/existing-ssh-key \
  --phase consumers --confirm 'POWER_OFF:<operation-id>:<binding-digest>' \
  --wait-seconds 300 --ask-become-pass
```

`consumers → workers → control-plane → data → observation → infrastructure` 순서로 **명령을 한 개씩** 실행한다. 각 대상의 최신 점검→지속 보존 intent→정상 종료 요청→외부 OFF receipt 순서다. 단계마다 `PHASE_EXTERNALLY_CONFIRMED_OFF`를 확인한다. Windows의 새 export를 계속 전달해야 한다. 한 명령은 해당 단계만 진행하며 다음 단계를 자동 실행하지 않는다.

control03/02 종료로 etcd quorum을 잃는 전체 중단 절차이므로, control01의 마지막 종료 때 Kubernetes API를 다시 요구하지 않는다. 업무 Pod의 전체 확인은 중단 전 전체 preflight에서 수행하고, 이후 CI/앱 재개·다른 작업이 없는 단독 작업창을 유지한다. 앱 재개나 VM 재기동이 발생하면 HOLD한다.

## 5. 중앙 결과 보관 후 Windows에서 관리 VM 두 대 종료

6단계가 끝나면 `plan.json`, `preflight.json`, 여섯 개의 `<phase>.result.json`, 대상별 원본 결과·intent·최신 receipt를 server01의 승인된 비공개 보관처로 복사하고 해시를 대조한다. 중앙 제어 VM을 끄기 전에 원본을 회수한다. 다른 PC의 observer는 관리 VM 종료까지 최신 OFF를 갱신한다.

server01 Windows에서 마지막 정상 종료를 실행한다:

```powershell
python -B tools/phase1-workstation.py finalize `
  --plan C:/Approved/p1-round1/plan.json --physical-host server01 `
  --receipts C:/Approved/p1-round1/receipts `
  --central-handoff C:/Approved/p1-round1/central-handoff `
  --state C:/Approved/p1-round1/windows-state `
  --confirm 'POWER_OFF:<operation-id>:<binding-digest>' --wait-seconds 300
```

앞선 15대의 최신 OFF와 여섯 단계 결과를 요구하며, Tools running일 때만 **ansible01 → mgmt-gw01**을 `vmrun stop ... soft`로 한 번씩 정상 종료한다. 17대 전체의 최신 receipt가 있어야 `ALL_17_EXTERNALLY_CONFIRMED_OFF`를 보존한다. 한 대라도 확인하지 못하면 HOLD한다. server01의 대상 밖 VM이 남아 있으면 소유자의 별도 처리가 필요하며 물리 PC 전원을 자동으로 끄지 않는다.

## 실패·중단·재개와 보관

- CLI 종료코드 0은 해당 계획/읽기/전달/단계 결과 성공, 2는 HOLD다. Ansible/SSH/VMware 응답 실패·기한 초과·부분 정지 시 **다음 VM으로 진행하지 않는다**. 성공 범위는 각 결과로 구분한다.
- `/run/fds-phase1-shutdown-<boot-id>.intent`와 controller/Windows의 `<resource>.intent.json`은 실패 시에도 보존하며 자동 삭제하지 않는다. Linux는 같은 부팅의 게스트 claim도 확인하고, Windows 최종 종료는 동일 회차의 공유 state claim을 사용한다. 회차의 state 경로를 복제/변경하여 claim을 우회하지 않는다. 읽기/이미 정상 OFF의 재확인은 가능하지만 UNKNOWN인 동일 stop을 재전송하지 않는다.
- timer/서비스/Docker/backend에 이미 제출한 요청은 CLI timeout이나 Ctrl+C로 취소할 수 없다. 실제 상태를 콘솔·로그·vmrun으로 확인한 뒤 담당 Lead가 부분 복구를 판단한다. 강제 종료·kill·compose down/-v·prune·데이터 삭제·보안 예외를 사용하지 않는다.
- 자동 역순 재기동은 구현하지 않는다. 관리/경로→DNS/NTP→DB/Harbor→LB/etcd control-plane→workers→관측→Edge/Runner 의존성을 서비스 담당이 확인하고 기존 기동·복구 절차와 정상 판정을 따른다. Harbor는 삭제하지 않은 컨테이너의 기존 manager/기동 계약을 따르며 원본 claim을 지워 재시험하지 않는다.
- 교육장 보관은 정상 Powered Off 후 VMX/VMDK 전체 체인·필요한 NVRAM/스냅샷 자료를 복사하고 파일 수/용량/SHA256·디스크 체인을 별도 확인한다. shutdown PASS를 보관·복원 시험 PASS로 확대하지 않는다. 기존 자원 회수기간·승인된 보관처·인수 책임을 유지한다.

## 검증 범위

`python3 -B -m unittest discover -s tests -p test_phase1_shutdown.py -v`는 합성 fixture를 사용하며 SSH/systemctl/Docker/vmrun을 실행하지 않는다. 작성자의 STATIC/MOCK와 독립 REVIEW는 구분한다. Ansible syntax/CI도 실제 환경 정상 종료·재기동·데이터 복원의 증거가 아니다.

이 버전의 실제 Runtime은 NOT RUN이다. 운영 전 측정 bindings·Kubelet 유예·DB unit 정지 정책·Harbor owner 연계·최신 전원 관측/전달이 필요하다. 현행 설정이 미확인인 대상을 추정으로 READY로 표시하지 않는다.
