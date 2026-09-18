# Ansible CI 회귀 — Issue #5

2026-09-17 기준 기존 시험 전용 source의 정상 Actions PASS와 count 고의결함 탐지를 인수했습니다.
이후 artifact export 진단 수정 `a9785da3485ffd61840a82a3e9bd14ceb4edb50b`는 로컬58/58 PASS이며,
수정 코드를 포함한 새 source의 실제 Actions는 NOT_RUN입니다. 일반 Workflow는 여전히 비활성입니다.
선행 #8은 코드 PR #16 / 증적 PR #12 독립 승인 후 병합됐으며 기반 main은
`651c2558bc55ca8367bed32ad318c497e2f3bf35`입니다. 후속으로 PR #12가 병합된 main
`57e7cc740e7a406387848c52f4aa56b98c516168`을 CI 후보에 통합했습니다. 기존 Linux PASS는 이전 HEAD의 증적이고 이 변경의 새 실행 결과가 아닙니다.

## 현재 Runner 입력

[P1-CICD-01](https://github.com/321Team/fds-project-baseline/issues/16)의 기존 앱 Runner는 `infra-cicd` 소속입니다.
별도 `ansible-verify` 계정의 rootless Podman Runner v1.3에서 정상 ID5와 결함 ID6 세션을 인수했습니다.
두 세션은 IPC·격리18/18·SELinux Enforcing, runner/proxy/workspace 정리와 종료 이후 관리 Receipt의 정확한 ID/name 부재를 확인했습니다.
[원본 인수 기록](https://github.com/321Team/fds-project-evidence/tree/8223fdff0c3e52e17c13311107624578bb35542d/evidence/infra-ansible-followup/actions-acceptance-20260917).
기존 v1.2/ID3는 이전 등록 시험 이력입니다. 기존 앱 Runner를 공유한다고 가정하지 않습니다.

인수된 bundle SHA256은 `e2fbefffa01b8a0f401cd4623b497944d0e41264ad13343d42ff2b272707d5c6`,
image는 `sha256:3f96787b2a8db29294002677a3e733689439952ad9e95db721acf8e16ff601f1`입니다.
Runner 코드 PR19 HEAD `4da96621fd05a4943b76ca32b860a5779ec65e00`는 이번 export 수정으로 바뀌지 않았습니다.
현재 서버 PREPARED/bundle/image는 이번 문서 갱신에서 조회하지 않았으므로 재사용을 확정하지 않습니다.
다음 세션은 기존 launcher의 현재 상태 검사를 통과해야 합니다. 새 prepare를 자동 반복하거나 PREPARED를 수기로 수정하지 않습니다.

활성화 전 담당자가 실제 Runner 이름/labels/group, Ansible 저장소 접근, 작업 계정, Linux x86_64·glibc>=2.28·
CPython3.12·Git·grep·Bash, 작업 디렉터리/종료 후 정리 소유자를 기록합니다. 운영 SSH 키·배포 Token·sudo·
Podman 소켓 등 다른 작업의 권한이 PR 코드에 노출되는 영속 Runner를 사용하지 않습니다.
새 venv나 환경 변수 제거만으로 임의 PR 코드가 격리된다고 보지 않습니다. 승인된 일회성 Runner 또는 동등한 격리 경계를 확인합니다.

## 실행기

`tools/run-ansible-ci.py`는 전체 SHA와 clean checkout을 확인하고 #8의 collect/build/prepare/run을 재사용합니다.
wheel을 수집할 때만 고정된 PyPI 원본에 접근하며, 설치는 로컬 wheel·hash lock·no-index로 새 venv에서 수행합니다.
`--wheels`로 이미 검증한 wheel 디렉터리를 지정하면 다운로드 단계도 생략합니다. 시스템 Ansible/Python을 교체하지 않습니다.

```bash
python3.12 -I -B tools/run-ansible-ci.py --commit "$(git rev-parse HEAD)" --plan
python3.12 -I -B tools/run-ansible-ci.py --commit "$(git rev-parse HEAD)" --output /NEW/OUTSIDE/CHECKOUT/result --wheels /APPROVED/WHEELS
```

plan은 실행이 아닙니다. 실행은 전체 playbooks/*.yml 및 SSH 읽기/DNS 시험 Playbook을 양쪽 엔진에서
syntax-check한 후 기존 단위·guard 결함·callback·DNS localhost fixture를 수행합니다. 현재 구문 대상은 운영 playbook 14개 + 시험 playbook 2개 = 16개 × 2엔진 = 32개이며
파일 목록에서 산출합니다. syntax-check 외 운영 playbook 실행 옵션은 없습니다.

2.16.19/2.21.3은 한 Job 안의 두 엔진 matrix로 실행해 baseline을 직접 비교합니다. 엔진 목록은 기존
verification_contract의 ENGINES, guard 입력/조건은 원본 fixture, matrix 기대 집합은 regression_expectations에서 연결합니다.
완료 행 수만 같아도 누락+중복 조합은 실패합니다. 새 expected case를 정의하고 실행하지 않으면 실패합니다.

예상 실패는 하위 판정기가 확인합니다. 뜻밖의 syntax 오류·fixture FAIL·잘못된 source SHA·누락·중복은
CI_RESULT status FAIL 및 실행기 exit1로 전달합니다. continue-on-error나 실패를 성공으로 바꾸는 처리는 없습니다.
새 결과 경로만 허용하며 과거 실패 자료를 삭제하거나 덮어쓰지 않습니다.

artifact export 예외도 메모리 결과 FAIL·실행기 exit1로 전달하며, 쓰기 가능한 CI_RESULT에
artifact_export의 오류 종류/errno를 best-effort로 기록합니다. 지속 쓰기 장애에서는 기존 결과 파일이 남을 수 있습니다.
이는 원자적 저장/전원 손실 내구성 보장이 아닙니다. 결과 파일의 PASS 하나로 인수하지 않고
rc·Job/Check·완전한 manifest·정확한 source/attempt를 함께 확인합니다.

## Workflow 활성화와 최소권한

`docs/ci/ansible-regression.workflow.yml`은 **.github/workflows 바깥의 비활성 초안**입니다.
Runner 입력·경계와 독립 리뷰를 확인한 별도 변경에서 .github/workflows/ansible-regression.yml로 편입합니다.
기존 PR #20/#21의 제한된 격리 Workflow 실행과 이 일반 활성화 절차는 별개입니다.
명시적으로 요청된 시험 전용 격리 준비에 독립 승인을 일괄 선행조건으로 추가하지 않습니다.
`runs-on`은 `[self-hosted, Linux, X64, fds-ci, ansible-isolated]`로 고정하며 변수로 다른 Runner를 선택하지 않습니다.
설정 변수 ANSIBLE_CI_RUNNER_LABELS는 이 선택에 대한 확인값입니다. 승인 후 공백 없이 정확한 순서의
`["self-hosted","Linux","X64","fds-ci","ansible-isolated"]`를 사용하고 ANSIBLE_CI_ENABLED=true를 적용합니다.
문자열 비교는 GitHub 규칙상 대소문자를 무시하지만 공백·순서를 자동 보정하지 않습니다.
빈 값·부분 라벨·다른 Runner·잘못된 JSON은 Job 조건에서 skip되며 fromJSON으로 스케줄링 대상을 만들지 않습니다.
허용 이벤트도 동일 저장소 pull_request와 workflow_dispatch로 명시합니다.
코드 수정 전 검토는 `docs/ci/ACTIVATION_DEEP_REVIEW.md`에 있습니다.
활성화 검증에는 미설정/정상/잘못된/넓은 labels, 비활성, fork 및 허용되지 않은 이벤트를 포함합니다.
이 조건의 로컬 점검은 GitHub의 실제 skip/실행 증적을 대신하지 않으며 skipped는 #5의 PASS가 아닙니다.
선택 값 ANSIBLE_CI_WHEEL_DIR은 승인된 wheel 보관 경로입니다. 본 작업은 저장소 변수나 Runner 등록을 변경하지 않습니다.

trigger는 동일 저장소의 main 대상 pull_request 및 workflow_dispatch입니다. pull_request_target·자동 병합·배포 단계는 없습니다.
contents:read만 부여하고 checkout은 PR HEAD 전체 SHA를 지정하며 persist-credentials:false입니다. 외부 Action은 검토한 commit SHA로 고정합니다.
Fork PR은 실행하지 않으며 이 필터는 Runner 격리나 사람의 코드 리뷰를 대신하지 않습니다. manual dispatch는 Workflow가
기본 브랜치에 존재해야 하므로 초안 PR에서 아직 실행된 것으로 표시하지 않습니다.

참고: [GitHub 이벤트와 HEAD](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[최소권한·자가 호스팅 Runner 보안](https://docs.github.com/en/actions/reference/security/secure-use),
[Workflow 구문](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## 정상·고의 결함 Actions 증명

활성화 후 정상 HEAD에서 actual Run ID/Attempt·workflow SHA·source SHA·Runner 이름·Check SHA·artifact 해시를 기록합니다.
정상 시험은 PASS/exit0이어야 합니다. 별도 임시 검증 브랜치에서 첫 SSH guard의 count 비교 `!= 1`만 `!= 2`로 바꾼
**실제 고의 결함 commit**을 만들고 해당 PR Run이 FAIL/exit1이 되는 것을 확인합니다. OR와 두 번째 guard 및 시험 기대값은 유지합니다.
`or → and`는 기존 matrix 생성기의 OR 전제조건에서 먼저 중단되므로 이 실제 인수 사례로 사용하지 않습니다.
결함 원인은 첫 guard의 one_plain/one_restricted/two_plain/two_restricted/mixed 5건 불일치로 확인해야 합니다.
환경 오류·설치 실패·취소만으로 기대한 결함 탐지 성공을 인정하지 않습니다. 다른 경로의 문법 오류도 차단됩니다.
결함 commit은 main에 병합하지 않으며 최종 인수·검토 후 해당 PR 종결을 별도로 판단하고 원문 artifact는 보존합니다.

내부 mutation 시험이 성공했다는 것만으로 실제 고의 결함 Actions Run을 대체하지 않습니다.
정상/결함 SHA·Run URL·Attempt·Check 결과·artifact SHA를 #5에 연결하고 당시 지정된 독립 리뷰어에게 검토를 요청합니다.
현재 PR17/PR19/증적 PR13에는 `hayeounglee`, `supreme33-kr` 검토 요청이 있습니다.
요청 상태나 과거 COMMENTED를 최신 HEAD의 독립 승인으로 간주하지 않습니다.
정상 source `2750634766862d7fe19479acacc4259ee8315061`의 Run `35139314896 / Attempt2`는 success,
결함 source `c50a6b3316fabba08d5211933e3733f8026e2d95`의 Run `35173018935 / Attempt1`은 기대한 failure였습니다.
이는 수정 전 코드의 실제 성적입니다. 수정 코드의 실제 CI·최종 독립 리뷰는 남아 있으며 #5 AC는 최종 체크하지 않습니다.

검토 가능한 비활성 patch와 실행별 증적 대조 기준은 [Actions 인수 준비](../ci/ACTIONS_ACCEPTANCE.md)를 따릅니다.
patch 파일을 게시한 것만으로 Workflow가 활성화되지 않습니다.
수정 코드의 다음 정상 격리 CI와 count 재시험 범위 판단은 [후속 검증 계획](../ci/ARTIFACT_EXPORT_CI_PLAN.md)을 따릅니다.
Start 키트 버전과 Runner bundle 버전은 서로 다른 값입니다. 기존 Start v1.1의 PR20 고정 admin 명령을 새 시험에 재사용하지 않습니다.
새 Run/Attempt/Job이 확정되기 전 발급·serve 명령을 실행하지 않습니다.

## 증적과 작업 디렉터리 수명

각 실행은 RUNNER_TEMP의 고유 run/attempt 경로에서 runtime·venv·결과를 만들고 source checkout에는 쓰지 않습니다.
artifact/에는 CI_RESULT·원본 설치/구문/fixture 로그·원본 관찰·manifest와 새 SHA256SUMS를 저장합니다.
venv·wheel·source pack·Ansible module cache는 업로드하지 않으며 생략 cache의 경로/해시는 ARTIFACT_SCOPE에 기록합니다.
원본 fixture manifest는 생략 cache도 참조할 수 있으므로 artifact 전체 검증은 새 SHA256SUMS를 기준으로 합니다.
artifact 보존기간은14일을 요청하지만 실제 expires_at을 확인합니다. 기존 정상 artifact에는7일이 적용됐습니다.
장기 보관은 검토 후 증적 저장소/승인 보관 위치에 연결하며 기존 인수 원본은 이미 확보했습니다.

Job 완료(취소 포함) 후 일회성 Runner 폐기 또는 승인된 run-root 정리는 Runner 담당자가 보장합니다.
Runner 서비스/기존 checkout/다른 run/SSH 키/known_hosts를 재귀 삭제하는 명령은 이 실행기에 넣지 않습니다.
기존 ID5/ID6 실제 Actions 세션의 정리·원본 보관은 위 기록으로 확인했습니다. 새 세션의 정리는 해당 ID/name으로 별도 인수합니다.
서버 수집 증적은 기존 로그인 홈에 생성하는 Runner launcher 절차를 사용합니다. 기존 P1-CICD 앱 Delivery AC·일정·승인 범위는 유지합니다.
