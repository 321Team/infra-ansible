# Ansible CI 회귀 — Issue #5

현재 구현은 실행기·비활성 Workflow 초안입니다. 실제 Actions PASS를 확보한 상태가 아닙니다.
선행 #8은 코드 PR #16 / 증적 PR #12 독립 승인 후 병합됐으며 기반 main은
`651c2558bc55ca8367bed32ad318c497e2f3bf35`입니다. 후속으로 PR #12가 병합된 main
`57e7cc740e7a406387848c52f4aa56b98c516168`을 CI 후보에 통합했습니다. 기존 Linux PASS는 이전 HEAD의 증적이고 이 변경의 새 실행 결과가 아닙니다.

## 현재 Runner 입력

[P1-CICD-01](https://github.com/321Team/fds-project-baseline/issues/16)의 기존 앱 Runner는 `infra-cicd` 소속입니다.
별도 `ansible-verify` 계정의 rootless Podman Runner v1.2는 prepare·격리14개·등록/제거·workspace 정리와
관리 API에서 이번 ID3의 부재를 확인했습니다. [실제 등록 증적](https://github.com/321Team/fds-project-evidence/tree/d71a5a5992f994265f723c9e388b4d443287ce39/evidence/infra-ansible-followup/cicd-runner01-registration-20260916T172532Z),
[ID3 부재 증적](https://github.com/321Team/fds-project-evidence/tree/89cdf9c3911afb8c734136dfff32758a8f78d6fc/evidence/infra-ansible-followup/ansible01-runner-absence-20260916T175215Z).
이는 등록 검증 범위이며 실제 Actions Job 인수는 아직 미완료입니다. 기존 앱 Runner를 공유한다고 가정하지 않습니다.

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

## Workflow 활성화와 최소권한

`docs/ci/ansible-regression.workflow.yml`은 **.github/workflows 바깥의 비활성 초안**입니다.
Runner 입력·경계와 독립 리뷰를 확인한 별도 변경에서 .github/workflows/ansible-regression.yml로 편입합니다.
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
정상 시험은 PASS/exit0이어야 합니다. 별도 임시 검증 브랜치에서 첫 SSH guard의 failed_when `or`를 `and`로 바꾼
**실제 고의 결함 commit**을 만들고 해당 PR Run이 FAIL/exit1이 되는 것을 확인합니다. 다른 경로의 문법 오류도 차단됩니다.
결함 commit은 main에 병합하지 않으며 결과 확인 후 해당 PR을 닫고 원문 artifact는 보존합니다.

내부 mutation 시험이 성공했다는 것만으로 실제 고의 결함 Actions Run을 대체하지 않습니다.
정상/결함 SHA·Run URL·Attempt·Check 결과·artifact SHA를 #5에 연결하고 당시 지정된 독립 리뷰어에게 검토를 요청합니다.
이번 선행 검토는 이하영 부재 기록과 CICD 검토 이력을 고려하여 이재환(`supreme33-kr`)에게 요청합니다.
이는 이번 PR의 검토 담당 선택이며 상시 Lead/Support나 최종 병합 권한을 변경하지 않습니다.
현재 이 단계는 NOT RUN이며 #5 AC는 최종 체크하지 않습니다.

## 증적과 작업 디렉터리 수명

각 실행은 RUNNER_TEMP의 고유 run/attempt 경로에서 runtime·venv·결과를 만들고 source checkout에는 쓰지 않습니다.
artifact/에는 CI_RESULT·원본 설치/구문/fixture 로그·원본 관찰·manifest와 새 SHA256SUMS를 저장합니다.
venv·wheel·source pack·Ansible module cache는 업로드하지 않으며 생략 cache의 경로/해시는 ARTIFACT_SCOPE에 기록합니다.
원본 fixture manifest는 생략 cache도 참조할 수 있으므로 artifact 전체 검증은 새 SHA256SUMS를 기준으로 합니다.
artifact 보존기간은14일이며 장기 보관은 검토 후 증적 저장소/승인 보관 위치에 연결합니다.

Job 완료(취소 포함) 후 일회성 Runner 폐기 또는 승인된 run-root 정리는 Runner 담당자가 보장합니다.
Runner 서비스/기존 checkout/다른 run/SSH 키/known_hosts를 재귀 삭제하는 명령은 이 실행기에 넣지 않습니다.
등록 검사 때의 Runner 정리는 위 실제 증적에서 확인했습니다. 실제 Actions 각 세션의 정리·장기 보관 인수는 별도로 확인합니다.
서버 수집 증적은 기존 로그인 홈에 생성하는 Runner launcher 절차를 사용합니다. 기존 P1-CICD 앱 Delivery AC·일정·승인 범위는 유지합니다.
