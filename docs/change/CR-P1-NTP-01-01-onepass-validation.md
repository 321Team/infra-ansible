# NTP 단일 실행 후보 — 변경·검증 기록

상태: **LOCAL/MOCK 63/63 PASS / 신규 정확 HEAD 독립 리뷰 필요 / RUNTIME NOT RUN**.

현장 수집에서 control01 UDP123 수신 차단과 최종 NTP 송신 제한 부재를 확인했다.
기존 승인 실행기는 chrony 전환을 처리하지만 방화벽 준비는 수행하지 않으므로,
새 controller와 원격 방화벽 엔진으로 준비·전환·제한·검증·증적 포장을 연결했다.

- 기존 PR29 병합 `eb08dc8c4ae3505dace39e76a11ef57be75e96ce`의 **118개 추적 파일 내용·실행 mode 불변**.
- 기존 실행기는 별도 clean checkout에서 호출한다. 새 wrapper와 기존 실행 소스를 각각 결합한다.
- 새 범위: controller/remote 각 1개, 시험 2개, 입력 예제·런북 및 이 검증 기록.
- firewalld rich rule은 5개 client `/32`만 허용한다. 송신 제한은 전체 NTP 전환 성공 후 적용한다.
- reload 없는 신규 policy 생성이 지원되지 않아 scoped direct chain을 사용한다.
  폐기 예정 인터페이스 의존 및 NEW 세션에만 적용하는 범위는 [런북](CR-P1-NTP-01-01-onepass.md)에 명시했다.

## 검증 범위

| 검증 | 결과 | 확인 범위 |
|---|---:|---|
| Controller LOCAL/MOCK | 35/35 | 단계 차단·부분 실패·소스/입력 변조·실제 Git 두 checkout·child 원문 gate 검증·실제 subprocess 잠금 상속·표본 간격·상태 불명확 |
| Firewall LOCAL/MOCK | 28/28 | 범위 고정·변경 전 journal·기존 규칙 보존·부분 복구·registry/kernel 불일치·Negative 카운터·표본 parser |
| 실제 로컬 stdin 전달 | PASS | Python `-I -B -`로 코드를 전달하고 잘못된 host를 journal/방화벽 접근 전에 거부 |
| 정적 검사 | PASS | Python 4개, Bash 블록 2개, JSON 6개 키, diff 공백 검사 |
| 기존 시험 | 재실행 안 함 | 변경 없는 PR29의 301/301·syntax 7/7 이력을 재사용 |
| CI / 현장 Runtime / 최종 AC | NOT RUN | 로컬 시험으로 확대하지 않음 |

초기 controller fixture는 workspace의 쓰기 가능한 상위 경로를 실제 보안 guard가
거부해 보호된 `/tmp`에서 다시 실행했다. guard나 시스템 권한은 완화하지 않았다.
별도 fixture가 의도적으로 설정한 `ANSIBLE_NOCOLOR`까지 오염으로 판정한 항목은
fixture만 정정했다. 최초 실패와 재시험 원문을 함께 보존한다.

AI 코드 검토에서 표본을 배치 시작 기준으로 예약하면 host별 간격이 짧아질 수 있는 점과,
복구 중 `REMOVE_PREPARED`를 상태 불명확으로 구분해야 하는 점을 수정했다.
현재 확인한 범위에 남은 확정 코드 차단 사항은 없다. 이 검토는 사람의 GitHub APPROVED가 아니다.

원문·최종 파일 해시는 [SUMMARY.json](validation/ntp-onepass/SUMMARY.json)과
[raw-results.tar.gz](validation/ntp-onepass/raw-results.tar.gz)에 연결했다.
무결성은 동작·인수의 대체 증거가 아니다.

## 남은 실행 조건

신규 코드의 정확한 HEAD 독립 리뷰·병합 및 실제 network/recovery 참조가 필요하다.
기존 선정 결정 URL을 두 참조에 복사하거나 생성 파일만으로 미확인 상위망·복구 승인을
완료 처리하지 않는다. 단계별 반복 승인은 추가하지 않는다.

IPv4 Negative는 신규 test flow와 전용 DROP 카운터의 대조다. IPv6 정책 존재 확인은
IPv6 실제 패킷 시험이 아니며 기존 conntrack 세션도 유지한다. 재부팅·동기화 상실 시험과
기존 AC 인수는 실제 후속 결과로 판단한다. 이번 작성 중 현장 서버·방화벽·시계를 변경하지 않았다.
