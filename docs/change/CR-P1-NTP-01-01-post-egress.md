# CR-P1-NTP-01-01 — 중단 실행의 후속 검증 후보

상태: **R3 보존 증적 기반 커널 경로 보완 후보 / R3 운영 실행 NOT RUN / 새 작업창 필요**.
PR35의 R2와 상위 PR24는 main `ab0e98ffeda913908d11f4df8ae09642ff80b775`에 병합됐다.
아래 R1/R2 검증 기록은 이력으로 유지한다. 기존 승인으로 새 R3 변경의 승인을 대신하지 않는다.

## 2026-09-23 재개 변경과 현재 상태의 경계

최신 기준은 main `65b279c44051e6b17a8e531816b23d812e09e127`이다. PR36의 진단 코드와
PR41의 승인 엔진 소스 pin(`28e59bfd517661439f2a2c794824b0d19de3218e5101e143656ff5a865e3f1b2`)을
유지한 상태에서 보존된 R3 초안을 이어 보완했다.

- 실제 16:14 원문에 있는 ARP `ifname : verdict` map과 `vmap`을 구조·키·verdict·참조 대상으로
  검사한다. 중복 키, 존재하지 않는 참조, 지원하지 않는 map 형식은 거절한다. ARP 내용도 고정하므로
  NTP와 무관한 Pod/인터페이스 변경에 따라 STOP할 수 있으며 자동 허용하지 않는다.
- iptables-save에만 표시되는 빈 ACCEPT builtin은 native nft에서 실제 생성되지 않은 상태를 별도
  표식으로 고정한다. 규칙이 있는 체인·일반 체인·DROP 정책 누락은 거절하고 모든 nft hook 목록을
  계속 비교한다. 새 native hook을 이 예외로 무시하지 않는다.
- 비어 있던 6대 계약과 0으로 채워졌던 소스 pin을 채웠다. **계약 값은 9월 21일 관측값이며,
  9월 23일 정책의 승인이나 서버 현황을 뜻하지 않는다.** 실행 때 4종 원문을 새로 조회하고 고정
  계약과 다르면 패킷 시험 전에 STOP한다. live 원문으로 기준을 자동 갱신하는 경로는 없다.
