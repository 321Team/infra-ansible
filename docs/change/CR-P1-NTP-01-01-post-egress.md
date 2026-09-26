# CR-P1-NTP-01-01 — 중단 실행의 후속 검증 후보

> 2026-09-24: Gate 2 이후 노드 보호가 firewalld에서 Calico HEP/GNP로 바뀌었다. 이 문서의
> firewalld direct(`FDS_NTP_0101`) 기반 후속 검증은 A안
> [Calico GNP 기준 후속 검증](CR-P1-NTP-01-01-followup-gnp.md)으로 대체하는 것을 검토 중이다.
> 최종 인수 항목은 [네트워크·복구 인수 계약](CR-P1-NTP-01-01-network-recovery.md)을 그대로 유지한다.

상태: **별도 코드 리뷰 대상 / 운영 실행 NOT RUN / 새 작업창 미정**.
PR34 R1은 승인·병합됐으며, 현재 R2 보완은 별도 후속 PR의 리뷰 대상이다.
PR32·PR34 R1 코드 승인을 새 R2 코드의 승인으로 대신하지 않는다.

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
| 기준 수집본 | `ntp-pr31-post-egress-pdv_sd3n.tar.gz`, 2026-09-21 11:13 KST |
| 수집본 SHA256 | `11ea3cf62d3709d902120aca58264f6160725f5045568d4040d4119e54c7b7a9` |

이 기준 수집본은 현재 서버 상태를 뜻하지 않는다. 후속 실행 때 원문과 다시 대조하며,
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

PR24의 main 병합, 실서버 파일 배치·실행, 후속 결과 인수 및 티켓 종결은 각각 실제
확인한 단계에서 기록한다. 진단 개선 이슈 [#33](https://github.com/321Team/infra-ansible/issues/33)은
비차단 후속으로 유지하며 이 실행기에 함께 확장하지 않는다.
