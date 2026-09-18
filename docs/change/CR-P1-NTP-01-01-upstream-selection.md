# CR-P1-NTP-01-01 공인 시간원 선정·수정 계약

작성: 2026-09-19 KST. 상태: **1차 2~3개 지원·NIST 제외 수정 / 새 코드 리뷰 및 현장 입력 대기 / NOT_APPLIED**.
초기 3기관 후보와 단일 프로세스 실험은 아래에 이력으로 보존한다.
사용자의 권장안 착수 지시에 따라 정본 기반 설계와 필요한 보완을 구체화한다.
이 문서는 실행기가 소비하는 설정이 아니며 아래 주소를 현재 runtime 입력으로
복사하라는 지시도 아니다. 서버 접속·외부 NTP 요청·방화벽 변경·운영 적용은 미실행이다.

## 정본과 변경 범위

- 기준은 [발행 정본 v3.1.19](https://github.com/321Team/fds-project-baseline/releases/tag/docs-v3.1.19),
  tag commit `966fc5365874b1d259a9810fc876b57c3bfa0e08`이다.
- control01 `10.1.93.102` 단일 내부 NTP 구조와 기존 5개 client를 유지한다.
  외부 시간원은 정본에서 미확정이었다. 3기관 분산은 이번 권고이며 정본의 기존 의무로 소급하지 않는다.
- [2026-09-16 결정](https://github.com/321Team/fds-project-baseline/issues/10#issuecomment-5697547621)의
  신규 외부 egress 없음에서 **control01 → 실제 선정한 2~3개 /32의 UDP 목적지 123**으로 범위를 한정하여
  변경하는 안이다. 새 VM이나 client의 공인 NTP 직접 이용을 추가하지 않는다.
- 기존 승인과 역할을 유지한다. 기존 CR에 주소·영향·복구를 기록하며 동일 실행의
  진단/적용/검증마다 재승인을 추가하지 않는다. 새로운 실행 코드·설정의 독립 리뷰는
  [현행 리뷰 정책](../REVIEW_POLICY.md)에 따른다.

## 이번 1차 수정과 적용 선택

기존 권고의 NIST 1차 제외와 2개 입력 지원을 반영한다. 기존 PR #28의
승인·병합 소스는 정확히 3개만 허용했다. 현재 수정은 renderer, source 생성,
진단, runtime source 집합 검증이 모두 `module_utils/fds_ntp_policy.py`의
동일한 2~3개 계약을 따르게 한다. NIST·NICT·임의 공인 IP는 설정 변경이나
진단 패킷 전에 거부한다. NIST 합산 요청 간격 구현은 이번 1차 적용의 선행조건이 아니다.

기술 지원 후보는 CF `162.159.200.1`, CF `162.159.200.123`, Netnod `194.58.200.20`이다.
기관 분산 대안은 CF `.1` + Netnod `.20`이며 Netnod 주소·윤초 적합성을 먼저 확인한다.
세 주소를 모두 써도 운영기관은 둘이다. CF 두 주소만 선택하면 Netnod 확인은
비해당이지만 동일 운영기관의 장애·시간 기준 위험을 실제 기존 CR에서 수용해야 한다.
이 문서는 어느 선택의 운영 승인이나 실제 주소 입력도 대신하지 않는다.

Netnod [현재 공식 권고](https://tech.netnod.se/en/time-services/ntp-best-practice)는
iburst를 권장하고 Google smear를 경고하지만, 현재 `.20`의 비smear 운영을
직접 명시한 보증은 확인하지 못했다. 이번 조회에서 현재 개별 `.20` 주소를
명시한 Netnod 공식 운영 문서도 확보하지 못했다. 과거 등록 주소와 현재 서비스
설명만으로 주소·윤초 적합성 확인을 완료 처리하지 않는다.

Cloudflare의 현재 [사용 가이드](https://developers.cloudflare.com/time-services/ntp/usage/)는
두 IPv4 주소와 서비스의 chrony `iburst` 예제를 모두 제공하며,
[NTP 설명](https://developers.cloudflare.com/time-services/ntp/)은 비smear를 명시한다.
따라서 현 문서 근거로 입력을 구체화할 때는 **Cloudflare 두 주소를 1차 권장안**으로
제시한다. 동일 운영기관 의존과 두 source 간 상충 시 판별 한계를 기존 CR에서
수용한 뒤 사용하며, 이를 독립 2기관 구성이나 운영 인수 완료로 표시하지 않는다.
Netnod 확인이 끝나면 기관 분산 대안을 선택할 수 있다. chrony의 최소 3개 서버
[권고](https://chrony-project.org/faq.html#_what_is_the_minimum_recommended_configuration_for_an_ntp_client)는
알려진 한계로 기록하되 프로젝트 정본 AC를 임의로 확대하지 않는다.

실제 방화벽 목적지와 source/network 기록은 선택한 목록에서 동일하게 도출한다.
3기관 다양성을 기존 정본 의무로 만들지 않으며 기존 수치 AC를 유지한다.
[실서버 반영 절차](CR-P1-NTP-01-01-field-runbook.md)와
[이번 수정 검증](CR-P1-NTP-01-01-two-source-validation.md)을 함께 확인한다.

## 초기 3기관 후보와 근거 — 이력

| 운영기관 | 후보 IPv4 | 확인한 사실 | 남은 조건 |
|---|---|---|---|
| Cloudflare | `162.159.200.1` | 공식 주소, chrony `iburst` 예제, 비smear 명시 | control01 실제 경로·offset·지속성 |
| Netnod | `194.58.200.20` | 운영자 등록 주소, Global/OpenAccess, 현행 서비스의 전 세계 무료 이용 및 UTC(SP) 동조 설명 | 적용 시 주소/서비스 재확인, 윤초 정책의 명시적 적합성 확인, 실제 경로·offset·지속성 |
| NIST | `132.163.96.1` (`time-a-b.nist.gov`) | 이전 후보 기록의 주소·비smear·4초 간격 기준. 이번 조회에서 최신 서버 목록 재확인은 실패 | 초기 burst와 반복·병행 요청의 현재 정책 적합성 미확인; 이번 지원 목록에서 제외 |

공식 자료 확인일은 2026-09-18 UTC이다. 원격 서비스의 주소·상태를 영구 보장하는 의미가 아니다.
주소는 검토된 입력·정책 변경으로 교체 가능해야 하며 자동 DNS 해석 결과로 방화벽 범위를 넓히지 않는다.

- Cloudflare: [IPv4·chrony 사용법](https://developers.cloudflare.com/time-services/ntp/usage/),
  [윤초 정책](https://developers.cloudflare.com/time-services/ntp/).
- Netnod: [운영자 등록 주소](https://support.ntp.org/Servers/PublicTimeServer001419),
  [현행 서비스](https://www.netnod.se/swedish-distributed-time-service),
  [iburst·시간원 분산 설명](https://www.netnod.se/blog/best-practices-connecting-ntp-servers).
  주소 등록 자료는 2017년 이력이다. 현행 서비스 페이지와 함께 검토했지만 현장 도달성 증명은 아니다.
- NIST: [서버·요청 간격 정책](https://tf.nist.gov/tf-cgi/servers.cgi),
  [서비스·윤초 설명](https://www.nist.gov/pml/time-and-frequency-division/time-distribution/internet-time-service-its),
  [방화벽 안내](https://www.nist.gov/pml/time-and-frequency-division/time-services/internet-time-service-firewall-information).

Cloudflare `162.159.200.123`은 같은 사업자의 대체 후보이며 독립된 네 번째 기관이 아니다.
KRISS 구주소 `210.98.16.100/.101`은 [종료 공지](https://www.kriss.re.kr/board.es?act=view&bid=0002&list_no=63463&mid=a10503000000)에 따라 제외한다.
NICT는 [평균 20회/시간 제한과 주소 변경 관리](https://www.nict.go.jp/en/sts/ntp_faq.html)가 필요하므로
현재 iburst 실행기에 그대로 넣지 않는다. 이 제외는 서비스의 일반적인 품질 평가가 아니다.

## NIST를 나중에 추가할 때 해결할 코드 계약

검토한 실행 코드 기준은 PR #28의 `72d3f62992683511d67be0c70b984b0644b6412d`이다.
당시 `library/fds_ntp_migration.py`는 모든 공인 source를 `server IP iburst`로 생성한다.
`library/fds_ntp_probe.py`도 모든 별도 진단에 iburst를 사용하며 같은 형식으로 적용 설정을 검사한다.
chrony 4.8의 로컬 초기 burst에서 4초보다 짧은 간격을 관측했다.
다만 [NIST 자체 2016 연구 §3.2](https://tf.nist.gov/general/pdf/2818.pdf)는 지속적인
4초 미만 요청과 일시적인 초기 burst를 구분하며, 후자는 반드시 남용은 아니지만
응답 제한을 유발할 수 있다고 설명한다. 따라서 기존의 “iburst 충돌”은 프로젝트가
채택하려던 엄격한 4초 간격 계약과의 불일치를 뜻한다. 이를 **현재 NIST 정책 위반이나
반드시 실패한다는 사실로 단정하지 않는다.** 최신 서버 목록은 이번 조회에서
확보하지 못했다. 현재 이용 조건·반복/병행/NAT 동작을 확인하지 않은 상태이므로
NIST 제외와 아래 보수적인 후속 검토 계약을 유지한다.

필요한 수정 범위:

1. 생성·별도 진단·적용 설정 비교가 같은 source별 정책을 사용하게 한다.
   NIST 운영 후보는 `server 132.163.96.1 minpoll 6 maxpoll 10`이며 iburst를 붙이지 않는다.
   내부 client → control01의 기존 iburst는 유지할 수 있다.
2. NIST 진단은 iburst 없이 `minpoll 3 maxpoll 3`을 사용하는 8초 간격 후보를 검증한다.
   제안 예산은 chronyd `-Q -t 35`, 외부 timeout 40초다. 현재 30초 입력 상한과
   controller 단계 예산도 함께 검토해야 한다. 로컬 단일 프로세스 실험 결과는 아래와 같으며
   운영 실행기 반영과 합산 요청 간격 보장은 아직 완료되지 않았다.
3. 기존 daemon과 별도 진단의 동일 목적지 중복 요청, 반복 실행, 중단 후 재개,
   진단 종료 → daemon 재시작 경계까지 합산 요청 간격을 보장한다.
   `minpoll` 추가 또는 마지막에 sleep 하나를 넣는 것만으로 보장됐다고 판단하지 않는다.
   현재 활성 source에 같은 목적지가 있으면 별도 진단을 무조건 시작하지 않는다.
4. 합산 간격을 확인할 수 없는 상태는 후속 변경 전에 중단한다. 검사를 통과시키려고
   기존 daemon을 몰래 중지하거나 source를 일시 해제하지 않는다.
5. 단일 응답만 사용하는 `maxsamples 1`은 기존 다표본 검사의 대체로 자동 채택하지 않는다.
   packet 수·최소 간격·timeout·잘못된 offset·반복 실행·병행 daemon·부분 적용 재개와
   source 설정 멱등성까지 검증한 후 독립 리뷰를 받는다.

설정의 의미는 [chrony 4.8 문서](https://chrony-project.org/doc/4.8/chrony.conf.html)를 따른다.
공개 서비스에 실제 부하를 주는 시험 대신 먼저 loopback fixture로 요청 간격을 검증한다.
loopback 성공은 provider 이용조건 전체 준수나 현장 Runtime PASS가 아니다.

## 단일 프로세스 로컬 실험 결과

실제 chrony 4.8을 127.0.0.1의 합성 NTP responder와 연결했다. 공개 NTP/현장 서버는 조회하지 않았다.
[원본 결과](validation/ntp-provider-rate/RESULTS.json),
[실험 설명](validation/ntp-provider-rate/RESULTS.md),
[사용한 실험 코드 원본](validation/ntp-provider-rate/compare_rate.py)을 보존한다.
코드 원본의 경로는 당시 환경에 고정돼 있으므로 현장 실행 명령으로 사용하지 않는다.

| 사례 | 관측 요청 간격 | offset | 결과 |
|---|---|---|---|
| 기존 iburst | 2.007 / 2.037초 | 0.033ms | 로컬 요청 간격 <4초 관측; 운영 정책 위반 판정 아님 |
| 수정 후보 minpoll 3 / maxpoll 3 | 8.133 / 8.013초 | 0.035ms | 단일 진단 간격·정상 응답 확인 |
| 수정 후보 + 250ms 오차 | 8.069 / 8.111초 | 250.065ms | chronyd rc0이지만 로컬 100ms 판정은 FAIL |

**실험 기대조건 3/3 충족**이다. 기존 128/128 suite와 별도 기록이며 합산하여
전체 운영 지원 PASS로 표시하지 않는다. daemon 병행, 재시작 경계, 반복 실행,
NAT를 공유하는 다른 client의 요청 간격은 이 실험으로 검증되지 않았다.

## 운영 입력과 완료 조건

`CR-P1-NTP-01-01-runtime-input.example.json`의 `public_upstreams: []`를 유지한다.
위 표는 3기관 후보 확보를 뜻하며 세 주소가 현재 실행기에 모두 적합하다는 판정은 아니다.
1차 적용은 NIST를 제외한다. 실제 선택에 Netnod가 있으면 윤초 적합성을 확인하고,
선택 목록의 사용 조건·실제 정책·복구 경로를 기존 source/network/recovery 기록에
연결한 뒤 입력을 한 번 확정한다. NIST 간격 보장 구현·검증은 향후 NIST를
추가하는 별도 코드 변경에만 필요하다.

최종 AC는 **offset ≤100ms / 60초 간격 6회 / sync loss 5분 이상 FAIL /
재부팅 후 5분 이내 재동기화**를 유지한다. 주소 개수·단일 진단·LOCAL 시험·코드 리뷰로 대체하지 않는다.
네트워크 및 실패 복구는 [네트워크·복구 실행 계약](CR-P1-NTP-01-01-network-recovery.md)을 따른다.
