# CR-P1-NTP-01-01 — chronyd 빈 OPTIONS 기본값 수정 기록

상태: **수정 및 소스 결합 후보 / 독립 리뷰 대기 / 이 후보의 Runtime NOT RUN**.
기준일: 2026-09-21 KST. 실행 절차는 [OnePass 런북](CR-P1-NTP-01-01-onepass.md)을 따른다.
PR29·PR30의 기존 승인을 이번 변경의 승인으로 재사용하지 않는다.

## 현장 중단과 원인

`ntp-onepass-1vu26i8b.tar.gz` 실행은 2026-09-21 **00:16:36–00:17:21 KST**에
control01 수신 준비를 마친 뒤 6대 diagnose에서 중단됐다. 공통 오류는
`Inline chronyd Environment needs a separate restart review`였다.
입력 검증, SSH 및 수신 규칙 추가는 진행됐으므로 전체 실행을 무변경으로 표시하지 않는다.

`ntp-chronyd-environment-xkmf5tss.tar.gz`의 읽기 전용 후속 수집은 같은 날
**00:41:43–00:41:47 KST**, 6대 COMPLETE다. 6대 모두 다음 사실이 일치한다.

| 항목 | 관측값 |
|---|---|
| `systemctl show ... --property=Environment --value` | `OPTIONS=` 뒤 줄바꿈, 즉 값이 빈 단일 변수 |
| unit의 기본값 | `Environment=OPTIONS=""` |
| unit의 파일 | `EnvironmentFile=-/etc/sysconfig/chronyd` |
| 파일에 지정된 값 | `OPTIONS="-F 2"` |
| unit 실행 명령 | `/usr/sbin/chronyd -n $OPTIONS` |
| 실제 프로세스 argv | `/usr/sbin/chronyd`, `-n`, `-F`, `2` |

systemctl 출력 9바이트(`OPTIONS=\n`)의 SHA256은
`29b7b5a5e52063c021fb5d1a66349e920ca5c84f8d711439e34b8c94595ff654`다.
기존 probe는 inline 환경 출력이 조금이라도 있으면 차단했다. 빈 기본값과 파일의
검토 가능한 OPTIONS를 구분하지 않아 현장 기본 unit을 차단한 것이 이번 수정 대상이다.
서버의 unit·환경변수·sysconfig를 지우거나 바꾸는 방법으로 우회하지 않는다.

## 최소 변경과 유지한 검사

`library/fds_ntp_probe.py`의 재시작 사전검사에서 `systemctl` 조회 성공 시 출력의
양끝 공백을 제거한 결과가 **빈 문자열 또는 정확히 `OPTIONS=`**인 경우만 허용한다.
일반적인 shell/systemd 환경문법 파서를 새로 도입하거나 다른 변수를 허용하지 않는다.

- 비어 있지 않은 OPTIONS, 추가 변수, 중복 OPTIONS, 따옴표 변형·잘못된 문법, 조회 실패는 계속 차단한다.
- `EnvironmentFiles` 허용 경로, sysconfig OPTIONS 파싱과 기타 지시문 거부를 유지한다.
- 다음 재시작 argv의 옵션·설정 경로 검사 및 실제 `/proc` argv와의 일치 검사를 유지한다.
- 증적의 기존 `empty` 의미는 유지한다. `accepted_empty_options_default`는 이 빈 기본값을
  정상 조회하여 인정한 경우만 true다. 다른 환경변수의 값은 증적에 기록하지 않는다.

## 00:41 기준 서버 상태와 보존 범위

| 항목 | 확인 범위 |
|---|---|
| control01 수신 규칙 | `.103/.104/.105/.107/.108 → .102 UDP/123`, runtime 5개·permanent 5개 존재 |
| 변경 소유권 | 이전 run의 해당 10개 `group/state/object`가 기존 증적과 일치, 모두 `ADDED` |
| chrony 적용·재시작 | 00:17 실행의 source/client 적용 단계 미착수 |
| 송신 제한 | 00:17 실행의 egress 단계 미착수 |
| 공인 NTP 응답·전환 후 표본 | 00:17 실행에서 미수행; 이 후속 수집도 해당 시험을 하지 않음 |

