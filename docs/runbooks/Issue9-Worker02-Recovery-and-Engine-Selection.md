# Issue9 — worker02 복구 및 운영 엔진 선택 준비 v1.0

기준 source: 5454b77d508cdbfd0eef13e489cbc0322d11c653. 책임 [Issue9](https://github.com/321Team/infra-ansible/issues/9).
단계: DESIGN_ONLY. 신규 운영 복원 도구/배포 명령이나 wrapper 변경을 포함하지 않는다. AI usage: CODEX_ASSISTED.

## 현재 검증의 적용 범위

- worker02 2.21.3 실제 apply2회/changed0, 신규 SSH, 키/OS/DNS 사후 비교 PASS (evidence PR113).
- 로컬 Python fixture7사례 PASS (이 PR의 스크립트).
- 별도 현장 shell 합성파일 시험: 사용자 2026-10-05 03:20 KST 콘솔. /var/tmp/issue9-restore-metadata.lWTROYLy에서 0:0/0644/system_u:object_r:tmp_t:s0 → 1001:1001/0600/unconfined_u:object_r:ssh_home_t:s0, RESTORE1/2 PASS, rc0. 실제 authorized_keys는 문맥 참조만 수행. 원본 로그파일 미수신이며 로컬 Python fixture 실행 결과로 전용하지 않음.
- 실제 운영 authorized_keys 복원, 복원 뒤 신규 SSH, 전체 role 복구, 운영 엔진 전환은 NOT_RUN.

## 실제 키 복구의 고정 입력

| 항목 | 값 |
|---|---|
| 대상 | k8s-worker02 / 10.1.93.107, 단일 호스트 |
| 정상 접근 | ansible01/server01_ansible → svc_ansible, source10.250.10.10, strict host-key, 기존키 |
| 연결 실패 시 접근 | 사용자 확인한 worker02 VMware 콘솔에서 관리자 복구 |
| 복구 원본 | /var/lib/ansible-issue9-worker02.NXrcqAmF/authorized_keys |
| 목적지 | /home/svc_ansible/.ssh/authorized_keys |
| SHA256 | b7923e8c646b7a7dd2ccba1ac48ddf02d264780db9100317644dcf87216cc834 |
| uid/gid/mode | 1001:1001 / 0600 |
| SELinux 문맥 | unconfined_u:object_r:ssh_home_t:s0 |
| 이후 비교 | 신규 SSH, OS CentOS10/Python3.12.14/Enforcing, resolver hash c452a6013b82f5daeec71cbe4234dc696f9e4948197866ac74788285d934827e, k8s-api →10.1.93.109 |

NXrcqAmF는 실제 키 백업이다. lWTROYLy는 합성 fixture이며 실제 복구 원본으로 절대 사용하지 않는다. 오래된 .pre-p1-restrict도 이번 복구 원본이 아니다.

## 복구 실행 자료가 보장해야 할 순서

1. host/계정·복구 대상1대·콘솔 가용성·동시 변경 여부와 backup hash/uid/gid/mode/context 확인. 링크/부모 경로 변경·비정규 파일·예상 밖 소유권은 중단한다.
2. 목적지의 현재 hash와 metadata를 기록하고 실패/변경 원인에 연결. 백업 이후 정상적인 변경이 있었다면 오래된 사전값으로 자동 덮어쓰지 않는다.
3. 목적지와 같은 파일 시스템의 보호된 임시 경로에 원본을 보존 속성과 함께 복사하고 hash 및 metadata를 검증한다. /var/tmp에서 목적지로 cross-filesystem mv하는 방식을 원자 교체로 오인하지 않는다.
4. 교체 직전 목적지 drift를 재확인한다. 검사/교체 사이의 경쟁 조건과 하드링크·부모 경로 취급은 운영 도구의 별도 검토 대상이다. 로컬 fixture는 이 보안 경계를 보장하지 않는다.
5. 검증한 staged 파일을 원자 교체하고 최종 hash/metadata를 검사한다. 파일·디렉터리 fsync 등 전원 손실 내구성 요구와 실패 동작은 운영 구현 시 명시한다.
6. 기존 연결을 재사용하지 않는 신규 SSH로 접근·키 제한·OS/DNS 확인. 실패 시 대상 확대 중단, 콘솔 복구와 최종 상태를 기록한다.
7. 이력이 보존될 때까지 이번 백업은 삭제하지 않는다. 무조건적인 restorecon으로 기존 문맥을 다른 값으로 바꾸지 않고 고정된 기대 문맥과 비교한다.

현재 키와 백업은 동일하다. 동일 상태 덮어쓰기는 운영 경로의 복사/교체 연습일 수 있으나 실제 실패 상태 복구를 입증하지 않는다. 시험 목적으로 restrict 제거·유효키 삭제·연결 고의 단절은 계획에 포함하지 않는다. 복구가 필요한 실제 drift 또는 별도로 승인된 안전한 시험 범위가 없으면 현재 운영 키는 유지한다.

## wrapper별 엔진 전환 영향 (고정 source 정적 조회)

| 진입점 | 엔진 연관 CLI | 보존할 제어 |
|---|---|---|
| cr-p1-ans-01-01-run.sh | ansible-playbook | CR 승인, control-plane/workers/rollback 범위, 출력/실패 전파 |
| cr-p1-mon-01-01-run.sh | ansible-playbook, ansible-inventory | 실제 재적용 recap와 inventory host 집합 동일성, proxy clients 확인, CR 승인 |
| cr-p1-ntp-01-01-run.sh | ansible-playbook; 별도 python3 잠금 도구 | 전체 작업 잠금 FD, source/vars binding, NTP 승인/STOP |
| p1-k8s-01-gate0-run.sh | ansible-playbook, ansible, ansible-config | syntax 직접 호출과 run/check/finalize 엔진 일치, ansible/tee rc 별도 기록 |

현재 CLI는 PATH 선택이다. worker02 canary의 절대 경로 실행 성공을 이 네 wrapper의 전환 성공으로 간주하지 않는다. DNS/MON/NTP wrapper는 범용 단일 호스트 --limit 인터페이스가 아니므로 worker02 canary를 그대로 대입하지 않는다. 기존의 NTP check-mode 재검사는 실제 재적용 멱등성과 구분한다.

## 권장 최소 변경 설계 — 미구현

- 전역 PATH·RPM 교체 없이 명시적 opt-in 엔진 디렉터리 입력을 제공한다. 미지정 시 기존 선택 동작을 보존하고 기존 동작 변경은 별도 승인한다.
- 후보: /home/server01_ansible/ansible-candidate.8oCqVUwx/result/runtime/venv-2.21.3/bin.
- ansible-playbook뿐 아니라 필요한 ansible-inventory/ansible/ansible-config를 동일 디렉터리에서 선택한다. 하나가 없거나 버전이 어긋나면 PATH fallback 없이 중단한다.
- 실제 executable/버전/config/module 경로를 실행 로그에 기록한다. finalize 시점 엔진 정보가 과거 실행 엔진을 대체하지 않게 한다.
- NTP lock용 python3는 엔진 선택과 분리한다. 후보 venv의 Python으로 잠금 경로를 무심코 치환하지 않는다.
- restrict 대상은 ANSIBLE_SSH_USETTY=false 등 검증된 비PTY 설정을 실행 범위에 명시한다. sudoers/SSH 보안 제약을 완화하지 않는다.
- 엔진 복귀는 opt-in 해제 및 실제 기존 CLI 경로/버전 확인이다. 변경된 대상 파일 상태는 별도 복구해야 한다.
- 적용 전 mock CLI 회귀에서 네 wrapper의 모든 관련 CLI 선택, 잘못된 경로/누락/버전 불일치, 실패 전파, 기존 CR/잠금/source 통제 보존을 확인한다. 실제 두 엔진 및 role별 Runtime 범위는 따로 검증한다.
- 변경 코드는 별도 일반 코드 PR로 검토한다. 이 Pre-check PR을 운영 코드 승인으로 확대하지 않는다.

## 다음 작업

현재 운영 키와 기본 엔진은 유지. 우선 위 opt-in 선택 설계에 따라 최소 wrapper 변경·회귀 시험을 준비한다. 운영 배포 전 exact SHA 검토와 적용할 action/대상/복구 조건을 연결한다. 기존 read-only 수집·canary 적용·합성 시험은 변경 영향이 없는 한 반복하지 않는다.
