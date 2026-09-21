# PR32 R2 — 테이블별 OUTPUT_direct 구분과 리뷰 대응

대상: [PR32 리뷰 5262713527](https://github.com/321Team/infra-ansible/pull/32#pullrequestreview-5262713527).
리뷰된 R1 HEAD는 `f7c913db80dc5cdd1f5583386ef9bb58803766bf`다. 이 기록은 R2의
수정·로컬 검증 근거이며 사람의 승인·병합·배포·최종 인수 완료를 의미하지 않는다.

## 지적과 수정

R1은 `filter` 밖의 일반 `OUTPUT_direct`를 NTP 전용 체인처럼 제한했다.
선언뿐 아니라 참조 검사도 같은 오류를 포함했다. R2는 두 검사를 모두 구분한다.

| 대상 | R2 처리 |
|---|---|
| 다른 테이블의 일반 OUTPUT_direct | 테이블별 이름 공간으로 구분; 동명 선언·참조만으로 STOP하지 않음 |
| 다른 테이블의 FDS_NTP_0101 | 선언·참조·goto·체인 본문 모두 계속 거부 |
| filter의 OUTPUT_direct | bridge와 내부 훅의 정확한 구성, 누락·중복·혼합·외부 참조 검사 유지 |
| 선행 OUTPUT 경로 | 기존의 정확한 KUBE DROP 구성 또는 빈 경로만 허용; ACCEPT 허용 범위 확대 없음 |

실행 코드 변경은 `kernel_topology()`의 두 조건과 설명 주석에 한정한다.
승인 목적지·NEW UDP123·규칙 순서·journal·소유권·변경/복구 동작은 바꾸지 않는다.

## 공식 구현 근거와 현장 증거의 구분

[firewalld v1.3.4 ipXtables.py](https://github.com/firewalld/firewalld/blob/v1.3.4/src/firewall/core/ipXtables.py)의
`BUILT_IN_CHAINS`와 `build_default_rules()`를 직접 확인했다. 사용 가능한
`security`·`raw`·`mangle`·`nat` 테이블에서 각각 OUTPUT를 포함한 기본 체인의
`*_direct` 선언과 연결을 생성한다. 따라서 다른 테이블에 OUTPUT_direct가
없다고 가정할 수 없다. [공식 direct 문서](https://firewalld.org/documentation/man-pages/firewalld.direct.html)도
테이블 속성과 내장 체인의 `_direct` 구성을 설명한다.

이는 공식 구현 근거이며 실제 indirect 운영 환경의 iptables-save 원문은 아니다.
현재 제공된 운영 증적 `pdv_sd3n` 6대는 직접 OUTPUT 연결이다. 아래 시험은
현장 원문 replay와 그 원문을 바탕으로 만든 합성 간접 연결·타 테이블 변형을
명확히 구분한다. 리뷰 요청 (a)의 실제 indirect 원문을 확보했다고 주장하지 않는다.
공식 구현으로 오탐 가능성을 확인하여 코드를 수정했으며, 이 근거와 제한 범위의
충분성은 새 HEAD의 독립 리뷰에서 판단한다.

공식 v1.3.4 iptables backend의 기본 OUTPUT에는 RELATED,ESTABLISHED 및 loopback ACCEPT가 선행하는
형태도 있다. 현재의 엄격한 선행 경로 검사는 이를 계속 STOP시킨다. **일반 legacy
환경 전체 호환·무회귀는 미검증**이며 이번 수정으로 지원 범위를 확대하지 않는다.
다른 테이블의 NAT·NOTRACK 등 전체 패킷 경로를 검증한 것도 아니다.

## LOCAL/MOCK 검증

| 검사 | 결과 |
|---|---|
| 기존 PR32에 새 정상 namespace 사례 적용 | 32/32 기존 STOP 재현(RED) |
| R2 정상 namespace 사례 | 32/32 PASS |
| 기존 + 보완 focused suite | 50 tests, 289 subtests; 실패 0, 오류 0 |
| 실제 SSH·방화벽·패킷 실행 | 0회; subprocess/socket 금지 guard 호출 0 |
| 공백 검사 | git diff --check PASS |

정상 32조합은 IPv4/IPv6 × 직접/간접 연결 × 4개 비filter 테이블 × 선언만/정상 bridge
형태를 시험한다. 추가 실패 조합은 정상 타 테이블 체인이 있어도 filter의 훅 누락·중복·
범위 변경·선행 ACCEPT·bridge 누락을 숨기지 못하는 72조합, 전용 체인의 다른 테이블
선언 16조합, 참조/goto/본문 48조합이다. 기존 직접 현장 replay·간접 합성·순서·소유권·
복구 관련 focused 시험을 포함한다.

재현 명령(방화벽/SSH를 호출하지 않는 focused 시험):

```bash
python3 -I -B -m unittest discover -s tests/ntp_source -p 'test_onepass_*.py' -v
```

| 파일 | SHA256 |
|---|---|
| R1 remote source | 7cc2726eabdeb6156eb5f84a3f10a517084a62ce85424239dfcd3ad286a03efb |
| R2 remote source | ccdfd29e6d4821e4205963990b7c29af879240b1aae76c40119966fc67eebf50 |
| R2 layout tests | 1a1550184a72fc0f4f2e31954ccc5a21fe253d54fa5870503609ffd34bbdf9ea |

R1의 46 tests 통과는 당시 시험 범위의 결과였으며 다른 테이블의 일반 체인을
과잉 차단하는 결함을 발견하지 못했다. 새 정상 사례를 먼저 R1에서 실패 재현한 뒤
R2에서 통과 확인했다. LOCAL/MOCK 결과를 CI나 실제 indirect 운영 검증으로 표시하지 않는다.

## 나머지 리뷰 대응

- KUBE-FIREWALL 본문·주석·조건·순서 변경 시 STOP 후 원문/journal 보존 및 재검토를
  [운영 절차](CR-P1-NTP-01-01-onepass.md#커널-경로와-재검토-조건)에 명시했다.
- R1 HEAD의 GitHub Actions run·check-run·commit status 조회는 모두 0건이었다.
  CI는 NOT RUN이며 R2의 검사 상태는 게시 후 별도로 확인한다. 이 변경에 새 CI 실행기나
  서버 접근 workflow를 추가하지 않는다.
- 진단 receipt의 expected/actual 차이 보존은 비차단 후속 [이슈 #33](https://github.com/321Team/infra-ansible/issues/33)으로 분리했다.
- 병합 순서는 PR31(완료) → PR32를 `cr-p1-ntp-01-01`에 반영 → 상위 PR24의 누적 변경을
  별도 검토 후 `main` 병합이다. PR32 승인만으로 상위 PR24의 승인·병합을 대신하지 않는다.
- 기존 작업창은 2026-09-21 11:35 KST에 만료됐다. 실서버 후속 검증은 기존 설정과 run
  journal을 보존하는 별도 경로의 리뷰·승인 및 새 작업창이 필요하다. 전체 apply 재실행,
  기존 배포 ZIP 덮어쓰기, 자동 작업창 연장은 이번 대응 범위가 아니다.

11:13 단회 관측의 동기화 상태를 현재 상태나 최종 인수로 확대하지 않는다. IPv4 음성
시험·후속 허용 경로·60초 이상 간격 6회 표본 및 장애/재부팅 등 잔여 AC는 별도다.