이전 run ID는 `ntp-onepass-c112dd98ad56453e86f5c648e54f2cce`이며 control01 journal은
`/var/lib/fds-ntp-onepass/ntp-onepass-c112dd98ad56453e86f5c648e54f2cce/state.json`이다.
기존 수신 규칙 10개와 이전 journal을 보존한다. 후속 실행은 이미 있는 규칙을
`PREEXISTING`으로 취급하며 이전 실행의 소유권을 가져오지 않는다.

후속 수집의 journal 파일 SHA는 들여쓰기·마지막 줄바꿈을 포함한 원문 해시다.
기존 응답의 `state_sha256`은 `sort_keys=True, separators=(',', ':')`의 canonical JSON
해시이므로 두 문자열을 직접 비교하지 않는다. 이번 확인은 10개 operation의 지정 필드와
실제 규칙 존재까지이며 전체 journal 내용 동일성을 새로 입증한 것은 아니다.

## 검증과 소스 결합

최소 probe 변경의 기존 로컬 결과 **102/102 LOCAL/MOCK PASS**를 재사용한다.
기존 65개와 신규 37개 사례이며, 6대×2 gate 사실 재현, 선택적 파일 부재,
argv drift, 다른 설정 경로, 기타 sysconfig 지시문, 알 수 없는 환경파일,
조회 실패, 잘못된 inline 값과 민감값 비기록을 포함한다.
실제 chronyd loopback 실행은 0건이며 이 시험이 서버 Runtime을 대신하지 않는다.

별도 `FIELD_REPLAY.json`은 제공된 6대의 관측값을 사용해 `inspect_restart()`만 로컬
재현했다. 기존 소스는 6/6 차단, 수정 소스는 6/6 인정하고 다음 argv를
`/usr/sbin/chronyd -n -F 2`로 계산했다. SSH·NTP 패킷·서비스 조작은 하지 않았다.
결과 원문과 새 소스 결합 시험의 구분은
[검증 요약](validation/ntp-empty-options/SUMMARY.json)에 기록한다.

소스 결합은 두 commit으로 구성한다.

| 소스 | 식별·역할 |
|---|---|
| R1 별도 rollout checkout | `0e17e2d7713484352c84f72d9ddc55aab6187386`, tree `3978af25d4489de68590af3fc5d86191e97beb5b` |
| 최종 wrapper checkout | R1 SHA/tree를 고정하는 후속 commit과 문서·검증 자료. 최종 전체 HEAD는 리뷰·병합 단계에서 확정 |

R1은 PR30 병합 `b9ba8cb8a2bb838f35b926648aa354b88c7e743f`에서 probe와 해당 시험
2개 파일만 바꾼 소스다. 기존 eb08 소스를 요구하던 OnePass에 R1 소스만 전달하면
결합 검사에서 중단되므로 wrapper의 고정 SHA/tree와 입력도 함께 갱신한다.
R1 SHA는 이미 확정된 결합값이며 독립 승인 완료를 뜻하지 않는다. 최종 wrapper의
자기 SHA를 문서·소스에 미리 하드코딩하지 않는다.

## 재개 입력과 남은 단계

입력 계약은 기존 **6키**를 유지한다. `reviewed_source_sha`는 위 R1,
`reviewed_wrapper_sha`는 새 최종 독립 검토·병합 HEAD다. 선정 Cloudflare 두 주소와
`source_policy_ref`는 기존 결정 그대로다. 다음 두 운영 문서 경로도 재사용한다.

- `network_policy_ref`: `/home/server01_ansible/ntp-refs/CR-P1-NTP-01-01-NETWORK.md`
- `recovery_ref`: `/home/server01_ansible/ntp-refs/CR-P1-NTP-01-01-RECOVERY.md`

기존 담당 이권욱, 실행 계정·호스트, 6대 대상과 chronyd restart·step 가능 영향 범위는
유지한다. **새 작업창은 아직 미정**이다. 이전 2026-09-20 23:53:19–2026-09-21
00:53:19 KST 작업창과 입력은 과거 실행 기록으로 보존하고 재개 시간으로 간주하지 않는다.

현재 후보의 `--apply`는 실행하지 않는다. 새 최종 소스의 독립 리뷰·병합과 실제 재개
작업창을 반영한 배포 입력이 준비되면 별도 clean checkout 두 개를 사용하는 런북으로
재개한다. 수신 규칙이 이미 있다는 이유로 삭제·재추가하거나 전체 재수집을 반복하지 않는다.
기존 최종 AC와 장애·재부팅 검증 범위는 변경하지 않는다.
