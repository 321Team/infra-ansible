# CR-P1-NTP-01-01 — 네트워크·복구·인수 구현안

상태: **권장안 구현 계약 / NOT_APPLIED / REFERENCES_PENDING**.
작성: 2026-09-19 KST. [시간원 선정·수정 계약](CR-P1-NTP-01-01-upstream-selection.md)과 함께 검토한다.

사용자의 권장안 착수 지시에 따라 기존 control01 단일 내부 NTP 구조를 유지하고,
control01 자체 upstream을 선정된 공인 IPv4 3개로 제한하는 안을 구체화한다.
이 문서는 실제 주소 선정, 방화벽 반영, 서버 실행 또는 AC 인수 증적이 아니다.
공인 3기관 후보는 선정 문서에 기록했지만 현재 실행기와의 서비스 정책 적합성,
최종 유효 네트워크 정책과 구체적인 네트워크 복구 기준점은 아직 미확정이다.

## 1. 유지하는 정본과 변경 범위

최신 발행 정본은 `docs-v3.1.19`, 고정 commit
`966fc5365874b1d259a9810fc876b57c3bfa0e08`이다.
[발행 기록](https://github.com/321Team/fds-project-baseline/releases/tag/docs-v3.1.19)과
[정본 승인 입력](https://github.com/321Team/fds-project-baseline/blob/966fc5365874b1d259a9810fc876b57c3bfa0e08/baseline/FDS_Project_Implementation_Baseline_v3.1.19.md#L21)은
control01 내부 chronyd와 기존 수치 AC를 확정하고, control01 upstream/time
authority는 `INPUT_INCOMPLETE / RUNTIME_HOLD`로 구분한다.

[2026-09-16 Lead 결정](https://github.com/321Team/fds-project-baseline/issues/10#issuecomment-5697547621)의
내부 단일 소스, Relay 추가 제외, 수치 AC는 유지한다. 그 결정의
“신규 외부 egress 없음”에서 **control01 한 대의 선정 공인 NTP 3개 접근**으로
바뀌는 부분은 기존 결정의 자동 승계가 아니다. 해당 범위 Lead가 기존
Decision/CR에 변경 이유, 정확한 endpoint, 영향과 복구를 기록한다.

[정본 §15.2](https://github.com/321Team/fds-project-baseline/blob/966fc5365874b1d259a9810fc876b57c3bfa0e08/baseline/FDS_Project_Implementation_Baseline_v3.1.19.md#L1101)에
따라 Producer/Consumer, allowlist, NetworkPolicy, Monitoring, 시험 영향을
대조하고 Positive/Negative/Regression과 실행 소스를 연결한다. 미정의
인터페이스를 먼저 열거나 문서상 승인만으로 Runtime PASS를 부여하지 않는다.

[현행 Lead 위임정책](https://github.com/321Team/fds-project-baseline/blob/b2e4612cf2e417b10e7f145c5b1e5f58dbe1b948/governance/REVIEW_AUTHORITY_POLICY.md)에
따라 새 실행 코드·실행 설정의 병합에는 정확한 HEAD의 독립 리뷰가 필요하다.
기존 승인 이력은 보존한다. 동일한 확정 범위의 진단·적용·검증마다 별도의
Support 서명이나 새 승인 문서를 요구하지 않는다. 변경 판단과 아래 세 참조는
하나의 기존 Decision/CR 기록에서 함께 관리할 수 있다.

참조한 통합 실행 소스는 [PR28 HEAD `72d3f62992683511d67be0c70b984b0644b6412d`](https://github.com/321Team/infra-ansible/tree/72d3f62992683511d67be0c70b984b0644b6412d)다.
이 문서에서 해당 SHA의 코드 승인·병합 또는 실제 실행을 새로 주장하지 않는다.
실행 시 `reviewed_source_sha`에는 그때 확인한 검토·병합된 실행 checkout의
전체 HEAD를 사용한다.

## 2. 요청하는 정확한 통신 범위

| 구분 | Source | Destination | 요청·판정 |
|---|---|---|---|
| 공인 NTP 요청 | control01 `10.1.93.102/32` | 선정한 서로 다른 공인 IPv4 3개, 각각 `/32` | IPv4 UDP **destination 123**만 |
| 공인 NTP 응답 | 위 3개 endpoint | 실제 요청을 시작한 control01 세션 | stateful reply만; 인터넷 시작 신규 inbound 허용 없음 |
| 내부 NTP 요청 | `10.1.93.103/32`, `10.1.93.104/32`, `10.1.93.105/32`, `10.1.93.107/32`, `10.1.93.108/32` | control01 `10.1.93.102/32` | UDP destination 123; source ingress와 client egress 모두 대조 |
| 내부 NTP 응답 | control01 | 요청한 5개 client 세션 | 실제 반환 경로·stateful reply 확인 |
| 나머지 5대의 공인 NTP 직접 접근 | 위 client 5개 | 공인 NTP | 최종 설계에서 허용하지 않음; 실제 차단 여부는 별도 증적 필요 |
| 업무 Pod의 외부 NTP | 업무 Pod | 외부 | 이번 변경에서 허용 범위를 추가하지 않음 |

주소 목록은 실제 서비스 운영·사용 조건을 확인한 literal IPv4 3개로 채운다.
현재 pool을 한 번 DNS 조회해 나온 IP를 고정 운영 주소로 전환하지 않는다.
hostname, `0.0.0.0/0`, 큰 공인 대역 허용, 선정된 3개 외 목적지 추가로 대체하지 않는다.
공인 IP 문법 통과는 해당 주소가 NTP 서비스를 제공하거나 사용을 허용한다는
증명이 아니다. 공급자의 윤초 처리 방식이 호환되는지 함께 결정한다.

chronyd의 기본 NTP client source port는 운영체제가 선택한다. source port를
123으로 고정하는 규칙을 만들지 않는다. 실제 ephemeral 범위와 NAT 후 source는
경로 증적에 기록한다. 목적지 123 허용과 인터넷에서 들어오는 신규 요청 허용은
다르다. [chrony 4.8 acquisitionport](https://chrony-project.org/doc/4.8/chrony.conf.html#acquisitionport)

필요한 논리 흐름은 좁지만 실제 구현이 “규칙 한 줄”로 끝난다고 확정하지 않는다.
host firewalld/nftables, Calico HEP/GNP, 상위 방화벽과 NAT 중 어디서 집행되는지에
따라 필요한 증분이 달라진다. 코드에 있는 allow 규칙이나 `chronyc accheck`만으로
전체 경로가 열렸다고 판정하지 않는다.

## 3. 네트워크 소유자가 연결할 실측·변경 증적

최초 준비에서는 필요한 범위의 읽기 전용 원문을 확보하고, 실제 변경은 확인한
backend의 검토된 변경분으로 수행한다. 아래 목록은 모든 장비에 같은 설정을
중복 적용하라는 뜻이 아니다. 해당 경로에 실제 존재하는 통제 지점을 식별한다.

| 확인 대상 | 필요한 원문·대조 | PASS로 확대하지 않을 사실 |
|---|---|---|
| control01·client host 정책 | firewalld 활성 상태, interface/source의 zone 결합, runtime/permanent, policy/rich/direct 규칙과 실제 유효 nftables 경로 중 NTP에 관련된 부분 | zone에 `ntp`가 보이거나 보이지 않는 것만으로 전체 허용·차단 단정 불가 |
| Calico host 정책 | 실제 HEP 유무, node/interface/IP/label, 적용되는 GNP selector·tier/order·direction·forward/preDNAT 범위와 유효 규칙 | 저장소 manifest 존재는 live 집행 증거가 아님; 업무 Pod 정책과 host 정책을 혼동하지 않음 |
| 상위망·NAT | control01→선정 IP 3개별 route/interface/source, 실제 외부 source/NAT, UDP123 허용과 반환 세션 조건, 정책 ID/변경 ID | `10.1.93.102`가 상위 장비에서도 그대로 보인다고 가정하지 않음 |
| 내부 5개 경로 | client별 source/interface/route와 control01 UDP123 listener·5개 `/32` ACL, 실제 NTP request/reply | route 또는 ACL 성공은 UDP 왕복·정확한 시간 표본 성공을 대체하지 않음 |
| 변경 소유권 | 변경 전 정책 원문/해시, 장비·host·정책 ID, 이번 추가·수정·삭제 내역, 복구 대상과 기존 공유 규칙의 구분 | 전체 정책 flush/교체를 증분 변경이나 복구로 취급하지 않음 |
| 영속성 | 해당 backend의 저장·재기동/재부팅 후 집행 방식과 검증 결과 | runtime만 바꾼 결과를 permanent·재부팅 지속성 PASS로 표시하지 않음 |

2026-09-18 21:14:44–21:15:00 KST 원 수집에서는 control01의 UDP123 listener가
없고, 5개 client의 accheck 응답이 `209 Access denied`였다. 당시 zone 관측에는
NTP 허용 항목이 없었지만 전체 nftables/상위망/HEP 유효 정책을 수집한 것은
아니다. 이것은 **당시 관측**이며 지금 상태를 대신하지 않는다.
[원 수집 검토](https://github.com/321Team/infra-ansible/pull/24#issuecomment-5730010107)

현재 문서 작성에서는 원격 조회나 변경을 수행하지 않았다. 새로운 네트워크
준비 완료 또는 source/network/recovery 확정을 표시할 원격 적용 증적은 없다.

## 4. 기존 runtime 입력의 세 참조를 채우는 방법

실행기는 `reviewed_source_sha`, `public_upstreams`와 아래 세 문자열만 받는다.
형식을 통과한 문자열은 실제 승인·서비스·방화벽 반영을 인증하지 않는다.
빈 값 또는 미확정 내용을 그럴듯한 URL로 바꿔 실행하지 않는다.

| 입력 | 연결할 실제 기존 기록의 내용 | 완료 전 상태 |
|---|---|---|
| `source_policy_ref` | 선정 IP 3개, 서비스 운영자·사용 조건, 고정 endpoint 유지/변경 방식, 윤초 처리의 호환성, control01 단독 외부 접근으로 바꾸는 Lead 판단과 기존 downstream/AC 유지 | 주소·사용·윤초 중 미결이 있으면 미확정 |
| `network_policy_ref` | 위와 동일한 IP 3개와 `.102/32` UDP destination123, 5개 내부 client 경로, 실제 통제 장비/host와 변경 증분·반영 결과, stateful return/NAT, public 직접 접근 제한 및 경로 시험의 원문 위치 | 정책 초안·코드만 있으면 적용 미검증 |
| `recovery_ref` | host별 원본 chrony pair/baseline과 직전 snapshot, 이전 네트워크 정책 원문/해시, 변경 소유권·복구 순서·접근 경로·중단 기준, 성공 host 보존과 실패 host/네트워크 증분 복구 방법 | 원본 pool/DHCP와 복구 네트워크의 정합성을 확인하지 못하면 미확정 |

세 참조는 기존 티켓의 한 결정 댓글이나 버전 고정 문서의 구분된 절을 가리켜도
된다. 담당·시각·대상·검토 소스·결정/미결·증적 위치를 함께 기록한다. 이미 있는
유효한 결정과 증적은 재사용하고 같은 목적의 서류를 다시 만들지 않는다.
그 기록의 실제 endpoint와 실행 JSON의 `public_upstreams`, Ansible의 최종
resolved upstream 값, 네트워크 요청서의 주소가 일치해야 한다.

현재 [입력 예제](https://github.com/321Team/infra-ansible/blob/72d3f62992683511d67be0c70b984b0644b6412d/docs/change/CR-P1-NTP-01-01-runtime-input.example.json)는
`public_upstreams: []`와 빈 참조를 유지한다. 이 초안은 실제 IP나 확정 참조를
대신 작성하지 않는다.

## 5. 기존 책임 범위와 단일 작업창 순서

| 책임 범위 | 기존 연결 | 할 일 |
|---|---|---|
| NTP 토폴로지·서비스·수치 AC | 기존 K8S/NTP 책임 범위, baseline #10 | 선정 upstream·윤초/사용 정책과 내부 단일 소스 유지 판단, Kubernetes 영향·최종 결과 인수 |
| 네트워크·경로·정책 복구 | 기존 ICR/네트워크 책임 범위; K8S/SEC 담당과 연결 | 실제 host/상위망 정책 증분, 반환/NAT, 변경 전후 증적과 복구 기준점 |
| HEP/GNP·최소 권한 | 기존 K8S/SEC 책임 범위 | 적용되는 host 정책의 source/destination 범위·집행과 다른 경로 영향 확인 |
| Ansible 실행·증적 | 기존 Ansible 담당 범위 | 검토·병합된 소스/입력 고정, source→path gate→clients 직렬 적용, 실패 보존·host 복구 |

이 표는 담당자를 새로 배정하거나 Support에게 추가 승인권을 만드는 것이 아니다.
상위 방화벽의 실제 운영자는 네트워크 기록에서 확인하고 임의로 지정하지 않는다.

1. 결정 기록과 주소 3개를 고정하고, 작업창의 실제 정책·chrony 원본·복구 경로를
   연결한다. 설치된 chronyd의 실제 argv/config와 서비스 상태는 실행 진단에서
   확인한다. 현재의 SSH 관리 경로를 보존한다.
2. 네트워크 소유자가 검토한 최소 증분을 반영한다. 아직 원래 pool/DHCP를 쓰는
   host의 필요한 경로를 먼저 끊지 않도록 **구성 전환과 기존 허용 제거 시점**을
   같은 기록에 정한다. 기존 경로의 존재나 허용 근거가 미확정이면 가정하지
   않는다. 잠시 유지할 기존 범위도 명시하며 새 광역 예외를 만들지 않는다.
3. 네트워크 준비 후 통합 실행기 한 번으로 precheck→control01의 공인 3개
   NTP 응답 진단→source check/apply/idempotency→source health/ACL/listener와
   5개 내부 NTP 응답 gate→clients check/apply/idempotency→verify→증적 포장을
   수행한다. 별도 단계별 승인 질문을 추가하지 않는다.
4. clients는 한 대씩 적용한다. 실패한 host 이후의 적용은 중단한다. 전환 후
   불필요해진 기존 공인 경로는 검토한 네트워크 증분으로 정리하고, 5대의 공인
   직접 접근 제한을 포함한 Positive/Negative/Regression을 확인한다. 원래
   정책에서 제거할 항목이 없으면 불필요한 삭제 작업을 만들지 않는다.
5. 원문 증적과 설정/정책 버전으로 최종 AC를 판정한다. 통합 실행기의
   `ROLLOUT_COMPLETED_REVIEW_REQUIRED`는 흐름 완료이고 최종 인수 PASS가 아니다.

네트워크 변경은 현 PR28 실행기가 수행하지 않는다. 따라서 실제 backend 변경분이
미구현·미반영인 상태에서 “진단부터 적용까지 한 번”만으로 모든 방화벽 준비도
끝난다고 설명하지 않는다. 기존 `makestep 1.0 3`은 보존되므로 chronyd 재시작 후
조건을 만족하면 시계가 step될 수 있다. Kubernetes 영향과 작업창 판단에 포함한다.

## 6. 실패 범위별 복구와 성공 host 보존

자동 rescue는 해당 호출 직전의 main/drop-in snapshot을 사용한다. 명시적
host rollback은 보호된 최초 baseline을 사용한다. 두 기준점은 다르며, 성공한
이전 실행을 자동으로 되돌리거나 baseline을 삭제·수정해 검사를 우회하지 않는다.

| 실패 지점 | 적용 상태와 후속 처리 | 네트워크 복구 범위 |
|---|---|---|
| source 전 진단 실패 | Ansible 구성 적용은 시작하지 않음. 실패 원문 보존 | 준비 단계에서 실제로 바꾼 네트워크 증분이 있으면 그 소유자가 원래 승인 상태와 영향에 따라 복구 |
| source 적용 도중 실패·timeout·신호 중단 | 적용 여부가 불명확할 수 있음. `source_applied:null`을 미실행으로 해석하지 말고 해당 host 상태·복구 결과 확인 | control01의 원본 pair와 맞는 경로를 복구 계획대로 대조. 원격 작업이 종료됐다고 controller 종료만으로 단정하지 않음 |
| source 성공 후 내부 path gate 실패 | clients는 시작하지 않음. 정상 적용한 source를 자동으로 되돌리지 않고 내부 경로 실패를 분리 | 성공한 source의 upstream 경로를 유지하며 실패한 내부 정책 증분만 판별; source 자체 복구 필요성은 실제 상태로 판단 |
| client 한 대 실패 | 해당 host의 invocation pair 복구와 서비스 결과 확인. 이후 host는 중단하고 앞서 성공한 host는 보존 | 실패 host의 복구 설정에 필요한 이번 네트워크 증분만 조정. 공유 규칙·성공 host 경로를 일괄 삭제하지 않음 |
| verify 또는 증적 마무리 실패 | 적용 완료와 AC/증적 완료를 분리. 원문·baseline 보존, 범위가 정해진 보완 수행 | 구성이 실제 실패했다는 근거 없이 전체 정책을 되돌리지 않음 |

**원래 pair를 복원하는 것과 시간 동기화가 복구되는 것은 다르다.** 최초 baseline은
`pool 2.centos.pool.ntp.org iburst`와 `sourcedir /run/chrony-dhcp`를 포함한다.
그 설정이 사용하는 목적지는 새 고정 IP 3개와 다를 수 있다. 새 strict allowlist만
남긴 상태에서 pair를 복원하면 동기화가 계속 실패할 수 있다.

따라서 `recovery_ref`에 다음을 한 묶음으로 남긴다.

- host별 원본/직전 pair, 소유권·mode·해시와 보관 위치; 원본 baseline 유지.
- 네트워크 변경 전 실제 유효 정책, 이번 증분의 식별자·소유자와 되돌릴 항목.
- 기존 설정이 필요로 하는 원래 **승인된** 경로와 반환/NAT 상태를 복구하는 순서.
  새로운 `0.0.0.0/0` 허용이나 전체 firewall flush로 대신하지 않는다.
- 성공 host의 현재 설정과 경로를 보존하는 방법. 공유 정책이면 영향을 받는
  host를 확인하고 검토한 역변경을 사용한다.
- 복구 후 main/drop-in 및 서비스·실제 선택 source·NTP 응답·offset 확인과 결과
  인계. 시계 동기화를 확인하지 못했으면 복구 시도와 실패/미검증을 구분한다.

이전에 사용하던 외부 경로가 승인된 복구 범위인지 확인할 수 없거나 원본 정책을
확보하지 못하면 네트워크 복구를 임의 수행하지 않는다. 불명확한 부분과 영향받은
host를 기록하고 해당 Lead가 기존 책임 범위에서 복구를 판단한다.

## 7. 기존 AC와 네트워크 인수 증적

| 항목 | 성공 조건 | 남길 원문과 범위 |
|---|---|---|
| source 진단 | control01에서 확정 IP 3개 각각의 유효 NTP 응답과 offset 검사 성공 | target·source·시각·명령·rc·원문; 진단 응답은 세 서버의 시간 합의나 장기 동기화의 대체 증거가 아님 |
| 내부 경로 | 5개 client 각각 control01에서 실제 NTP 응답; source listener/5개 ACL 일치 | host별 request/reply·서비스·ACL 원문; ACL만으로 통신 PASS 불가 |
| 최종 소스 구성 | control01은 확정 3개, 5개 client는 control01만 사용 | effective chrony config와 runtime sources/tracking; 기존 pool/DHCP에 의한 경쟁 source가 남지 않는지 확인 |
| offset | 기존 확정 한도 **100ms 이내** | 동일한 측정 필드·기준을 사용하고 raw tracking의 System time/Last offset을 보존; 부호를 제거한 크기와 단위 명시 |
| 표본 | **60초 간격 × 6회** | 6대 각각 실제 관측 시각과 값. 시작을 t0로 하면 마지막은 약 t0+300초; 누락/재시도/지연을 숨기지 않음 |
| 동기화 상실 | **5분 이상 지속 시 FAIL** | 상실 시작·관측 공백·회복 시각과 연속 관측. 짧은 한 번의 정상 출력으로 조건 충족을 주장하지 않음 |
| 재부팅 지속성 | **재부팅 후 5분 이내 재동기화** | 대상별 reboot/서비스 기동/선택 source/정상화 시각과 정책 지속성; Kubernetes 영향·순서는 기존 담당 판단에 따르고 6대 일괄 reboot로 대체하지 않음 |
| 최소 권한 Negative | 다른 5대의 직접 공인 NTP와 비승인 source의 control01 NTP 사용은 허용되지 않음 | 정해진 대조군·유효 정책·drop 증거를 연결. 단순 timeout/무응답만으로 방화벽 차단 원인을 확정하지 않음 |
| Regression·복구 | SSH 관리·필요한 기존 Kubernetes 경로 유지, 실패 host와 네트워크 증분 복구가 기존 범위대로 동작 | 변경 전후 결과와 정확한 source/config/policy 버전. 무관한 기존 시험을 전부 반복하지 않음 |

Negative/장애/재부팅 시험은 대상·지속시간·복구 기준점과 Kubernetes 영향을 같은
작업 기록에 정해 수행한다. 위 표의 네트워크 검증은 제안한 변경의 허용/차단을
입증하는 절차이며 정본 수치 AC를 새 수치나 포괄적 프로젝트 Gate로 확대하지 않는다.

최종 인수는 원본 archive와 SHA256, host·UTC/KST 시각, 입력·실행·설정·정책
버전 및 실제 시험 범위를 대조해 해당 Lead가 판단한다. 코드 리뷰, 로컬 모의시험,
루프백 시험, `-Q` 단일 표본, archive 생성 성공을 운영 AC PASS로 대신하지 않는다.
증적 저장소 편입 PR은 기존 독립 리뷰 요구를 그대로 따른다.
