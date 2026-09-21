# Ansible 격리 Runner v1.3 — IPC 수정 및 준비 재검증

Run35139314896/Attempt1은 실제 실행 후 FAIL이다. 32개 syntax rc0,
두 엔진의 baseline fixture는 각각 PASS0/FAIL0/ERROR14이며 /dev/shm 읽기 전용으로 multiprocessing이 실패했다.
원본 artifact397파일 및 SHA256 검증 완료. 상세 근거는 IPC_FAILURE_REVIEW.md.

## 변경과 현재 한계

Runner만 private IPC와64MiB /dev/shm tmpfs(rw,nosuid,nodev,noexec,mode1777)를 사용한다.
루트 읽기 전용·network none·SELinux·capabilities0·CPU2/RAM4GiB/PIDs512·proxy 제한은 유지한다.
모든 모드에서 shm mount4개와 fork/spawn semaphore·자식통신 검사를 토큰 읽기 전에 수행한다.
검사 실패 시 등록 및 prepare PASS를 차단한다. Proxy에는 새 쓰기 가능 마운트를 추가하지 않는다.

기존 Runner v1.2 이미지/PREPARED는 이 bundle에서 재사용할 수 없다. 새prepare로 새이미지를 만든다.
이 ZIP을 작성한 환경에서 Python IPC 동작은 통과했으나 실제cicd-runner01의 수정Podman 실행은 아직 NOT_RUN이다.
토큰 발급·등록·Actions 재실행은 이 문서의 절차에 포함하지 않는다.
기존 부재증적은 ID3 대상이다. 이번 ID4는 관리자 API로 별도 확인한다.

## 실행

ZIP과 .zip.sha256를 두 호스트의 기존 로그인 홈에 복사한다.
root/sudo 로그인으로 시작하지 않는다. 경로를 입력받거나 HOME을 재정의하지 않는다.
새wrapper에는 홈chmod·삭제·서비스설정 변경이 없다. 증적은 기존로그인홈 신규디렉터리에 생성한다.

1. ansible01 / server01_ansible: 기존 gh 인증으로 ID4/name 부재를 GET 확인한다. 삭제나 토큰 발급은 없다.

```bash
(
set -euo pipefail
umask 077
cd "$HOME"
sha256sum -c FDS_Ansible_Actions_Runner_v1_3.zip.sha256
TASK_IPC_ADMIN=$(mktemp -d "$HOME/ansible-ipc-admin.XXXXXXXX")
unzip -q FDS_Ansible_Actions_Runner_v1_3.zip -d "$TASK_IPC_ADMIN"
cd "$TASK_IPC_ADMIN/FDS_Ansible_Actions_Runner_v1_3"
bash 01-admin-absence.sh
)
```

2. cicd-runner01 / server01_cicd-runner: 수정된이미지 생성과 토큰없는 prepare 실행.

```bash
(
set -euo pipefail
umask 077
cd "$HOME"
sha256sum -c FDS_Ansible_Actions_Runner_v1_3.zip.sha256
TASK_IPC_PREPARE=$(mktemp -d "$HOME/ansible-ipc-prepare.XXXXXXXX")
unzip -q FDS_Ansible_Actions_Runner_v1_3.zip -d "$TASK_IPC_PREPARE"
cd "$TASK_IPC_PREPARE/FDS_Ansible_Actions_Runner_v1_3"
bash 02-prepare.sh
)
```

prepare는 기존 계정검증 후 sudo로 전용비sudo계정에 전환하고 새실행경로만 사용한다.
이미지빌드를 위해 고정Runner2.337.0 배포파일을 다시다운로드하며 SHA256/크기를 검증한다.
원본Python기반이미지를 재사용하고 호스트패키지·기존앱Runner서비스를 변경하지 않는다.

## 제출과 다음 실행

각 호스트의 HOME_EVIDENCE= 압축파일과 .sha256를 제출한다.
관리자는 ansible-runner-absence.tar.gz, Runner는 ansible-actions-runner-evidence.tar.gz다.
관리자 PASS_ABSENT와 서버 PASS_PREPARE,18개격리체크,ipc_preflight_passed=true,
네트워크probe·cleanup·새image/bundle/PREPARED 일치를 확인한뒤 같은PR20 소스로 정상Actions를 재시험한다.
실패 시 같은실행을 반복하거나 구영수증을 편집하지 말고 생성된증적부터 확인한다.

과거 DEEP_REVIEW/CODE_REVIEW/PREPARE_FAILURE_REVIEW/REGISTRATION_FAILURE_REVIEW와
validation/INPUT_RECEIPT 및 REGISTRATION_INPUT_RECEIPT는 버전별 이력이다.
현재검증은 validation/IPC_INPUT_RECEIPT.json·IPC_RESULTS.json 및 새로그다.
정상Actions PASS·결함시험·독립승인·병합·운영apply·Issue5완료는 아직 충족되지 않았다.
