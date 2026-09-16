# Issue #5 격리 Actions 시험 착수 기준

작성: 2026-09-17 KST / 2026-09-16 UTC. Workflow 코드 작성 전 딥리뷰 및 실행 범위 기록.
사용자 지시: “격리 액션 테스트를 착수. 착수하기에 앞서 필요한 조건은 정본을 근거한 권장안으로 기준을 정하고 착수”.
이번 시험 실행의 사용자 지시와 사람의 독립 코드 승인·최종 인수를 구분한다.

## 정본 근거와 적용 판단

최신 정식 릴리즈는 docs-v3.1.18, 태그/최종화 commit `72599ae49342b0fb8dbd3d8ee60314afb9f907bb`다.
릴리즈의 PR69/70 내용·최종화 승인 및 발행 기록을 근거로 하며, 파일에 남은 당시 CANDIDATE 문구를 현재 미발행으로 해석하지 않는다.

| 근거 | 확인한 요구 | 이번 격리 시험 적용 |
|---|---|---|
| [Baseline §4·§10](https://github.com/321Team/fds-project-baseline/blob/72599ae49342b0fb8dbd3d8ee60314afb9f907bb/baseline/FDS_Project_Implementation_Baseline_v3.1.18.md) | GitHub/외부 Self-hosted Runner, Commit 추적, 실패 시 Deploy 금지 | cicd-runner01의 별도 격리 계정, Ansible syntax/localhost만 실행, 배포 단계 없음 |
| [P1-CICD-01 핵심 요구사항](https://github.com/321Team/fds-project-baseline/blob/72599ae49342b0fb8dbd3d8ee60314afb9f907bb/tickets/v3.1.18/descriptions/P1-CICD-01.md) | 외부 Action 전체SHA, 최소 GITHUB_TOKEN, PR 코드에 운영 SSH·Harbor Push·K8S 자격증명 금지, 작업 간 침해 잔존 평가 | 검토된 action SHA 유지, contents:read, persist-credentials:false, rootless 일회성1-job·network none/제한 proxy |
| 같은 티켓 Schedule Note·Scope | Runner/Workflow·Negative Gate 준비 병행, Ansible #5 별도 완료 추적, 운영 apply·자동 병합 제외 | 정상 시험부터 실행하고 결과 인수 후 결함 시험, 앱 Delivery AC나 Kubernetes/Harbor 완료로 확대하지 않음 |
| 같은 티켓 AC10·repo README 변경관리 | 독립 기술 리뷰·최종 판정 및 검토 후 병합 | Draft·미병합 유지; 실제 결과 포함 독립 리뷰 후 종결/병합 판단 |
| [infra-ansible #5](https://github.com/321Team/infra-ansible/issues/5) | 두 엔진 고정, 정상/결함 실제 Run, 실패 nonzero, 증적·Check SHA | 2.16.19/2.21.3 유지, source/workflow/event/check/attempt·artifact 연결 |

확인한 위 정본 조항은 모든 격리 시험 앞에 독립 승인을 일괄 요구하지 않는다.
기존 자체 작성 인수 문서의 “독립 승인 후에만 활성화” 순서는 정본의 추가 의무가 아니었다.
이번 명시적 사용자 지시에 따라 아래 테스트 전용 범위는 사전 딥리뷰·격리 조건으로 진행한다.
운영 배포/일반 PR 자동 실행/병합 승인 통제를 완화하거나 기존 GitHub 설정·정책을 우회하지 않는다.
새 권한·네트워크 경로·Workload 또는 정본 변경 결정은 만들지 않는다.

## 시험 시작 조건 — 권장 구현 기준

1. **범위/소스**: base PR17 `9b019ad4213539e9a6edf2409e1d0bd0d4ef46f6`의68개 Git blob을 대조한다.
   이 문서와 별도 테스트 Workflow만 추가한 정상 commit을 고정한다. 실제 checkout은 해당 시험 PR의 전체 head SHA다.
   결함은 정상 commit에서 첫 guard count `!= 1 → != 2` 한 줄만 바꾼 별도 commit이다.
2. **실행 선택**: 별도 `.github/workflows/ansible-isolated-acceptance.yml`, pull_request만 허용,
   같은 저장소·main 대상·아래 두 전용 브랜치만 허용한다. main과 PR17의 일반 템플릿은 활성화하지 않는다.
   `test/issue-5-isolated-positive-20260917`, `test/issue-5-isolated-negative-20260917`.
   runs-on은 `[self-hosted, Linux, X64, fds-ci, ansible-isolated]`로 고정한다.
   이 시험은 저장소 전체 ANSIBLE_CI_ENABLED/labels 변수를 바꾸지 않고 명시한 두 테스트 ref만 선택한다.
   일반 PR용 설정 gate를 수정하는 것이 아니라 별도 제한된 시험 Workflow를 추가하는 것이다.
3. **권한/자격증명**: contents:read만, checkout 인증 잔존 없음, secrets/environment/deploy/자동 merge 없음.
   기존 격리 Runner v1.2의 제한 proxy만 사용한다. 직접 사설망·운영 SSH·Podman socket·host network를 제공하지 않는다.
4. **실행 시점 호스트 검사**: 기존 launcher가 비sudo ansible-verify(UID1001/GID1002), password lock, home0700,
   SELinux Enforcing·rootless Podman/cgroupv2/systemd·논리CPU≥4/가용RAM≥6GiB/home free≥8GiB를 매번 재검사한다.
   Runner CPU2/RAM4GiB/PIDs512, proxy CPU0.25/RAM256MiB/PIDs128. 전용 lock으로 한 세션만 허용한다.
   이미지 ID·bundle·PREPARED 영수증이 일치해야 한다. 이전 PASS만으로 현재 검사를 생략하지 않는다.
5. **토큰/입력**: 기존 ansible01 관리 도구로 등록·제거 단기 packet 발급, 사설 전송, 기존 로그인 홈의 일반 파일만 허용.
   검증된 safe_input.py가 형식/소유자/링크/만료를 확인한 후 동일 FD에만0600을 적용한다.
   실패하면 serve를 실행하지 않는다. 토큰/PAT/gh 인증 파일은 증적이나 PR에 넣지 않는다.
6. **순차 실행**: 정상 Run 하나만 먼저 생성한다. 실제 Run/Job/Check와 CI_RESULT 및 artifact를 확인하기 전 결함 Run을 시작하지 않는다.
   GitHub 정책이 실행을 차단하면 그 원문을 기록하고 정책을 자동 변경하지 않는다. queued/skipped는 PASS가 아니다.
7. **종료/증적**: 1-job ephemeral, Job30분·controller1시간 한도와 정확한 CID 정리 유지.
   관리자 수집·세션 증적은 기존 로그인 홈의 새 디렉터리에 기록한다. 홈에 임의 chmod/재귀 삭제를 하지 않는다.
   세션별 Runner ID/name 부재를 종료 후 확인한다. 전체 Runner 삭제/Podman prune은 없다.

위 세부 라벨·CPU/RAM·단기 세션·브랜치 제한은 정본 요구를 구체화한 이번 시험의 권장 구현값이다.
정본에 동일 숫자나 브랜치 이름이 명시됐다고 주장하지 않는다.

## 변경 전 딥리뷰 결과와 검증 계획

- 기존 템플릿의 exact checkout·고정action·실패 전파·artifact 보존·외부 결과 경로를 재사용한다.
- 일반 enable 변수는 이 시험의 원격 상태를 확인할 수 없어 변경하지 않는다. 두 테스트 ref를 소스 코드에 고정하여 범위를 좁힌다.
- 수동 dispatch/main 편입 없이 동일 저장소 Draft PR의 opened 이벤트로 시험 Run을 생성한다.
- matrix 생성기의 OR 전제조건을 유지한 count 결함을 사용한다. 앞선 국소2.16.19의5 FAIL 증적은 설계 근거이며 실제 Actions 증적은 별도다.
- 새 YAML의 실제 내용을 검사하여 허용 ref2개·다른 ref/fork/이벤트 차단, selector/permissions/action/checkout/명령/artifact 계약을 검증한다.
- 이벤트/ref 조건 완화·격리 라벨 누락·write 권한을 주입한 후보는 검증이 실패해야 한다.
- 수정한 Workflow가 Runner 보호를 대신한다고 보지 않는다. 실제 세션 시 재검사와 Run provenance 확인이 필요하다.
- 기존 Runner/이미지/prepare 코드와 token helper는 변경하지 않는다. 기존 이미지 재활용 여부는 launcher의 bundle/ID 검사로 결정한다.
- GitHub Actions는 처음 실행하므로 action 다운로드·checkout·설치·fixture·upload 통합이 성공한다고 선판정하지 않는다.
- 승인된 호스트에 직접 접속할 연결은 현재 없다. 원격 Run 생성과 호스트에서 필요한 serve 실행을 구분해 보고한다.

## 판정 및 중단

정상: Job/Check success, CI_RESULT PASS/rc0,32개 syntax와 양 엔진 전체 fixture/원본 artifact 확인.
결함: Job/Check failure, CI_RESULT FAIL/rc1, 양 엔진 baseline에서 지정한 첫 guard5 FAIL/ERROR0, artifact 성공.
환경/설치/인증 오류·취소·timeout·artifact 부재는 시험 실패 원인을 해결할 대상이지 결함 탐지 성공이 아니다.
등록/격리/정리 실패 시 새 세션을 반복하지 않고 해당 증적부터 확인한다.
독립 리뷰·수동 병합·Issue5 완료·운영 apply·운영 엔진 전환은 이번 시험 착수와 별도다.

공식 보완 근거: [Workflow 보안](https://docs.github.com/en/actions/reference/security/secure-use),
[PR trigger와 SHA](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request).
