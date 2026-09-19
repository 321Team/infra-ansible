# CR-P1-NTP-01-01 PR28 후속 변경 검증

기준일: 2026-09-19 KST. 판정: **LOCAL/MOCK 301/301 PASS / SYNTAX 7/7 PASS / NEW_CODE_REVIEW_REQUIRED / RUNTIME NOT RUN**.

## 기준과 변경

기준 PR28은 `hayeounglee`가 `f7940d7fd29850e45f4197ea7ab97d74b35021aa`를 승인했고,
PR24 작업 브랜치에 `a51a7de0e7e7cebaa46bef318ab46808ceb2b835`로 병합됐다.
[조회한 승인·병합 원본 요약](validation/ntp-two-source/BASE_REMOTE.json)의 tree
`694f6af7709c4703757fb9a346260bf649c8912e`와 로컬 snapshot의 기준 tree가 일치한다.
로컬 snapshot commit은 GitHub의 실행 SHA로 사용하지 않는다.

이번 변경은 정확히 3개로 고정된 공인 시간원 입력을 2–3개로 확장하고,
renderer·migration·probe에 공통 지원 목록을 적용한다. `iburst` 구성에 대한
사용 조건 검토가 끝나지 않은 NIST와 임의 주소는 변경 또는 진단 실행 전에 거절한다.
Cloudflare 두 주소는 한 운영기관으로 집계한다. 빈 입력과 기존 내부 단일소스·수치 AC는 유지한다.
이 수정에 PR28의 기존 독립 승인을 소급하지 않는다.

## 이번 실행 결과

| 시험 | 기대결과 충족 | 실제 수행 범위 |
|---|---:|---|
| egress contract | 11/11 | 2·3개 목록, 거절 입력, 목적지와 운영기관 수 등 Python 단위시험 |
| migration | 81/81 | localhost 임시 파일의 생성·백업·멱등성·실패·복구와 실제 chronyd 파서; 서비스는 fixture |
| 기존 role 회귀 | 48/48 | localhost Ansible 조건·파일 작업 및 모의 서비스 |
| probe | 68/68 | 모의 관측 65개 + 실제 chrony 4.8/loopback NTP 3개 |
| rollout | 71/71 | 2·3개 통합 흐름, 실패 중단·입력/소스 고정·증적 모의시험 |
| wrapper | 19/19 | 기존 단계 순서·실패·잠금·증적 보존 회귀 |
| client 직렬 실패 | 1/1 | 실제 Ansible localhost 5-host fixture; 앞선 성공 보존/실패 host 복구/후속 미실행 |
| module_utils 패키징 | 2/2 | 실제 Ansible AnsiballZ 패키징·local 실행; 미지원 입력 변경 전 거절 |
| playbook syntax | 7/7 | Ansible core 2.16.19의 NTP playbook 구문 검사; 위 301건과 별도 |

probe의 실제 통신은 `127.0.0.1` 임시 responder만 사용했다. 외부 NTP 및 SSH 접속,
실제 6개 노드의 시간/chronyd/방화벽 변경은 수행하지 않았다. 패키징 시험도
`connection: local`이므로 원격 SSH·CS10·SELinux Runtime 검증으로 확대하지 않는다.
기존 128/128 및 과거 provider-rate 3/3 결과에 이번 숫자를 합산하지 않는다.

## 최초 실패와 재시험

최초 `/workspace` 아래 fixture에서 migration/rollout/wrapper/serial 4 suite가
상위 경로 쓰기 권한을 거부하는 기존 보호 조건 때문에 실패했다. 이 실패는
[원본 묶음](validation/ntp-two-source/raw-results.tar.gz)에 보존한다.
실행 코드·보안 가드·workspace 권한을 변경하지 않고 root 소유의 보호된 `/tmp`
fixture로 해당 4 suite만 재시험하여 위 결과를 얻었다. 실패를 숨기거나
첫 실행부터 전부 성공한 것으로 표시하지 않는다. 실행 전후 코드 SHA256 일치를 확인했다.

## 추적 및 한계

- [실행 명령·시각·종료코드·소스 해시·suite 집계](validation/ntp-two-source/SUMMARY.json)
- [원본 JSON·stdout/stderr·실행기 묶음](validation/ntp-two-source/raw-results.tar.gz)
- [원본 묶음 SHA256](validation/ntp-two-source/raw-results.tar.gz.sha256)

AI 정적 기술 검토에서 이 변경 범위의 신규 실질 차단사항은 발견하지 못했다.
이는 인적 독립 리뷰/APPROVED가 아니다. 정확한 새 HEAD의 기존 정책상 독립 리뷰가 필요하다.
GitHub CI는 별도 상태로 PR에서 확인하며 이 로컬 결과를 CI PASS로 쓰지 않는다.

Netnod 현재 주소·윤초 조건, 최종 시간원 채택, 실제 egress/내부 UDP 경로·복구
원문은 여전히 현장 입력 조건이다. Cloudflare 두 주소 선택 시 Netnod 확인은 비해당이지만,
단일 운영기관 의존과 두 source 상충 판별 한계를 기존 CR에 기록한다.
60초×6 / sync-loss 5분 / reboot 후 5분 재동기화는 실제 증적으로 별도 인수한다.
