# PR34 R2 — 작업창 기준과 실패 증적 보완

대상은 [리뷰 5263137368](https://github.com/321Team/infra-ansible/pull/34#pullrequestreview-5263137368),
검토된 R1 HEAD는 `3167665b12bbe1b69c0011e7f85baeda6c19c710`이다.
이 리뷰 자체는 **COMMENTED**이며 본문도 독립 승인이 아니라고 명시한다.
작업 중 R1의 동일 HEAD에 별도 [APPROVED 5263246569](https://github.com/321Team/infra-ansible/pull/34#pullrequestreview-5263246569)가
2026-09-21 14:15:47 KST에 등록됐고, GWONUK가 14:24:11 KST에
`aa4fad6db2fb14611aaf03a9126c8d5eb4623ed0`으로 병합했다.
병합 tree `88816fb4f6031e84a22ee2c159da41fe82f2a21a`는 승인 R1 tree와 같다.
따라서 완료한 R2 보완은 이 병합을 기준으로 별도 후속 PR에 게시한다.
R1 승인을 새 R2 코드 승인으로 확대하지 않으며, 이 대응을 배포 완료로 표시하지 않는다.

## 코드 수정 범위

### 1. 컨트롤러 작업창과 원격 경과시간 연결

작업창의 기준 시각은 `ansible01`의 UTC다. 원격 노드의 `datetime.now()`로
작업창 안팎을 판정하던 경로를 제거하고, 별도의 시계 관측 요청에서 받은
`boot_id`와 `CLOCK_BOOTTIME` 표본을 컨트롤러의 응답 수신 시각에 연결한다.
시계 관측은 NTP 시험 패킷을 보내거나 원래 journal·설정을 수정하지 않는다.

원격 만료 시점은 다음 관계로 고정한다.

```text
원격 만료값 = 관측된 원격 부팅 경과시간
            + (승인 작업창 종료 − 컨트롤러 응답 수신 시각)
            − 정리 여유 10초
```

원격 표본은 컨트롤러가 응답을 받기 전에 만들어진다. 따라서 지연은 사용 가능한
시간을 줄이고, 후속 요청의 도착 시점에 새 유효 시간을 부여하지 않는다. 같은 host의
후속 동작은 고정된 시계 연결값을 재사용한다. 부팅 ID 변경, 경과시간 역행 또는 만료는
STOP이다. 컨트롤러의 단계별 작업창·명령 timeout 검사와 패킷 직전 재검사를 유지한다.

Python의 [CLOCK_BOOTTIME 정의](https://docs.python.org/3/library/time.html#time.CLOCK_BOOTTIME)에
따라 시스템 suspend 시간을 포함하는 경과시간을 사용한다. 원격 벽시계의 시각 오차나
step을 승인 작업창의 확대 근거로 사용하지 않는다. `ansible01`의 UTC가 운영 기준으로
올바르다는 전제는 별도이며, 이 실행기는 컨트롤러나 노드의 시간을 수정하지 않는다.
SSH 중단 신호만으로 이미 실행 중인 원격 프로세스의 종료를 증명하지 않는 기존 한계도 유지한다.

### 5. 원래 실패와 보존 검사 실패를 함께 기록

검증 동작 실패 뒤 수행하는 보존 검사도 실패하면 두 원인을 각각 기록한다.
기존 `finally`의 새 예외가 원래 오류를 가리는 동작을 보완한다. 두 오류가 있더라도
성공으로 처리하거나 자동 복구하지 않으며, 이미 수집한 command 원문과 관측 근거를 보존한다.

### 6. 원격 모듈을 실행하기 전에 소스 해시 검사

컨트롤러의 초기 원격 모듈 로드에 고정 SHA256을 요구한다. 검사한 동일 바이트를
실행하며 캐시된 bytecode를 사용하지 않는다. 이후 Git HEAD/tree/clean 검사와 원격으로
보내는 코드의 해시 검사에서도 같은 고정값을 사용한다. 이 결합은 실제 리뷰 승인을
자동 판정하는 기능이 아니며 새 HEAD의 독립 리뷰가 필요하다.

## 나머지 항목의 근거와 유지한 경계

| 리뷰 항목 | 대응 / 수용 조건 |
|---|---|
| 2. baseline 범위 | 역사 기준은 구성 3개 파일·journal·kernel이다. 나머지 5개 파일은 새 preflight 이후만 비교한다. 11:13부터 preflight까지의 불변을 주장하지 않는다. |
| 3. nonfilter `-A` STOP | 11:13 수집본의 6대 IPv4·IPv6 모두 mangle/nat의 `-A`는 0개였다. raw/security는 출력에 없었다. 현재 K8s/CNI 규칙이 추가됐다면 의도적으로 STOP하고 새 원문과 경로를 검토한다. 허용 범위를 넓히지 않는다. |
| 4. 원격 180초 제한 | 기존 verify 호출 제한을 유지한다. 실제 소요 시간의 충분성은 미확인이다. timeout은 StateUncertain으로 중단하며 자동 재시도·rollback을 하지 않는다. |
| 7. 승인 참조 | `approval_ref`와 환경변수는 운영자가 입력한 결합값·절차 플래그다. 실제 승인 기록은 별도 확인한다. 임의 작업창이나 새 시간 상한을 만들어 승인 기준을 바꾸지 않는다. |
| 8. 실증 수준 | LOCAL/MOCK와 기본 모드 검증만 수행했다. 실제 패킷·DROP 카운터 검증과 전체 Runtime 인수는 미실행이다. CI 0건은 NOT RUN이다. |
| 9. 병합 순서 | PR34 R1은 정확한 HEAD 승인 후 `cr-p1-ntp-01-01`에 병합됐다. R2는 별도 후속 PR의 정확한 HEAD 승인·병합 판단이 필요하다. PR24 main 병합은 당시 누적 최신 HEAD의 별도 검토 대상이며 자동 승인·병합하지 않는다. |

3번 근거는 `ntp-pr31-post-egress-pdv_sd3n.tar.gz`의 6개 host 로그와 committed fixture의
18개 원문(`iptables-save`, `ip6tables-save`, `nft-ruleset`)을 바이트 대조한 결과다.
18개 모두 rc 0, timeout/truncation 없음이 확인됐다. filter 규칙 수는 control01 IPv4 7개,
나머지 IPv4 각 6개, IPv6 각 2개다. 당시 원문의 정확한 일치이며 현재 운영 상태의 증거는 아니다.
수집본 SHA256은 `11ea3cf62d3709d902120aca58264f6160725f5045568d4040d4119e54c7b7a9`다.

## 검증과 운영 상태

R1의 96 tests / 442 subtests와 기본 모드 점검은 당시 범위의 이력으로 보존한다.
R1 소스로 원격 시계가 10분 느릴 때 만료된 컨트롤러 작업창 뒤 모의 패킷 허용,
변조된 원격 모듈의 초기 실행, 보존 오류가 원래 작업 오류를 가리는 현상을 재현했다.
이는 실제 서버·네트워크 동작이 없는 LOCAL/MOCK 재현이다.

R2는 기존 onepass 50개, 기존 후속 시험 46개, 새 회귀 시험 19개를 합친
**115 tests / 494 subtests PASS**, 실패·오류 0이다. post-egress 시험 전체에서
실제 `Popen`·`socket` 호출 금지 단언이 통과했다. 원격 벽시계 편차·step, 지연 도착,
재부팅·부팅 경과시간 역행, 응답 결합·컨트롤러 시간 예산, 실행 전 해시 검사,
작업·보존·최종 journal 오류의 동시 보존을 포함한다.

별도로 실제 기본 CLI를 깨끗한 로컬 Git 소스와 합성 입력에서 실행했다.
`FOLLOWUP_OFFLINE_PREPARED_NOT_EXECUTED`, 원격 요청·시계 조회 0,
증적 manifest 일치를 확인했다. 로컬 Git 명령은 실행했고 SSH·방화벽·패킷은
실행하지 않았다. 합성 입력의 날짜와 참조는 운영 승인·작업창이 아니다.

- [R2 검증 요약·파일 해시](validation/ntp-post-egress-r2/SUMMARY.json)
- [R2 시험 로그](validation/ntp-post-egress-r2/focused-tests.log)
- [수정 전 R1 재현 결과](validation/ntp-post-egress-r2/R1-reproductions.json)

AI 독립 정적 점검에서 추가 차단사항을 발견하지 못했으며, 이를 사람의 독립 승인으로
표시하지 않는다. CI와 실제 운영 Runtime은 NOT RUN이다.

이번 보완 작업에서는 병합·실서버 파일 배치·원격 실행을 수행하지 않았다. PR34 R1의
사용자 병합은 위에 구분해 기록했다. 기존 작업창은 만료됐고 새 작업창은 미정이다.
이 대응 뒤에도 정확한 R2 HEAD의 독립 승인, 실제 운영 판단과 작업창이 필요하다.
