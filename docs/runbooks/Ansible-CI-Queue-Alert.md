# Ansible 격리 Job 대기 알림

대상은 [infra-ansible #61](https://github.com/321Team/infra-ansible/issues/61)의 상시 queued 감시·담당 알림 잔여다. 기존 [운영자 카드](Ansible-CI-Operator-Card.md)의 공급·인증·회수 절차와 `ansible-ci-queue-watch.py` 분류기는 유지한다. Phase 1 범위이며 새 Runner·공급 broker·운영 서비스는 만들지 않는다.

## 동작과 권한

`ansible-ci-queue-alert.py`는 고정 저장소의 `ansible-regression.yml`에서 활성 Run과 정확한 Attempt의 Job을 읽는다. 필수 5 labels가 모두 있는 queued Job의 대기 시간이 선택한 threshold 이상이면 `ATTENTION`, 시간이 없거나 이상해도 `ATTENTION`, API 오류·목록 잘림은 `READ_ERROR`다. 다른 Job이 실행 중인 Run 안의 queued Job도 읽도록 `queued/in_progress/requested/waiting/pending`을 조회한다. 시간 계산에 오래된 Run 생성시각을 대신 쓰지 않는다.

Runner 목록은 조회하지 않는다. GitHub의 [Runner 목록 API](https://docs.github.com/en/rest/actions/self-hosted-runners#list-self-hosted-runners-for-a-repository)는 Administration read 권한이 필요하기 때문이다. 새 관리 PAT를 두지 않고 Actions read로 확인되는 **장기 대기 알림**까지만 수행한다. 알림을 받은 운영자는 기존 허용된 관리 경로에서 queue-watch를 한 번 실행해 online/idle/busy/offline/미공급을 구분한다. 알림만으로 미공급·공급 GO를 선언하지 않는다.

실행 위치는 GitHub hosted `ubuntu-latest`다. PR 코드를 실행하는 이벤트는 없으며 고정 저장소 `main`의 정확 SHA만 checkout한다. Actions checkout/upload-artifact는 기존 workflow와 같은 commit으로 고정한다. 기존 self-hosted Runner나 Harbor 작업창을 사용하지 않는다.

| 실행 | 필요 권한 | 외부 변경 |
|---|---|---|
| 수동 `notify=false` | Contents read, Actions read | 없음. 관측 JSON·SHA artifact만 저장 |
| 채택 후 주기 실행 / 수동 `notify=true` | 위 두 권한 + Issues write | 상태가 바뀐 경우 고정 #61에 댓글 한 건 |

Issues write 자체는 저장소 이슈 전체에 유효하다. 코드가 허용하는 쓰기 API는 #61 댓글 추가 하나이고, issue 본문·라벨·담당·종결은 바꾸지 않는다. 기존 `GITHUB_TOKEN`만 사용하며 별도 Secret·PAT·Runner token을 만들지 않는다. read-only 수동 Job에는 Issues write가 없다. [GitHub token 권한](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions)과 저장소/조직의 실제 정책을 함께 확인한다.

## 설정과 채택할 값

현재 기본 상태는 **비활성**이다. source PR 병합만으로 운영 인수 완료가 되지 않는다. 다음 repository variables를 실제 운영자가 확인한 값으로 설정한 뒤 켠다.

| 변수 | 값 / 검토할 사항 |
|---|---|
| `ANSIBLE_QUEUE_ALERT_ENABLED` | 정확히 `true`일 때만 발송. 해제/`false`가 중지 방법 |
| `ANSIBLE_QUEUE_ALERT_THRESHOLD_MINUTES` | 정수1~1440. 후보10분, 아직 운영값으로 채택하지 않음 |
| `ANSIBLE_QUEUE_ALERT_RECIPIENTS` | 담당·대체자의 GitHub login을 쉼표로 연결, 공백 없이1~5명. 팀 slug 불가. 실제 연락 담당은 최소2명을 정하고 서로 다른 사람의 수신·수행을 확인 |

### 실행 시간과 야간 대응

[PR81 R1 검토](https://github.com/321Team/infra-ansible/pull/81#pullrequestreview-5497322141)에 따라 schedule은 UTC `7,37 0-14 * * *`, 즉 **매일 KST 09:07~23:37에 30분 간격, 하루30회**다. threshold 후보10분은 유지하며 실제 변수 설정은 운영자가 채택한 값을 사용한다. 30분은 조회 간격이고 threshold는 Job이 대기한 시간의 판정 기준이므로 서로 다르다.

주간에 예정된 조회가 모두 실행되면 threshold10분인 Job은 대기 시작 후 대략10~40분 사이에 처음 알림 대상이 된다. 그러나 **23:37~다음 날09:07에는 예정된 조회가 없으므로 9시간30분의 감시 공백**이 있다. 마지막 조회 때 아직 threshold에 못 미친 Job은 다음 날까지 대기할 수 있어 야간에도40분 안에 발견한다고 해석하면 안 된다. [GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)은 지연·누락될 수 있으므로 이 값들은 SLA나 최대 통지시간 보장이 아니다.

이 구성은 24시간 자동 감시를 충족하지 않는다. 야간에 실제 Ansible 작업을 진행하는 운영자는 기존 운영자 카드의 수동 queue-watch와 승인된 연락 경로로 그 회차를 관측한다. 작업이 없는 밤에 사람의 상시 대기를 자동 지정하지 않는다. 야간 작업의 관측자·전달/수신 경로 또는 대응 가능 여부가 정해지지 않았다면 해당 공백을 미해소로 남기며 #61의 운영 인수 전체를 완료 처리하지 않는다. 기존 수동 preflight는 유지한다.

### hosted 사용량과 활성화 전 확인

현재 저장소는 private이며 조직의 Free plan은 standard GitHub-hosted 실행시간을 **조직 전체에서 월2,000분** 공유한다. [GitHub 포함량](https://docs.github.com/en/billing/concepts/product-billing/github-actions)과 [Job별 분 단위 올림](https://docs.github.com/en/billing/reference/actions-runner-pricing)을 기준으로 계산한다. 실제 플랜·잔여량·지출 제한은 활성화 직전에 다시 확인한다.

| 기준 | 예정 Job 수 | Job당 과금1분을 가정한 사용량 |
|---|---|---|
| 이전24시간·10분 주기 | 하루144회 | 30일4,320분 |
| 이번09:07~23:37·30분 주기 | 하루30회 | 30일900분 |
| 이번 주기를10/13~10/26 양일 포함14일 운영 | 420회 | 420분 |

이는 모든 예정 Job이 실행되고 각 Job이1분 이내 끝나는 계산 예시다. checkout·API·artifact 처리가1분을 넘으면 Job별 올림으로 더 소비하며 수동 실행도 별도 합산한다. 900분/420분은 예산 상한이나 현재 잔여량이 아니다. 비활성 schedule Run은 만들어져도 notify Job은 skip되므로 그 Job의 hosted 실행시간은 소비하지 않는다.

활성화 전에 조직 관리자 또는 Billing 조회 권한자가 **이번 달 실제 사용량·잔여량, 다른 저장소 CI에 남길 분량, 추가 사용의 지출 제한/중단 조건**을 확인하고 조회 시각·채택 결과를 기록한다. 현재 실제 사용량은 `NOT_VERIFIED`다. 확인할 수 없거나 필요한 여유가 없으면 enabled를 켜지 않고 기존 수동 관측을 사용한다. 과금 허용·관리 PAT 생성·조직 예산 변경은 이 PR에 포함되지 않는다.

### 필수 설정 누락

수동 dry-read와 notify 모두 관측 도구 호출 전에 threshold가 숫자1~1440인지 검사한다(ASCII 숫자1~4자리, 앞의0은 허용). 누락·빈 값·범위 밖이면 변수 이름과 허용 범위만 포함한 명확한 Actions 오류를 남기고 rc2로 종료한다. 설정 원문은 출력하지 않고 GitHub 관측/댓글 발송 도구를 호출하지 않는다. 이 경우 관측 JSON이 없는 것은 정상 조회나 `NO_ALERT`가 아니라 **설정 오류로 관측을 시작하지 못한 것**이다. 변수를 바로잡기 전 반복 실패를 막으려면 enabled를 false로 유지한다.

## 1회 확인 및 실제 인수 순서

1. 리뷰된 main SHA, 위 변수 후보의 채택, 담당·대체 담당/연락 수단과 야간 작업 대응, 저장소 Actions 활성 상태, 위 Billing 잔여량·사용 예산 확인을 기록한다. 기본 `notify=false`로 수동 실행해 artifact와 실행 로그를 읽는다. 기존 계정에서 로컬 도구를 실행할 경우에도 `--notify` 없이 다음 한 번의 읽기만 사용한다.

   ```text
   python -I -B tools/ansible-ci-queue-alert.py --threshold-minutes <채택한_정수> --output <새_JSON_경로>
   ```

2. 새로운 업무상 필요한 Ansible PR의 exact HEAD/Run/Attempt/Job을 사용한다. 완료된 PR75/76/77을 알림·교육 증적만 얻으려고 rerun하지 않는다. PR HEAD와 GitHub가 관측한 Run HEAD는 따로 기록하고, 실제 checkout·공급 판정은 기존 운영자 카드로 확인한다.
3. 채택한 설정으로 enabled를 켜고 다음 실제 장기 대기 관측에서 #61 댓글과 감시 Run/artifact를 연결한다. GitHub mention 게시 성공은 **사람의 수신 확인이 아니다**. 수신 시각·담당자 회신을 별도로 남긴다.
4. 담당자의 queue-watch 판단→중복·창·인증 preflight→기존 승인된 v1.3 공급→regression/upload→정리를 연결한다. 제2운영자의 실제 수행이 있어야 O02 실적이다. 이름만 추가하거나 기존 운영자의 반복 실행으로 인수하지 않는다.
5. 조건 해소 댓글을 확인하되 그것을 CI PASS·token 폐기·Runner 정리의 증거로 쓰지 않는다. 원본 JSON/SHA와 회차 증적을 기존 보관 경로로 편입하고 담당/보존 기준을 연결한다.

발송은 명시적으로 enabled된 main workflow의 첫 Attempt에서만 한다. main이 이미 바뀌면 그 실행은 발송을 중단한다. 수동 retry는 발송하지 않는다. 다음 정상 schedule이 새 상태를 다시 관측한다. source 전체 변경 없이 오류 해결을 위해 라벨/권한/대상을 넓히지 않는다.

## 상태 변화·실패·중지

- 같은 상태·Job/Attempt/SHA·threshold·수신자에는 반복 댓글을 남기지 않는다. 직전 #61의 `github-actions[bot]` 관리 marker를 읽고 비교한다. 시작 시 대상이 없으면 조용히 종료한다. 이전 경고가 해소되면 한 번 알린다. 사람의 marker 댓글은 dedup 근거로 쓰지 않는다.
- 일일 댓글 상한은 없다. `READ_ERROR`와 `ATTENTION` 또는 오류 코드가 번갈아 바뀌면 조회마다 mention이 생길 수 있다. 이번 schedule은 하루30회·각 실행 POST 최대1회지만 수동 실행·지연 실행까지 포함한 달력 날짜별 알림 상한을 보장하지 않는다. 기존 경고 전이를 임의로 숨기는 새 억제 로직은 이번 변경에 추가하지 않았다. 반복 오류 때 담당자가 실패 원본을 확인하고 enabled를 false로 중지한 뒤 기존 연락 경로로 인수한다. 일일 상한은 PR81 보안 리뷰의 비차단 권고로 남긴다.
- 읽기는 원자적 스냅샷이 아니다. Run이 목록 사이 이동한 경우 같은 identity는 중복 제거하며, Attempt/SHA 등이 바뀌면 해당 관측을 오류로 남긴다. 관측 직후 Job이 시작/완료할 수 있으므로 공급 전 fresh 확인이 필수다.
- 활성 Run20개, 총 Job100개, 기존 댓글1000개, HTTP 응답2MiB, API 전체120초/요청10초 상한을 넘기거나 목록이 불완전하면 정상 해소로 쓰지 않는다. 새 페이지를 임의로 생략해 `NO_ALERT`로 만들지 않는다.
- #61이 닫히거나 댓글이1000건을 넘으면 `OWNER_ISSUE_UNAVAILABLE`로 발송이 중단되고 감시 Run은 실패한다. enabled를 그대로 두면 다음 schedule도 같은 이유로 실패할 수 있다. 담당자는 enabled를 false로 중지하고 기존 연락 경로로 인수한다. 도구가 이슈를 다시 열거나 기존 증적 댓글을 삭제하여 우회하지 않는다.
- API 읽기 실패는 `READ_ERROR`이며 가능한 경우 그 상태 변화만 통지한다. GitHub 전체 장애·권한 오류로 발송도 안 되면 감시 Run은 실패한다. 원본 artifact/로그를 확인하고 지정 운영자가 기존 연락 경로로 전달한다. GitHub/Actions가 통째로 멈춘 상황을 이 도구 자체로 외부 통보하지는 못한다.
- 댓글 POST timeout/응답 불명확은 `UNCONFIRMED`·rc1이다. 그 실행은 POST를 자동 재시도하지 않는다. #61의 실제 marker와 감시 결과를 먼저 읽는다. 이후 schedule도 실제 기존 댓글을 다시 확인한다. 저장·GitHub 서비스 지연이 있으므로 exactly-once 보장을 주장하지 않는다.
- token/개인키·원문 HTTP 오류는 결과에 쓰지 않는다. 새 출력 파일과 SHA sidecar만 만들며 기존 파일을 덮어쓰지 않는다. artifact 보존14일은 전달 유예이며 장기 증적 보관 인수를 대신하지 않는다.
- 중지는 enabled를 false로 바꾸고 진행 중인 감시 Run의 종료·이미 게시한 댓글을 확인한다. 이미 시작한 Run은 시작 시 읽은 variables로 끝날 수 있다. 엄격한 즉시 중지가 필요하면 해당 감시 Run만 취소하고 게시 여부를 읽는다. 도구는 Runner·Job·정책을 바꾸지 않으므로 서버 원복은 없다. 기존 댓글·증적은 보존한다.

## 검증 범위

로컬 MOCK은 대기 경계·timestamp 이상·다른 labels·목록 상한/오류·active Run 안의 대기·Attempt 변경·변경 상태 발송·중복 억제·정상 해소·잘못된 context/권한·POST 불확실·출력 보존을 다룬다. 기존 queue-watch 검증도 함께 수행한다. 실제 GitHub API의 읽기 결과와 합성 POST 시험을 구분한다.

2026-10-13 04:48 KST 로컬 기본 실행은 활성 Run0, `NO_ALERT`, `DRY_RUN_NO_COMMENT`, rc0이었다. 실제 알림 발송·담당 수신·주기 실행·Runner 공급·O02 인수는 아직 미실행이다. 10분 값은 그 읽기의 진단 입력이며 운영값 채택 증거가 아니다. Windows MOCK/읽기 성공을 Linux CI 또는 운영화 완료로 확대하지 않는다.
