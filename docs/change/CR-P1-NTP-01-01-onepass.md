# CR-P1-NTP-01-01 — 방화벽 준비·NTP 전환 단일 실행

상태: **신규 통합 코드 검토용 / 실제 서버 실행 NOT RUN**.
작성 기준: 2026-09-20 KST. 이 문서는 이번 통합 코드의 운영 절차이며,
기존 PR29 승인·병합과 실제 배포·인수를 구분한다.

## 범위와 근거

기존 승인 실행 소스는 PR29 병합 commit
`eb08dc8c4ae3505dace39e76a11ef57be75e96ce`다.
선정 시간원은 `162.159.200.1`, `162.159.200.123`이며,
[기존 선정 결정](https://github.com/321Team/fds-project-baseline/issues/10#issuecomment-5740306915)을
재사용한다. 동일 사업자 의존 수용, control01 내부 단일 source 구조와 기존 AC를 유지한다.

2026-09-20 20:22:37–20:23:58 KST에 수집된 `ntp-network-recovery-w5e5yw5h.tar.gz`
원문은 6대의 chrony·네트워크 원본을 확보했으며 control01의 내부 UDP123 수신 허용과
6대의 최종 NTP 송신 제한이 없음을 보였다. 이는 당시 기준점이며 이번 실행은 변경할
항목을 적용 직전에 다시 확인한다. 수집기의 잘못된 default-zone 옵션으로 표시된
`COLLECTION_INCOMPLETE` 때문에 기존 원문을 폐기하거나 전체 재수집하지 않는다.

새 통합 코드는 control01 수신 준비, 기존 NTP 전환 실행, 전체 전환 성공 후 송신 제한과
증적 포장을 묶는다. 동일 작업창에서 단계별 승인 질문을 반복하지 않는다. 다만 새 코드와
실행 설정은 [기존 리뷰 정책](../REVIEW_POLICY.md)에 따라 정확한 HEAD의 독립 리뷰와
Lead의 병합·운영 실행 판단이 필요하다. 기존 PR29 전체를 재검토할 필요는 없다.

## 한 번 준비할 입력

실행 위치는 `server01_ansible@ansible01`이며 controller를 root로 실행하지 않는다.
기존 Ansible core **2.16.19**, `svc_ansible` 접속·비대화형 become,
`/home/server01_ansible/.ssh/p1_ansible_ed25519` 및 기존 known_hosts를 사용한다.
키·토큰·인증 파일의 내용을 실행 JSON이나 증적에 넣지 않는다.

| 대상 | 주소 | 최종 NTP 목적지 |
|---|---|---|
| k8s-control01 | 10.1.93.102 | 선정 Cloudflare 두 주소 |
| k8s-control02, k8s-control03 | 10.1.93.103, 10.1.93.104 | 10.1.93.102 |
| k8s-worker01, k8s-worker02, k8s-worker03 | 10.1.93.105, 10.1.93.107, 10.1.93.108 | 10.1.93.102 |

입력은 실제 기록을 가리켜야 한다. 상위망·NAT 반환 조건, 적용되는 Calico host 정책의
소유 범위, 기존 pool/DHCP 복구 경로와 작업창 판단을 서버 스크립트가 승인할 수는 없다.
기존 CR의 한 기록에서 해당 항목을 구분하여 연결해도 되며 새 서류나 별도 Support 서명을
추가하지 않는다. `approved: true`, `PENDING`, 예시 URL로 미결 항목을 대신하지 않는다.

사전 기록은 **실제 변경을 수행할 범위·복구 계획**이다. 아직 적용하지 않은 최종 송신 제한,
왕복 경로 시험이나 최종 AC를 완료로 적지 않는다. 당일 원문과 실제 변경 결과는 실행 중
생성되며 그 기록과 기존 결정 참조를 함께 사용한다.

[입력 예제](CR-P1-NTP-01-01-onepass-input.example.json)를 실행 checkout 밖의
본인 소유 일반 파일로 복사해 한 번 작성한다. 기존 파일을 덮어쓰지 않는다.

| 키 | 실제 값과 범위 |
|---|---|
| `reviewed_wrapper_sha` | 신규 통합 코드의 정확한 독립 검토·병합된 전체 HEAD SHA |
| `reviewed_source_sha` | 기존 승인 실행기의 `eb08dc8c4ae3505dace39e76a11ef57be75e96ce` |
| `public_upstreams` | 기존 확정 `162.159.200.1`, `162.159.200.123` |
| `source_policy_ref` | 예제에 있는 실제 기존 선정 결정; 동일 endpoint 결정 재사용 |
| `network_policy_ref` | 이번 정책 변경 범위, 적용 통제 지점·상위망/NAT 반환·전환 시점의 실제 결정 기록 |
| `recovery_ref` | 기존 승인 pool 경로·원본·변경 소유권·복구 순서·성공 host 보존의 실제 계획 기록 |

입력은 위 **6개 키**를 사용한다. 예제의 빈 값은 후보 상태를 표시하며 실행 승인값이 아니다.
기존 rollout의 5개 키 JSON에 신규 `reviewed_wrapper_sha`를 추가하는 관계이나,
실제 참조가 준비되기 전에 빈 두 참조를 그럴듯한 URL로 대체하지 않는다.

통합 코드와 기존 실행기는 **서로 다른 clean checkout**을 사용한다.
통합 코드의 실행 HEAD를 기존 eb08로 적지 않고, 기존 eb08 checkout에 새 파일을 복사하지
않는다. 해시를 알아냈다는 사실은 그 HEAD의 독립 승인 증명이 아니다.

```bash
chmod 600 /home/server01_ansible/ntp-onepass-input.json
```

## 한 번 실행

신규 통합 코드의 검토·병합된 checkout 루트에서, 기존 Ansible 환경을 활성화한 일반
계정으로 실행한다. 아래 기존 실행기 경로는 이번 현장 원문에서 확인된 경로다.
폴더를 이동했다면 `--rollout-repo`에 실제 eb08 clean checkout의 절대 경로를 사용한다.

```bash
(
set -euo pipefail
umask 077
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export ANSIBLE_PRIVATE_KEY_FILE=/home/server01_ansible/.ssh/p1_ansible_ed25519
export CR_CHANGE_APPROVED=CR-P1-NTP-01-01
python3 -I -B tools/ntp-onepass.py \
  --rollout-repo /home/server01_ansible/ntp-readiness-retry.W19ALmze/FDS_NTP_PR29_Field_Package_v1_0_eb08dc8c/infra-ansible \
  --input /home/server01_ansible/ntp-onepass-input.json \
  --apply
)
```

이는 방화벽 변경과 chrony 적용·재시작을 포함한다. 기존 `makestep 1.0 3`을 유지하므로
재시작 뒤 조건을 만족하면 시간이 step될 수 있다. 환경변수 설정은 미승인 코드·정책의
승인을 대신하지 않는다. 후보 패키지가 `REVIEW_ONLY`인 동안에는 위 적용 명령을 실행하지
않는다. 요청된 현재 작업의 결과는 구현·검증·검토 준비 단계다.

`--apply`를 생략하면 6대의 현재 원문과 journal을 저장하고 적용을 시작하지 않는다.
이 모드도 원격 `/var/lib/fds-ntp-onepass` 아래 기록 파일을 생성한다. 방화벽·chrony 구성은
변경하지 않으며 공인 진단·NTP 전환·송신 제한·최종 표본을 수행하지 않는다.
두 모드 모두 검토 소스·실제 참조를 포함한 동일한 유효 입력이 필요하다.
`--apply` 실행에 필요한 확인이 포함되므로 이를 별도 필수 단계로 반복하지 않는다.
증적 기본 위치 대신 기존의 본인 소유 안전한 디렉터리를 쓰려면 `--evidence-parent`를 지정한다.

## 적용 순서와 변경 범위

1. 입력·검토 소스·controller·대상을 확인하고 실행 전체의 잠금을 확보한다.
2. 6대 원본과 정책을 보존하고 control01의 수신 rich rule 5개 중 없는 항목만 추가한다.
   각 규칙은 해당 client `/32` → `10.1.93.102/32`, UDP destination 123이다.
   runtime/permanent 존재 여부와 이번에 추가한 쪽을 별도로 기록한다.
3. 실제 준비 원문·변경 결과·복구 방법과 사전 결정을 연결한 뒤 기존 NTP 실행기를 호출한다.
   source 진단·적용 → 5개 내부 경로 → client 직렬 적용·검증 순서를 유지한다.
   `PREPARATION.json`은 원래 정책 참조·이번 원문·검증된 수신 준비와 송신 적용 대기를,
   `RECOVERY.json`은 실제 복구 참조·host별 journal·복구 규칙을 기록한다.
   자식 `RUNTIME_INPUT.json`의 두 참조는 이 실제 생성 파일을 가리키며 입력값만으로 승인을
   생성하지 않는다. 원래 참조는 `ONEPASS_INPUT.json`과 준비 기록에 보존한다.
4. **전체 NTP 전환 성공 후** 6대 NTP 송신 목적지를 제한한다. 전환 전 host의 기존 pool 경로를
   먼저 끊지 않는다. SSH/LB 및 NTP와 무관한 통신 허용 범위를 바꾸지 않는다.
5. 송신 제한 후 유효 정책·경로와 표본을 확인하고 원문·변경 journal·결과와 해시를 포장한다.
   기존 승인 진단·내부 path gate를 다시 사용해 송신 제한 이후 실제 응답을 확인한다.
   전체 전환 후 6대의 표본을 60초 이상 간격으로 6회 수집한다. 첫 표본부터 마지막 표본까지
   최소 약 5분이 필요하며 누락·지연을 숨기지 않는다.

방화벽 변경은 정확한 규칙·전용 chain의 증분만 소유한다. 전체 flush, firewall reload,
`runtime-to-permanent`, 기존 공유 규칙 교체로 적용·복구하지 않는다. 기존에 동일하게 있던
항목은 이번 변경으로 소유하거나 제거하지 않는다.

수신은 firewalld rich rule, 송신은 firewalld direct의 전용 `FDS_NTP_0101` chain으로
구현한다. 앞서 설명한 `HOST → ANY` policy는 후보였으며 이번 코드의 실제 backend와 다르다.
송신 hook은 host `OUTPUT`의 **conntrack NEW, UDP destination 123**에만 한정한다.
선정 IPv4 목적지의 통신은 기존 뒤쪽 방화벽 판단으로 돌려보내고 나머지는 DROP한다.
IPv6의 신규 NTP 요청도 DROP하며 FORWARD/Pod 허용을 추가하지 않는다.

IPv4 Negative는 문서용 `192.0.2.123`으로 신규 UDP를 보내고 전용 DROP 카운터 증가를
대조하는 범위다. 이를 모든 비승인 주소·IPv6·Pod의 실제 패킷 시험으로 확대하지 않는다.
IPv6는 정책 존재를 확인하며 실제 IPv6 Negative 패킷 시험은 별도로 구분한다.

firewalld의 새 policy 생성은 permanent 범위이므로 runtime 반영을 위한 reload 없이
이번 단일 작업을 수행하기 위해 direct를 사용한다. direct는 **폐기 예정 인터페이스**다.
이번 backend가 검토·동작하는 설치 환경에 한정하며 향후 지원 종료·backend 변경 시 재검토한다.
[firewall-cmd](https://firewalld.org/documentation/man-pages/firewall-cmd.html),
[firewalld.direct](https://firewalld.org/documentation/man-pages/firewalld.direct.html)

NEW에만 적용하므로 **기존 conntrack UDP 세션을 즉시 제거하지 않는다**. 신규 비승인 NTP
요청 차단 결과를 모든 기존 세션의 즉시 차단으로 해석하지 않는다. conntrack 전체 삭제는
하지 않으며 기존 세션의 종료·잔존 여부는 최종 최소 권한 인수에서 별도로 대조한다.

## 실패 시 처리

| 실패 지점 | 처리 원칙 |
|---|---|
| 입력·검토 소스·기준점 확인 | 적용 시작 전 중단하고 원문 보존 |
| 수신 준비에서 확인된 실패 | 해당 실행이 추가한 control01 수신 증분만 복구 시도 |
| 수신 준비 중 응답 단절·상태 불명확 | journal과 현 상태를 보존하고 불명확한 역변경 중단 |
| 기존 실행기의 공인 진단·적용 실패 | 다음 단계 중단; 수신 규칙과 성공 host를 보존하고 기존 실행 결과로 범위 판단 |
| source 적용 도중·timeout·연결 단절 | 적용/복구 상태를 미실행으로 단정하지 않고 현 상태 확인 후 판단 |
| source 성공 후 내부 경로 | client를 시작하지 않고 성공 source 보존 |
| client 일부 실패 | 다음 host 중단, 기존 실행기의 host별 rescue 결과 확인, 성공 host 보존 |
| 송신 제한 중 확인된 실패 | 실패 host의 이번 송신 증분만 복구 시도; 먼저 완료된 host의 정책과 NTP 전환 유지 |
| 송신 제한 중 응답 단절·상태 불명확 | 추가 변경·복구 중단, 원문과 journal 보존 |
| 검증·증적 마무리 | 실제 적용 상태와 검증/포장 미완료를 구분하여 보존 |

원격 명령을 시작한 뒤 응답을 잃었다면 재실행으로 상태를 덮어쓰지 않는다.
`RESULT.json`, host별 journal과 현재 정책·chrony 상태를 먼저 대조한다.
명령을 종료한 사실은 원격 명령의 종료·복구 성공 증명이 아니다.

기존 실행기의 자동 rescue는 **해당 호출 직전 pair**, 명시적 rollback은 **최초 baseline**을
사용한다. 원래 pool/DHCP 설정으로 복구할 때는 그 host의 기존 승인 경로를 먼저 확보한다.
성공 host와 공유 경로를 일괄 삭제하거나 baseline을 수기 수정하지 않는다.

실행 상태는 다음과 같이 읽는다. `STOPPED_REVIEW_REQUIRED` 하나만 보고 미실행·전체 실패로
해석하지 말고 `child_started`, `ingress_ready`, `egress_completed`, `scoped_rollback`,
`uncertain`과 자식 결과·원문을 함께 대조한다.

| `STATUS` | 의미 |
|---|---|
| `SNAPSHOTS_COLLECTED_NOT_APPLIED` | 6대 원문·journal 수집 완료; 방화벽·chrony 구성 적용 미실행 |
| `ONEPASS_COMPLETED_REVIEW_REQUIRED` | 준비·NTP 전환·송신 제한·구현된 검증·6회 표본 흐름 완료; 최종 인수는 별도 |
| `STOPPED_REVIEW_REQUIRED` | 중단; 시작·성공·복구·미확인 범위를 원문으로 구분 |

이번 controller에 임의 host를 지정하는 별도 복구 CLI나 무조건 재개 옵션은 없다.
확인된 수신 준비 실패 또는 해당 host 송신 적용 실패만 위 범위대로 자동 복구를 시도한다.
그 밖의 명시적 복구는 실제 실패 상태와 journal에 기록된 이번 증분을 대조한 뒤 기존
책임 범위에서 수행한다. 복구 시도와 복구 성공을 구분한다.

## 결과 전달

`STAGE=`는 진행 단계, `EVIDENCE_DIRECTORY=`는 원문 디렉터리다.
종료 시 `HOME_EVIDENCE=`의 archive와 `SHA256_SIDECAR=`의 sidecar를 함께 전달한다.
실패 결과도 보존하고 archive 생성 실패 시 출력된 원문 디렉터리를 보존한다.

최소 대조 항목은 `RESULT.json`, `SOURCE.json`, `ONEPASS_INPUT.json`, `COMMANDS.json`,
`REMOTE_RESULTS.json`, host별 원문·journal이다. 적용을 시작했다면 `PREPARATION.json`,
`RECOVERY.json`, 자식 실행 증적과 `CHILD_VALIDATION.json`을, 후속 검증을 수행했다면
post-egress gate 및 `SAMPLES.json`을 함께 확인한다. 시작 전에 중단되어 없는 파일을
정상 완료 증적으로 취급하지 않는다. 출력된 archive의 같은 디렉터리에서 sidecar를 사용해
`sha256sum -c`로 전달 무결성을 확인한다.

## 완료와 최종 인수의 구분

단일 실행 완료는 그 실행에서 확인한 구성·방화벽·표본 검증 범위의 완료다.
**offset≤100ms, 60초 간격 6회, sync loss가 5분 이상 지속되면 FAIL,
재부팅 후 5분 이내 재동기화**라는 기존 AC를 변경하지 않는다.

장애·복구·재부팅 시험을 실행하지 않았다면 해당 AC는 NOT RUN이다. 정상 표본 6회가
장애 복구나 재부팅 시험을 대신하지 않는다. Kubernetes 영향과 host 순서를 확인하지 않고
6대를 일괄 재부팅하지 않는다. 최소 권한 Negative는 대상·유효 정책·drop 근거를 연결하며
무응답만으로 차단 원인을 확정하지 않는다.

로컬 정적·모의 검증, GitHub CI, 실제 Runtime, 정확한 HEAD 리뷰, 병합과 Lead 인수를
각각 표시한다. CI 0건은 NOT RUN이다. 기존 상세 기준은
[현장 실행 절차](CR-P1-NTP-01-01-field-runbook.md)와
[네트워크·복구 계약](CR-P1-NTP-01-01-network-recovery.md)을 따른다.
