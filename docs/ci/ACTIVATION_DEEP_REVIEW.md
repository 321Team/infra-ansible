# Workflow 활성화 전 딥리뷰 — 코드 변경 전 기록

검토 기준: PR17 `169571801d1b0cee0ba75137380149a48d6b56dd`, PR19 `2fae52a9e09e33b8c8bff6c653b8533d8b52dc47`.
이 문서는 코드 수정 전에 작성한 자체 검토이며 독립 승인이나 GitHub Actions 실행 결과가 아니다.

## 확인한 경계

Runner prepare, 등록/제거, 대상 ID3의 API 부재는 실제 증적으로 확인됐다.
PR17 템플릿은 docs/ci에 있어 아직 실행되지 않는다. CI 소스 SHA 고정, contents:read,
persist-credentials:false, fork 거절, 새 RUNNER_TEMP 하위 출력 및 localhost 시험 범위를 확인했다.
CI 실행기·wheel 수집/해시 검증·offline 설치와 Runner 컨테이너의 Python3.12/git 및 proxy 환경 전달 경로를 대조했다.
실제 action 다운로드·checkout·artifact 업로드 통합은 아직 미실행이므로 성공을 주장하지 않는다.

## 활성화 전 보완할 사항

### R1 — 격리 Runner 선택 계약이 설정값에 의존함

현재 runs-on은 ANSIBLE_CI_RUNNER_LABELS를 fromJSON으로 직접 사용한다.
enabled=true이며 설정값이 `["self-hosted"]` 또는 `["ubuntu-latest"]`이면 기존 job if를 통과한다.
따라서 코드가 필수 격리 라벨 fds-ci/ansible-isolated를 강제하지 않는다.
잘못된 JSON은 표현식 오류가 될 수 있다. 현재 활성화/실제 잘못된 스케줄링이 관측됐다는 뜻은 아니다.
infra-cicd의 저장소 전용 Runner ID2가 infra-ansible에 공유된다고 가정하지 않는다.

수정안: runs-on을 `[self-hosted, Linux, X64, fds-ci, ansible-isolated]`로 고정한다.
기존 설정 변수를 활성화 확인용으로 남기되 공백 없는 정해진 JSON 문자열과 일치할 때만 job if를 통과시킨다.
빈 값·부분 라벨·임의 그룹/Runner·JSON 오류는 skip한다. 변수값이 스케줄링 대상을 변경할 수 없어야 한다.
GitHub 문자열 비교는 대소문자를 무시하므로 이것을 바이트 단위 일치라고 주장하지 않는다.
라벨 순서·공백은 안내한 canonical 문자열을 사용한다. 실제 API 라벨/계정 격리는 활성화 시 별도로 확인한다.

### R2 — 허용 이벤트를 명시

현재 조건은 pull_request가 아닌 모든 이벤트를 허용하지만 현재 on에는 workflow_dispatch와 pull_request만 있다.
현재 노출 결함으로 판정하지 않으며, 후속 trigger 추가 때 묵시적 허용을 피하도록 두 이벤트만 명시한다.
동일 저장소 PR 및 수동 실행의 현재 동작은 유지하고 fork/미확정 이벤트는 거절한다.

## 변경 전 확정한 검증

- 원문 YAML을 읽어 고정 selector 계약과 enabled/라벨/이벤트/저장소 조건의 로컬 모델을 검사한다.
- 정상 PR/수동, disabled, 빈/부분/잘못된/객체 라벨, fork, pull_request_target 및 push 등 경계를 포함한다.
- 구 selector/넓은 조건을 재주입했을 때 회귀가 실제 실패하는지 확인한다.
- 기존 CI 실패 차단·source SHA·artifact 보존 시험도 실행한다.
- 로컬 모델은 GitHub expression 엔진, scheduler 또는 실제 Actions 인수의 대체가 아니다.
- Workflow 파일은 계속 docs/ci에 둔다. .github/workflows 편입·변수 변경·serve·merge는 이번 선행 작업에 포함하지 않는다.
- 기존 Runner 이미지/24파일·토큰 보호 도구는 수정하지 않는다. CI 후보 source SHA만 새로 검토한다.

## 공식 근거

- [Runner 라벨은 모두 충족해야 매칭](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow)
- [표현식 문자열 비교의 대소문자 처리](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions)
- [Job 조건과 Runner dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)
