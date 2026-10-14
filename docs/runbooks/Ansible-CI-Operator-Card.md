# Ephemeral Runner — 운영자 실행 카드

대상: infra-ansible #61, `ansible-isolated` Job 한 건. [상세 런북](Ansible-CI-Ephemeral-Runner.md), [CI 설명](Ansible-CI.md). 기존 v1.3 launcher를 사용한다. 문서·코드 승인과 새 공급 회차 승인을 구분한다.

| 순서 | 실행·확인 | 정상/중단 기준 |
|---|---|---|
| 1. 회차 고정 | PR full HEAD, Run/Attempt/Job, 필수 5 labels, 실행자/복구 인수자, 시작 상한·종료 시각 기록 | source/대상/창 미확정이면 STOP. 완료·취소된 Job에 공급하지 않음 |
| 2. 읽기 점검 | 아래 조회 결과·hash와 현재 matching Runner/기존 세션을 확인 | idle online 또는 대상 in-progress면 추가 공급 금지. busy/unknown·API 오류는 자동 미공급 판정 금지 |
| 3. prepare·인증 | 기존 정상 로그인 계정·호스트·HOME, launcher/input guard manifest·PREPARED identity 대조. 운영자가 같은 TTY에서 sudo 인증 | 다른 계정/HOME 조작으로 인증 우회 금지. 인증 대기 종료를 CI 실패로 표시하지 않음 |
| 4. fresh 확인·serve | 인증 확인 후 HEAD/Job/중복을 다시 확인하고 fresh token을 기존 안전 전달 경로로 전달, 1회 serve | 만료된 operator 파일/packet 재사용 금지. 채팅 답변만으로 살아 있는 인증 세션이라고 판단하지 않음 |
| 5. Job 결속·관측 | Runner ID/name↔Job, 실제 checkout SHA, regression과 upload 결과를 구분 | PR HEAD 변경·다른 Job 수신·시작 상한 경과 시 다음 단계 STOP. 취소/정리는 해당 회차 복구 계획으로 판단 |
| 6. 종료·회수 | deregister·runner/proxy/workspace 제거, 서버와 GitHub 부재, 양쪽 token packet 폐기 확인 | rc0/Runner0만으로 전체 완료 아님. raw/ZIP/hash/실패본 보존; 다른 회차나 장기 Runner를 삭제하지 않음 |
| 7. 인수 | 아래 필드로 결과·한계·원본 보관/수신을 연결 | 회차 증적 편입≠운영자 이중화·장기보존·티켓 Close |

## queued 조회와 담당 전달

조회 위치는 `gh` 읽기 권한이 있는 승인된 관리 PC/컨트롤러의 검토된 checkout이다. Python 3.11 이상을 사용한다. Windows 콘솔 출력은 ASCII JSON escape, 저장 파일은 UTF-8이다. 기존 비공개 증적 폴더에서 새 출력 이름을 사용한다. Windows의 접근 제한은 실제 ACL로 확인하며 POSIX `0600` 요청만으로 비공개 보장을 주장하지 않는다.

```text
python -I -B tools/ansible-ci-queue-watch.py --job-id <JOB_ID> --expected-source-sha <FULL_HEAD> --threshold-minutes <회차에_명시한_분> --output <새_비공개_JSON_경로> --strict
```

- rc0: 조회 완료. 분류를 읽어 판단하며 CI PASS나 공급 GO가 아니다. `JOB_COMPLETED`이면 이 회차 감시 종료·추가 공급 금지.
- rc2: 공급 담당자의 판단 필요. repository/PR/HEAD/Run/Attempt/Job, 관측 시각·classification, Runner 상태, 시작 상한, 증적 위치만 승인된 연락 경로로 전달한다. token/credential은 보내지 않는다.
- rc1: 조회/identity/출력 실패. 기존 JSON을 최신 결과로 재사용하지 않는다. API 오류를 Runner 미공급으로 바꾸지 않는다.
- 이 도구는 1회 조회이며 상시 scheduler·Discord/메일 전송 기능이 없다. 감시 주기·threshold·담당/대체 담당·연락 경로를 회차에 기록하고 **미확정 상태를 운영화 완료로 표시하지 않는다**. 자동 공급·rerun/cancel은 하지 않는다.

상시 대기 알림의 구현·설정·수신 인수는 [queued 알림 카드](Ansible-CI-Queue-Alert.md)를 따른다. 새 알림은 장기 대기까지만 발견하고 이 카드의 Runner 상태 판정을 대체하지 않는다. 기본 비활성인 코드의 병합과 실제 운영 인수를 구분한다.

## 인증 대기와 실패 분류

PR75/76의 operator는 `AUTH_READY` 뒤 최대180초 대기하고, 최신 preflight90초 이내·대상 identity·중복 방지를 확인했다. 이 값은 해당 회차 실적이며 모든 새 회차의 무기한 인증/전역 정책이 아니다. 새 operator는 자신의 검토된 시간 상한을 명시한다. 만료 시 종료 결과·packet 부재를 확인하고, 새 회차 준비 없이 예전 파일을 재실행하지 않는다.

실패는 `AUTH_OR_INPUT_TIMEOUT` / `RUNNER_SUPPLY_FAILURE` / `REGRESSION_FAILURE` / `ARTIFACT_UPLOAD_FAILURE` / `JOB_CANCELLED_OR_REPLACED` / `CLEANUP_FAILURE`로 구분한다. 실패 원본은 보존한다. 예산 부족이면 새 serve를 시작하지 않는다. sudo 암호·token 값/해시·개인키를 로그에 남기지 않는다.

## 회차 증적·인수 필드

`repository, PR, source SHA, Run, Attempt, Job, Runner ID/name, labels, 운영자, 대체/복구 인수자, 창, 관측/인증/공급/Job/정리 시각, regression/upload 각각의 결과, operator rc, cleanup 각 항목, 서버/GitHub 부재, packet 양단 폐기, archive/manifest SHA256, 원본 보관 위치·인수자·수신 시각·보존 종료 기준, 검증 한계`를 남긴다. 토큰 자체나 토큰 해시는 제외한다.

재사용할 기존 회차: [PR75 증적188](https://github.com/321Team/fds-project-evidence/pull/188), [PR76 증적192](https://github.com/321Team/fds-project-evidence/pull/192). #192 merge `04befee9b36f1f7477989dbfd347a110db34f4ac`, Job113706062449, 검사 source `0d58598d8a3ce77ccd7eaa9e1dfba820b0a436ea`. 이 Job은 완료됐으므로 교육/증적 수집을 이유로 재공급하지 않는다.

운영자2명 인수는 사람별로 정상 계정 접속/인증 가능 여부, preflight·STOP 판단, 승인된 실제 회차의 공급·실패·회수 수행 또는 기존 유효 수행 참조를 기록한다. 이름 지정이나 이 문서 열람만으로 수행 가능을 확정하지 않는다. 2026-10-14 [최종 요구 대조](https://github.com/321Team/infra-ansible/issues/61#issuecomment-6162176817)에 기존 수행·수신·보존 처분을 연결했다. 지속 알림 운영은 [#82](https://github.com/321Team/infra-ansible/issues/82), 대상 전환·중단·종결은 [알림 런북](Ansible-CI-Queue-Alert.md)의 전환 절차를 따른다. 기존 회차를 반복 실습하지 않는다.
