# Actions 정상·고의 결함 인수 기준과 현재 상태

2026-09-23 갱신. **일반 PR CI 활성화와 Issue #5 최종 AC는 미완료**다.

## 최신 확인과 남은 작업

- 코드 [PR17](https://github.com/321Team/infra-ansible/pull/17)·[PR19](https://github.com/321Team/infra-ansible/pull/19)는 9/18 독립 승인·병합 완료다.
- 정상 PR20, count 고의결함 PR21, export-fix 정상 [PR22](https://github.com/321Team/infra-ansible/pull/22)의 제한된 격리 Actions·Runtime·정리 증적은 각 source/Run/Attempt에 귀속한다. 수정 source의 시험 전체를 NOT_RUN으로 되돌리지 않는다.
- [증적 PR13](https://github.com/321Team/fds-project-evidence/pull/13)은 재환의 HEAD `b90c1d39decb6bfc5adeeebd8591133304a7a9c5` APPROVED를 유지하여 9/23 merge `e51b15ed587af165282a43ef57ca5b677495ea7c`로 편입했다.
- 9/23 GitHub 관리 화면 직접 확인: [Ansible Runners](https://github.com/321Team/infra-ansible/settings/actions/runners) 0개, [Repository Variables](https://github.com/321Team/infra-ansible/settings/variables/actions) 0개. `ANSIBLE_CI_ENABLED`·`ANSIBLE_CI_RUNNER_LABELS`가 없다. 당시 main `65b279c`에는 활성 Workflow가 없으며 이 문서 변경도 Workflow를 추가하지 않는다.
- 기존 일반 활성화 초안 `claude/bold-einstein-44hhmr`의 `2c617f3`은 Workflow 한 파일 추가이며 템플릿과 byte-for-byte 동일하다. 9/23에 당시 main으로 patch 적용·역적용 가능성을 로컬에서 확인했다. 새로 작성할 필요는 없으나 실제 착수 시 최신 base/HEAD를 대조한다.
- 남은 순서: **Ansible용 Runner 공급·사용 범위 확정 → Variables/정확한 라벨 확인 → 일반 Workflow 변경 검토와 정상/고의결함 인수 → Lead 최종 AC 판단**. CI Workflow는 Pre-check 예외 대상이 아니다. 증적 저장소 편입은 독립 리뷰를 유지하며, 동일 승인 코드의 Runtime 결과 수용·AC 인수마다 별도 Support 승인을 반복 요구하지 않는다.
- 과거 임시 Runner 격리 시험 완료와 앞으로의 일반 CI Runner 공급 미확인은 구분한다. PR20/21/22는 TEST ONLY / DO NOT MERGE다. 원 시험을 처음부터 반복하거나 엔진 운영 전환을 완료로 올리지 않는다.

아래 수치·source는 작성 당시 시험 이력이다. 기존 인수 기준과 원본을 보존하며, 이후 완료 사실은 위 최신 확인을 따른다. 사전 검토: [ACCEPTANCE_DEEP_REVIEW.md](ACCEPTANCE_DEEP_REVIEW.md).

## 인수한 실제 시험과 변경 후 검증

| 항목 | 정상 시험 | count 고의결함 시험 |
|---|---|---|
| source | `2750634766862d7fe19479acacc4259ee8315061` | `c50a6b3316fabba08d5211933e3733f8026e2d95` |
| PR / Run / Attempt | #20 / 35139314896 / 2 | #21 / 35173018935 / 1 |
| Job / Check ID | 104963520513 | 105048547807 |
| 실제 결과 | CI_RESULT PASS, Job/Check success | CI_RESULT FAIL, Job/Check failure; 기대 count 결함 탐지 PASS |
| syntax / unit | 32/32 rc0 / 57 OK | 32/32 rc0 / 57 OK |
| 후속 fixture | guard14/14, contract58/58, DNS 양 엔진 rc0 | 엔진별 baseline PASS9/FAIL5/ERROR0; contract/DNS NOT_RUN |
| Runner / 정리 | ID5 / 로컬 정리 및 수집 시점 원격 부재 확인 | ID6 / 로컬 정리 및 수집 시점 원격 부재 확인 |
| Artifact ID / 내부 manifest | 10470072587 / 831/831 | 10478742095 / 592/592 |

[고정된 원본 인수 기록](https://github.com/321Team/fds-project-evidence/tree/8223fdff0c3e52e17c13311107624578bb35542d/evidence/infra-ansible-followup/actions-acceptance-20260917)에 source/Run/Attempt/Job/Check, Runtime, 원본 hash를 보존했다.
두 세션은 Runner v1.3·격리18/18·SELinux Enforcing·IPC 및 runner/proxy/workspace 정리를 확인했다.
정상 source는 수정 전 PR17 `9b019ad4213539e9a6edf2409e1d0bd0d4ef46f6`의 68개 파일을 포함한다.
이 성적을 이후 수정된 실행기의 직접 CI 결과로 승계하지 않는다. TEST ONLY PR #20/#21은 병합하지 않는다.

`a9785da...`는 export 실패 시 메모리 결과를 FAIL로 만들고 쓰기 가능한 CI_RESULT를 best-effort로 갱신한다.
manifest 쓰기 장애 회귀시험 1개를 추가했다. 해당 commit의 LOCAL 58/58 결과와 수정안 통합 LOCAL/MOCK 157/157을 구분한다.
지속 저장 장애에서 파일 재기록이 불가능한 한계는 알려진 제한이다. 별도로 합의되지 않은 새 병합 차단 AC로 추가하지 않는다.
실행기 rc·Job/Check·완전한 manifest·source/attempt 대조는 계속 필수다.
새 코드의 구체적 준비 범위는 [artifact export 수정 후 격리 CI 계획](ARTIFACT_EXPORT_CI_PLAN.md)을 따른다.

## 일반 활성화용 비활성 패치

아래 patch를 처음 작성한 기준 source는 `5ed6d3947a15d59cf6c360c0419f961b8143c707`이다.
이 기준은 과거 작성 이력이며 현재 실행 대상 SHA가 아니다. 일반 활성화 patch는 계속 비활성이다.
이미 수행한 PR #20/#21은 별도의 제한된 격리 Workflow를 사용했다.

| 파일 | 승인 후 변경 | 현재 게시 상태 |
|---|---|---|
| [activate-workflow.patch](patches/activate-workflow.patch) | `.github/workflows/ansible-regression.yml` 신규 추가 | docs/ci 아래 비활성 patch |
| [intentional-count-defect.patch](patches/intentional-count-defect.patch) | 첫 SSH guard의 `!= 1` 한 곳만 `!= 2`로 변경 | docs/ci 아래 비활성 patch |

활성화 패치는 기존 템플릿을 바이트 그대로 복사한다. 첫 줄의 Inactive 주석도 원문 보존을 위해 포함된다.
실제 활성 여부는 `.github/workflows/` 경로와 GitHub 설정으로 판단한다. 주석이 실행을 막지는 않는다.
고의 결함 패치는 OR, 두 번째 guard, 회귀 기대값과 시험기를 수정하지 않는다.
기존 `or → and` 안내는 matrix 생성기에서 조기 중단되므로 실제 인수 사례에서 제외한다.

패치 자체는 HEAD를 검증하지 않는다. 담당자는 별도 새 checkout의 remote/전체 HEAD/clean 상태와
아래 대상 blob을 먼저 대조한다. `git apply --check`만으로 승인된 버전임을 증명하지 않는다.

| 기준 파일 | Git blob SHA |
|---|---|
| docs/ci/ansible-regression.workflow.yml | `a6741487ae1a3b96afef6c7ae05e4c63942b42b8` |
| playbooks/harden_svc_ansible_key.yml | `c393dcefdfbd0252e1c2c43e26fce3138dae2f62` |

기준 이후 바뀐 소스는 diff를 검토하고 새 SHA로 재고정한다. 임의 `--3way`/강제 적용은 하지 않는다.
Workflow 대상이 이미 있거나 patch 충돌이 있으면 중단하여 검토한다. 사용자 홈에 직접 patch를 적용하지 않는다.

## 일반 활성화 검토 및 새 시험 수행 순서

이 절차의 일반 Workflow 활성화 통제와 테스트 전용 격리 실행을 구분한다.
기존 [격리 시험 착수 기준](https://github.com/321Team/infra-ansible/blob/2750634766862d7fe19479acacc4259ee8315061/docs/ci/ISOLATED_ACTIONS_ENTRY.md)은
명시적으로 요청된 제한된 격리 시험에 사전 딥리뷰·실행 시 격리 검사를 적용했다.
모든 격리 시험 준비 전에 독립 승인을 일괄 요구하는 것으로 확대하지 않는다.
일반 자동 실행 활성화·최종 인수·병합의 독립 검토 통제는 유지한다.

1. PR17/19와 증적 PR13의 기존 승인·병합을 재사용하고, 일반 활성화 후보의 최신 HEAD와 이후 diff를 고정한다. 자체 준비를 새 코드의 독립 승인으로 간주하지 않는다.
2. 정상 후보용 새 브랜치에서 활성화 patch만 적용한다. diff가 Workflow 추가 한 파일인지 확인하고
   별도 활성화 변경으로 검토한다. main 병합 없이 동일 저장소의 main 대상 PR로 인수를 준비할 수 있다.
3. 승인된 고정 라벨과 설정을 확인한다. ANSIBLE_CI_RUNNER_LABELS는
   `["self-hosted","Linux","X64","fds-ci","ansible-isolated"]`, enabled는 승인된 시점에 true로 설정한다.
   9/23 조회에서는 해당 변수가 미등록이었다. 이번 문서 갱신은 설정을 변경하지 않았으며 활성화 시 다시 확인한다. 비활성/불일치 라벨의 skipped는 정상 인수 PASS가 아니다.
4. 정상 후보의 전체 HEAD와 Workflow blob을 기록하고 1-job ephemeral Runner에서 실제 PR Job을 실행한다.
   serve 완료만으로 Job 성공을 판정하지 말고 아래 API·artifact 증적을 대조한다.
5. 정상 후보에서 파생한 별도 임시 브랜치에 결함 patch 한 개만 적용하고, 정상 대비 한 줄 diff와 새 전체 HEAD를 기록한다.
   검토된 결함 PR을 실제로 실행한다. 두 실행에 같은 Workflow blob을 사용한다.
6. 정상/결함 세션 각각 종료·정리·그때의 Runner ID 또는 정확한 이름의 API 부재를 확인한다.
   기존 ID3/ID5/ID6 정리 증적을 새 세션에 재사용하지 않는다. 결함 PR은 병합하지 않고 최종 인수·검토 후 종결을 별도로 판단한다.
7. 일반 Workflow 코드와 증적 저장소 PR의 독립 검토를 확인하고, Lead가 실제 결과를 근거로 Issue #5 AC와 수동 병합 여부를 판단한다. 동일 승인 코드의 결과 수용에 별도 반복 승인을 추가하지 않는다. 자동 병합은 없다.

수동 workflow_dispatch를 쓸 경우 Workflow가 기본 브랜치에 있어야 하는 조건을 별도로 확인한다.
PR의 기본 merge SHA와 exact checkout source SHA를 섞지 않기 위해 첫 인수는 동일 저장소 PR 경로를 기준으로 한다.

## 실행별로 수집할 값

| 증거 | 필수 기록·대조 |
|---|---|
| 소스/패치 | 정상/결함 전체 commit, parent, 정상 대비 한 줄 diff, reviewed source와의 차이 |
| Workflow | 실제 workflow 경로·GITHUB_WORKFLOW_SHA·그 commit의 Workflow blob, 검토 템플릿과 동일 내용 |
| Run | repository, Run ID, run_attempt, event, head_sha, head_repository, PR 연결, status/conclusion, URL |
| Job | 해당 attempt의 모든 페이지, regression Job ID, runner_id/name/labels, status/conclusion, 각 step 결과 |
| Check | Job의 check_run_url로 얻은 ID·head_sha·suite·conclusion; Run/PR/event와 연결 근거 |
| Artifact | exact name `ansible-ci-<run_id>-<attempt>-<source_sha>`, artifact ID·workflow_run.id·expired·digest·원본 ZIP SHA256 |
| 내부 결과 | CI_RESULT source_commit/github의 Run ID·attempt·workflow/event SHA·Runner 이름; 원본 로그와 rc |
| 무결성 | 내부 SHA256SUMS의 경로/파일 집합과 모든 bytes 일치; 새 ZIP을 새 경로에서 안전하게 확인 |
| 종료 | 세션 결과, container/proxy/workspace 정리, 종료 이후 Runner ID OR 정확한 이름 API 부재 |

`pull_request`의 GITHUB_SHA는 merge SHA일 수 있다. CI_SOURCE_SHA는 PR head SHA를 checkout한다.
따라서 source/workflow/event/Check SHA를 한 값으로 강제하지 않는다. 차이가 있으면 각 역할과 연결 근거를 기록하고
설명되지 않는 SHA/다른 PR/다른 attempt/오래된 artifact는 인수하지 않는다.
rerun은 run_attempt가 증가하므로 최신 Jobs 조회만으로 과거 attempt를 증명하지 않는다.
API 요청과 artifact 다운로드는 기존 관리자 인증으로 수집하되 인증 토큰·hosts.yml·토큰 packet은 증적에 포함하지 않는다.

읽기 API 수집 경로(값 확정 후 사용):

- `GET /repos/321Team/infra-ansible/actions/runs/{run_id}/attempts/{attempt_number}`
- `GET /repos/321Team/infra-ansible/actions/runs/{run_id}/attempts/{attempt_number}/jobs?per_page=100` — Link 페이지 끝까지
- 각 Job의 `check_run_url` — 대상 저장소/ID 확인 후 조회
- `GET /repos/321Team/infra-ansible/actions/runs/{run_id}/artifacts?per_page=100` — Link 페이지 끝까지
- 이름·Run ID·attempt·source를 대조한 artifact ID의 ZIP 및 API digest 보존

artifact 목록은 Run 범위이므로 attempt는 이름과 CI_RESULT 내부 값으로 추가 확인한다.
Workflow는 14일 보존을 요청하지만 실제 적용 기간은 Artifact API의 expires_at으로 확인한다.
기존 정상 artifact에는 7일이 적용됐으며 원본은 이미 별도로 확보했다. 새 artifact도 실제 만료 전에 원본을 확보한다.
운영자 수집 파일은 기존 로그인 홈에 새 전용 디렉터리를 만들어 저장한다.
홈·토큰 경로에 chmod를 호출하거나 임의 절대경로를 재귀 삭제하는 절차는 없다.
서버에서 새 토큰을 다룰 때는 기존 입력 보호 도구를 먼저 사용한다.

## 성공/실패 판정 기준

| 사례 | 기대 결과 | 성공으로 인정하지 않는 결과 |
|---|---|---|
| 정상 | Job/Check success, CI_RESULT PASS/실행기0, 구문2엔진×16=32 완전 집합, fixtures PASS_FRESH_OFFLINE_FIXTURES 및 complete matrix, artifact 업로드 성공 | skipped, 이전 SHA 자료, 일부 엔진만 PASS, 설치/권한 오류, artifact 없음 |
| count 결함 | Job/Check failure, CI_RESULT FAIL/실행기1, 구문 정상·unit 성공 이후 guards baseline에서 아래5건 불일치, artifact 업로드 성공 | OR 전제조건 오류, ERROR/환경 오류만 존재, timeout/cancel, 업로드 실패만으로 Job failure |

결함 baseline은 각 엔진에서 첫 guard의 `one_plain`, `one_restricted`, `two_plain`, `two_restricted`, `mixed`가 FAIL이고
나머지9건은 PASS, ERROR0이어야 한다. 실제 guards/MATRIX 및 각 엔진 baseline report에서 대조한다.
CLI의 nonzero와 harness rc1은 별개 값이므로 모두 기록한다. Ansible CLI는 보통 rc2로 실패한다.
matrix는 고의 결함 source에서 baseline 불일치 외에 내부 mutation 기대도 달라질 수 있다.
결함 원인은 baseline5건을 근거로 판정하며 matrix 총 실패 행 수를 고정하지 않는다.
kit는 guards 실패 후 중단하므로 결함 실행의 뒤쪽 callback/DNS 미실행은 실패 위치와 함께 기록한다.
정상 실행에서는 두 엔진 전체가 완료되어야 한다.

## 로컬 검증과 실제 CI의 경계

기존 정상·결함 시험은 2.16.19/2.21.3 실제 Actions와 세션별 정리까지 인수했다.
이후 수정안의 저장 장애·변조·대조 모형은 LOCAL/MOCK이다. 타임아웃 반복은 실제 로컬 Python 자식 대상이다.
이 결과는 수정 코드의 실제 GitHub scheduler·checkout·양 엔진·artifact 업로드 통합, 새 Runner 정리 또는 독립 승인을 대신하지 않는다.
문서만 추가로 바뀐 HEAD는 runtime/test blob 동일성으로 기존 로컬 성적과 연결하되, 그 HEAD에서 새 시험을 수행했다고 표기하지 않는다.

## 공식 계약

- [PR event의 merge SHA와 head SHA](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
- [Run attempt의 Jobs](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt)
- [Workflow run attempt](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run-attempt)
- [Artifacts API](https://docs.github.com/en/rest/actions/artifacts#list-workflow-run-artifacts)