- [Issue33 현장 보고](https://github.com/321Team/infra-ansible/issues/33#issuecomment-5758749247)는
  9월 21일 18:53–18:57의 6대 predecessor STOP을 기록한다. Issue33/37/40 종결과 PR41 병합은
  각각의 후속 항목 완료이며, NTP Runtime PASS·최종 인수가 아니다.

재개 입력은 기존 승인된 계정·키·호스트, 원 journal, 실제 network/recovery 참조, 변경된 정책의
소유권과 NTP 관련 경로 확인, 새 작업창이다. 전체 HEP/GNP/MON 완료를 선행조건으로 추가하지
않는다. 기존 정책이 바뀌었으면 실제 원문과 승인 범위를 확인하며 과거 값을 새 값으로 바꿔
검사를 통과시키지 않는다. 이 PR은 무결성·보안 판정 코드이므로 Pre-check 병합 예외 대상이 아니며
최종 HEAD의 독립 리뷰가 필요하다. 동일 승인 코드의 단계마다 반복 리뷰를 추가하지 않는다.

## 2026-09-21 16:14 현장 확인과 R3 변경

수집본 `ntp-current-paths-mnqyxu02.tar.gz`의 SHA256은
`7945a9bc4c18f0bc05d22dc329773b9820134e57cdaa764cfcd8cc21f218fcb6`다.
16:14:31.198760–16:14:40.077813 KST에 읽기 전용 수집이 완료됐고,
외부 sidecar 및 내부 33개·기존 collector 내부 13개 파일 해시를 확인했다.
최종 source fixture는 `tests/ntp_source/fixtures/current_kernel_20260921_1614.json`이다.

| 관측 항목 | 확인 결과와 한계 |
|---|---|
| 서비스·동기화 | 6대 chronyd active/running, Leap Normal, 승인 source 선택, Reach 377. 단회 System time 절댓값 0.006185–0.161556ms |
| 설정·journal | 11:13 대비 chrony.conf, CR drop-in, direct.xml, 원 journal의 해시·권한 등 24개 파일 일치. 8개 보존 대상 전체를 수집한 것으로 확대하지 않음 |
| NTP 전용 정책 | runtime/permanent direct 조회 36개 출력 및 6대 IPv4/IPv6 FDS 본체·자체 hook 동일 |
| 전체 정책 | Calico/KUBE 체인 추가. native firewalld에는 control 각 9개·worker 각 3개 TCP 2380/6443/10250 허용 추가, 제거 없음. 전체 방화벽 불변은 아님 |
| 시험 실행 | 이 수집은 NTP 패킷 시험 0. IPv4/IPv6 FDS DROP 카운터 모두 0이며 음성 시험 PASS 아님 |
| 부팅 | uptime상 6대 모두 이번 NTP 적용 이전 부팅. 적용 후 재부팅 지속성 증거는 미확보 |

R2 중단은 nonfilter 규칙 일괄 거절, 11:13 전체 커널 해시 고정, 기존 엔진의
KUBE-FIREWALL 단독 선행 체인 조건에서 발생했다. R3는 기존 적용 엔진과 journal을
수정하지 않고 후속 검증기의 커널 판정만 보완한다. 서버 정책 재적용은 하지 않는다.

9월 21일 증적에서 raw OUTPUT은 Calico mark를 비우며, UDP4789만 NOTRACK 대상으로 삼는다.
mangle OUTPUT에는 규칙이 없고, NAT의 현재 서비스 분기는 TCP443/9153 또는 UDP/TCP53이다.
host endpoint 체인은 비어 있으며, filter의 Calico/KUBE 선행 경로 뒤에 FDS NTP hook이 있다.
이는 검토한 신규 UDP123 host-flow의 구조적 판단이며 실제 패킷 성공의 대체 증거가 아니다.

R3 커널 contract는 이 증적에서 검토한 경로와 hook을 코드에 고정한다. 명시적으로
NTP와 분리되는 서비스 분기만 투영에서 제외하며, `cali-*`/`KUBE-*`라는 이름만으로
자동 허용하지 않는다. 새 hook, NTP 관련 NAT/NOTRACK, 비어 있던 host endpoint 활성화,
전용 FDS 규칙 변경 및 지원하지 않는 구조는 STOP한다. nft의 xt 표현만으로 숨겨진
인수를 추정하지 않고 iptables/ip6tables 원문·ipset·native nft 구조를 함께 검사한다.
실행 시 새 정책을 승인 기준으로 학습하지 않는다.

실행의 사전·중간·최종 보존 검사는 전체 정규화 원문 해시를 계속 대조한다.
따라서 같은 실행 도중 외부 정책이 바뀌면 NTP와 무관한 변경이라도 STOP할 수 있다.
투영의 목적은 이후 독립 실행마다 무관한 서비스 분기 변화로 코드 기준을 다시
발행하는 일을 줄이는 것이며, 실행 도중 정책 변화를 무시하는 것이 아니다.

사용자가 연장한 15:00–16:30 KST 창은 수집에 사용했다. R2/R3의 positive gate는
1,810초 여유가 필요하므로 15:59:50 이후 같은 창에서 진입할 수 없다.
수집 완료 약 9초를 전체 검증의 시간 예산으로 사용하지 않는다. 이 문서와 코드는
새 운영 작업창을 임의 승인하거나 자동 연장하지 않는다.

## 최종 인수의 고정 범위와 잔여 실행

원 [Lead 결정](https://github.com/321Team/fds-project-baseline/issues/10#issuecomment-5697547621)과
[네트워크·복구 인수 계약](CR-P1-NTP-01-01-network-recovery.md)을 유지한다.
다음 항목이 충족되기 전에는 R3 실행 성공도 전체 인수 PASS로 올리지 않는다.

| 항목 | 재사용 / 다음 실행 | 완료 판단 |
|---|---|---|
| 설정 적용 | 9월 21일 10:56 적용과 같은 날 보존 근거 재사용 | 전체 OnePass apply 재실행 불필요 |
| 정상 경로·IPv4 음성 | R3 사전점검 → 기존 TEST-NET DROP → 고정 diagnose/pathcheck | 6대 음성의 전용 counter 증가, CP1의 승인 시간원 및 client 5대의 실제 NTP 응답 |
| 동기화 관측 | 기존 sampler 재사용, 실제 새 6회 관측 | 각 host 60초 이상 간격 6회, 승인 source·정상 Leap·offset 100ms 이내 |
| 직접 공인 NTP·기존 세션 | client의 승인 밖 목적지 차단 증거와 UDP123 conntrack 현황을 대조 | NEW 전용 제한을 기존 ESTABLISHED 차단으로 확대하지 않음. conntrack 전체 flush 없음 |
| IPv6 음성 | 9월 21일 수집 당시 외부 IPv6 주소·default route가 없었음. 실행 전 현재 경로를 조회하고 제한 시험 구체화 | ::1 신규 패킷과 IPv6 FDS DROP 증가를 시험할 수 있으나 외부 IPv6 경로 검증과 구분. ENETUNREACH는 방화벽 PASS 아님 |
| 비승인 ingress | ansible01→control01의 실제 도착 source/NAT와 거절 근거를 함께 관측 | 허용 목록 밖 source임과 정책 거절이 확인돼야 함. timeout 단독 PASS 금지 |
| 장애·회복 | 기존 정상/실패 판정 로직 시험과 현장 장애·회복 관측을 구분해 준비 | 실제 동기화 상실 300초 이상이면 FAIL. 무조건 5분 통신 차단 요구로 바꾸지 않음 |
| 재부팅 지속성 | 기존 적용 후 유효 증거를 우선 재사용하되 현재 제출본에는 없음. Kubernetes 가용성·복구 조건을 정한 대상별 순차 시험 | old/new boot ID, 기동·정상 source 회복 시각, 5분 이내 재동기화 및 NTP 정책 지속. 일괄 재부팅 없음 |
| Lead 인수 | 항목별 원문·대상·시각·소스·판정과 미완료 0건 대조 | 코드 리뷰·병합과 별도의 최종 판정 |

R3는 첫 정상 경로·IPv4 음성·6회 관측을 재개하는 변경이다. IPv6/ingress/장애·재부팅을
실행했다고 기록하지 않는다. 추가 시험은 이 표의 원래 인수 항목을 해소하는 범위이며,
모니터링 전체 종결, 새 NTP 시간원, Relay/failover를 선행 조건으로 추가하지 않는다.
재부팅을 같은 Followup 세션 안에 끼워 넣어 boot guard를 무시하지 않는다. 새 boot를
증명한 별도 관측은 같은 승인 종료시각에 다시 결합해야 한다.

## 목적과 고정 범위

원래 실행 `ntp-onepass-f9392ba915da49a19e0fe502e7616cfb`는 NTP 전환과 6대 egress
설정을 마친 뒤 control01의 커널 경로 검사에서 중단됐다. 이미 성공한 설정과 원래
실행의 journal을 보존하면서 남은 검증을 별도 증적으로 수집한다. 전체 onepass
`--apply`, ingress/egress 추가·삭제, chronyd 재시작·step, rollback을 호출하지 않는다.

| 항목 | 고정값 / 근거 |
|---|---|
| 실행 위치·계정 | `server01_ansible@ansible01` |
| 대상 | control01/02/03, worker01/02/03: 10.1.93.102/103/104/105/107/108 |
| 원격 계정 | 기존 `svc_ansible`, 비대화형 sudo root |
| PR32 승인 HEAD | `2fc8bb0b24d3bf68a15b0a227504ce43727a687a` |
| PR32 병합 | `aae84608b547f4f49134f80648a44032b91437e9` → `cr-p1-ntp-01-01` |
| 승인·병합 동일 tree | `5a1f524ba2b9da088992e7daf6554f68ccc1d0a2` |
| PR34 R1 승인 HEAD | `3167665b12bbe1b69c0011e7f85baeda6c19c710` |
| PR34 R1 병합 | `aa4fad6db2fb14611aaf03a9126c8d5eb4623ed0` → `cr-p1-ntp-01-01` |
| PR34 승인·병합 동일 tree | `88816fb4f6031e84a22ee2c159da41fe82f2a21a` |
| 기존 rollout 소스 | `0e17e2d7713484352c84f72d9ddc55aab6187386` |
| R1/R2 당시 커널·현재 설정/journal 기준 수집본 | `ntp-pr31-post-egress-pdv_sd3n.tar.gz`, 2026-09-21 11:13 KST |
| 수집본 SHA256 | `11ea3cf62d3709d902120aca58264f6160725f5045568d4040d4119e54c7b7a9` |

다음은 R1/R2 당시 커널 검사 설계의 이력이다. R3 커널 기준은 위 16:14 contract로 갱신하되
설정/journal의 원래 기준은 유지한다. 이 기준 수집본은 현재 서버 상태를 뜻하지 않는다.
후속 실행 때 원문과 다시 대조하며,
카운터 등 명시된 비정책 값 외 차이는 자동 수용하지 않는다. PR32 R2 승인 설명의
타 테이블 NAT/NOTRACK 확인 요청을 포함해 `iptables-save`, `ip6tables-save` 및
native `nft list ruleset`을 함께 다룬다. iptables 원문에 규칙이 없다는 이유만으로
native nft 경로가 없다고 판단하지 않는다.
전체 규칙을 고정하므로 NTP와 무관한 방화벽 변경도 STOP 원인이 될 수 있다.
이는 일반 환경 자동 호환을 목표로 한 실행기가 아니라 이 6대 중단 실행의 제한된 검증이다.
11:13 수집본의 6대 IPv4·IPv6 모두 mangle/nat의 `-A` 규칙은 0개였고 raw/security는
출력에 없었다. 이후 kube-proxy/CNI가 규칙을 추가한 상태라면 자동 수용하지 않고
새 원문과 NTP 우회 가능성을 검토한다. 현재도 규칙이 없다고 가정하지 않는다.

기준 수집본의 파일 해시는 `/etc/chrony.conf`, 해당 CR의 chrony drop-in,
`/etc/firewalld/direct.xml` 및 원래 `state.json`에 고정한다. 기존 엔진의 나머지
보존 대상(sysconfig, firewalld 설정·public zone, 최초 NTP 복구 메타데이터)은 이번
6대 사전점검의 파일 존재·내용·권한과 이후 관측을 대조한다. 이 추가 파일까지
11:13 원문과 동일하다고 주장하지 않는다. 전후 관측 사이의 외부 관리자 변경을
원천적으로 잠그는 기능도 아니므로 관측 사이의 연속 불변을 증명하지 않는다.

## 준비와 실행 경계

1. 이 후속 PR의 최종 HEAD 독립 리뷰·병합을 확인한다. PR32와 상위 PR24는 별개다.
2. 새 작업창과 이 후속 검증 범위의 운영 실행 판단을 기존 변경 기록에 남긴다.
   **2026-09-21 10:35–11:35 KST 작업창은 만료됐으며 재사용하지 않는다.**
3. 후속 소스와 기존 rollout을 각각 깨끗한 별도 Git checkout으로 준비한다.
   후속 입력은 승인된 전체 SHA에 결합하고 원래 onepass 입력·증적을 덮어쓰지 않는다.
4. [입력 예시](CR-P1-NTP-01-01-post-egress-input.example.json)를 새 외부 경로에 복사한다.
   빈 필드는 실제 값으로 채운다. 작업창은 시간대가 포함된 ISO 8601로 작성한다
   (예: `YYYY-MM-DDTHH:MM:SS+09:00`). `approval_ref`는 실제 운영 승인 기록을 가리킨다.
   `network_policy_ref`, `recovery_ref`에는 기존 참조를 사용하되 실제 내용의 재개 범위를 확인한다.
5. 먼저 기본 모드로 입력·소스 결합을 점검한다. 기본 모드는 서버에 접속하거나 패킷을 보내지 않는다.
6. 독립 코드 승인과 운영 실행 판단, 유효 작업창을 충족할 때만 `--verify`를 사용한다.
   환경변수·참조 경로의 존재 자체는 승인 증거가 아니다.

R2의 작업창 기준은 컨트롤러 `ansible01`의 UTC다. 각 host의 시계 관측 요청에서 얻은
부팅 ID·`CLOCK_BOOTTIME`과 컨트롤러 응답 수신 시각으로 원격 종료값을 고정한다.
요청 도착 시 새 유효 시간을 부여하지 않으며 원격 노드의 벽시계 오차·step으로
작업창을 연장하지 않는다. 부팅 변경·경과시간 역행·만료 시 STOP한다. 컨트롤러 UTC가
올바른지 운영자가 사전 확인해야 하며, 이 실행기는 시간을 수정하지 않는다.
자세한 근거와 제한은 [PR34 R2 리뷰 대응](CR-P1-NTP-01-01-pr34-review-response.md)에 기록한다.

아래는 **승인·병합 후** 사용하는 명령 형식이다. 경로는 배포 위치에 맞춰 실제 절대
경로를 지정한다. 현재 디렉터리를 패키지 루트로 가정하지 않는다.

```bash
python3 -I -B /ABS/FOLLOWUP/tools/ntp-post-egress.py \
  --rollout-repo /ABS/APPROVED_ROLLOUT \
  --input /ABS/post-egress-input.json \
  --evidence-parent /ABS/NEW_EVIDENCE_PARENT
```

실행 모드는 같은 명령에 `--verify`를 추가하고, 승인된 작업창 안에서
`CR_NTP_FOLLOWUP_APPROVED=CR-P1-NTP-01-01`을 설정한다. 후보 검토 중에는 실행하지 않는다.
사전점검 도중 작업창이 닫히거나 정책·journal이 달라지면 시험을 이어가지 않는다.
긴 positive gate를 시작하기 전에는 두 gate의 최대 실행시간과 정리 여유가 남아 있어야 한다.
현재 고정 gate의 timeout은 각각 900초이므로 이 단계 시작 시 최소 1,810초가 필요하며,
그 전후의 사전점검·음성 시험·6회 표본·최종 대조 시간은 별도로 확보한다.
컨트롤러가 SSH 작업을 중단해도 이미 원격에서 시작한 프로세스의 종료를 확인하지 못하면
미확인 상태로 기록한다. 시간초과를 패킷 미전송이나 원격 프로세스 종료의 증거로 삼지 않는다.

## 검증 순서와 판정

| 순서 | 수행 / 통과 조건 |
|---|---|
| 사전 | 각 host의 시계 관측과 컨트롤러 작업창을 연결; NTP 시험 패킷·journal 생성 없음 |
| 1 | 6대 모두 identity, 완료 snapshot, 원래 run journal의 소유권·확정 상태, 설정과 정책 기준 일치 확인 |
| 2 | 각 host의 제한 경로를 재확인한 뒤 TEST-NET `192.0.2.123:123/UDP` 음성 시험; 전용 DROP 카운터 증가 확인 |
| 3 | 고정 rollout의 diagnose/pathcheck와 그 receipt 검증으로 승인 upstream 및 5개 client의 실제 NTP 응답 확인 |
| 4 | 6대 tracking/sources를 6회 수집; 직전 배치 완료 후 최소 60초 간격, 승인 source·Leap Normal·stratum·offset 조건 확인 |
| 5 | journal·설정·정책 재대조와 새 증적 포장. 원래 증적과 원래 run journal은 보존 |

검증 과정에는 NTP 시험 패킷, conntrack 및 패킷 카운터 변화, 새 검증 증적 작성이 있다.
Ansible 임시 파일과 chrony 설정 구문 검사에 필요한 임시 staging 파일도 생성·정리된다.
따라서 `--verify`를 완전한 읽기 전용 작업으로 표시하지 않는다. 설정을 바꾸지 않는
검증이라는 범위를 유지한다. 서비스 중단·고의 sync-loss·재부팅·IPv6 음성 패킷은
여기에 포함하지 않으며 전체 AC 인수 완료로 판정하지 않는다.

## 실패와 복구

어느 gate든 실패하면 이후 시험을 중단하고 원문, 오류, 이미 수집된 새 증적을 보존한다.
검증 동작과 뒤따르는 보존 검사가 모두 실패하면 두 원인을 함께 기록한다.
원격 verify 호출의 180초 제한은 유지한다. 실서버에서 충분한 시간인지는 아직 미확인이다.
통신 단절·시간초과는 PASS나 차단 성공의 증거가 아니다. 확인되지 않은 서버 상태는
미확인으로 남기며 설정 원복·방화벽 삭제·journal 초기화·전체 apply 재실행을 하지 않는다.
중도 실패로 최종 대조에 도달하지 못한 host는 마지막 성공 관측까지만 근거가 있으며,
전체 후속 작업 동안의 설정 보존 완료로 표시하지 않는다.

규칙·설정 drift가 있으면 이전 기준을 새 값으로 덮어쓰지 않고 해당 host 원문과 변경
근거를 재검토한다. 원래 정책 자체를 되돌릴 필요가 있으면 기존 RECOVERY 문서의
소유 범위·최초 baseline·허용 NTP 경로·작업창에 따른 별도 복구 판단이 필요하다.
이 검증기의 중단이 자동 정책 복구를 요구하는 것은 아니다.

## 검증과 승인 기록

PR32는 [정확한 HEAD의 APPROVED](https://github.com/321Team/infra-ansible/pull/32#pullrequestreview-5262921305) 및
[승인 범위 설명](https://github.com/321Team/infra-ansible/pull/32#issuecomment-5755193199)에 따라 병합했다.
그때 LOCAL/MOCK 50 tests·289 subtests PASS, CI 0건 NOT RUN이었다.
이 후속 실행기 자체의 LOCAL/MOCK 결과와 최종 HEAD는 새 PR 본문에 별도로 기록한다.
AI 정적 점검을 사람의 독립 승인으로 표시하지 않는다.

R1 후보 검증(2026-09-21 KST): 기존 50개와 신규 46개를 합친 **96 tests / 442 subtests PASS**,
실패·오류·건너뜀 0, 모의 시험의 실제 프로세스·소켓 호출 0이다. 별도로 실제 기본 CLI를
합성 로컬 입력과 깨끗한 Git 소스에서 실행해 `FOLLOWUP_OFFLINE_PREPARED_NOT_EXECUTED`,
원격 요청 0, 새 증적 manifest 일치를 확인했다. 이 기본 모드 점검에는 로컬 Git 명령이
실행됐으며 실서버 SSH·방화벽·패킷 실행은 0이다. [검증 요약과 파일 해시](validation/ntp-post-egress/SUMMARY.json),
[LOCAL/MOCK 로그](validation/ntp-post-egress/focused-tests.log)를 보존한다.

R2 후보 검증: 기존 96개와 추가 19개를 합친 **115 tests / 494 subtests PASS**,
실패·오류 0이다. 실제 기본 CLI도 합성 로컬 입력에서 오프라인 준비 상태,
원격 요청·시계 조회 0, 증적 manifest 일치를 확인했다. 로컬 Git 명령은 실행했으며
운영 실행·CI는 NOT RUN이다. [R2 검증 요약](validation/ntp-post-egress-r2/SUMMARY.json)과
[리뷰 항목별 대응·수정 전 재현](CR-P1-NTP-01-01-pr34-review-response.md)을 별도로 기록한다.

재현 명령(모의 시험만):

```bash
python3 -I -B -m unittest discover -s tests/ntp_source -p 'test_onepass_*.py' -v
python3 -I -B -m unittest discover -s tests/ntp_source -p 'test_post_egress*.py' -v
```

PR24의 main 병합은 완료됐다. R3 후보의 실서버 파일 배치·실행, 후속 결과 인수 및 티켓
종결은 아직 완료가 아니며 각각 실제 확인한 단계에서 기록한다. 진단 개선 이슈
[#33](https://github.com/321Team/infra-ansible/issues/33)은
종결 상태를 유지하며 그 종결을 이 실행기의 Runtime PASS로 확대하지 않는다.

R3 재개 후보의 LOCAL/MOCK 검증은 **151 tests / 690 subtests PASS**, 실패·오류·건너뜀 0이다.
9월 21일 원본 archive와 fixture의 명령 원문 78개 일치를 확인했다. 별도 로컬 보안 검토는
양성 6건, 위험 변형 거절 156건, 동일 실행 중 정책 drift 중단 6건으로 총 168건을 확인했다.
실제 CLI 기본 모드는 합성 로컬 입력으로 오프라인 준비와 원격 요청 0건을 확인했다.
이는 GitHub 독립 승인·CI·운영 실행·최종 AC 인수가 아니다.
[소스 hash와 검증 요약](validation/ntp-current-kernel/SUMMARY.json),
[시험 로그](validation/ntp-current-kernel/focused-tests.log)를 함께 보존한다.
