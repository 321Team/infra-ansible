# Ansible 전용 Actions Runner v1 — 검토·실행 키트

현재 권장 실행은 **`prepare`**다. 등록 토큰 없이 전용 컨테이너 이미지와 격리·통신을 실서버에서 검사한다. 새 Runner 등록, 실제 Actions, 활성화 리뷰, merge, 운영 적용은 이 키트의 로컬 검증으로 완료되지 않는다.

## 확인된 출발점

- 2026-09-16 제출 증적: cicd-runner01의 기존 앱 Runner ID2는 infra-cicd 소속이며 online/idle이었다. infra-ansible Runner는 0대였다. 이 관측은 이후 상태를 보장하지 않는다.
- cicd-runner01: 기존 로그인 `server01_cicd-runner` UID1000, 격리 계정 `ansible-verify` UID1001/GID1002. 격리 계정 password locked/비sudo, home0700를 매번 다시 검사한다. sudo 목록의 rc0만으로 권한을 판단하지 않는다.
- 제출된 r3 증적에서 rootless Podman6.1/SELinux Enforcing/cgroupv2와 두 Ansible 엔진 localhost 회귀가 실제 PASS했다. 새 Runner의 실서버 PASS 근거로 대체하지 않는다.
- 검토 대상: CI PR17 `169571801d1b0cee0ba75137380149a48d6b56dd`, egress PR18 `d5147ebff0febbb8ab2afca28fe64d68301e033c`. 소스가 바뀌면 후속 Actions 증적은 새 SHA로 다시 묶어야 한다.

## 지금 실행할 명령 — cicd-runner01 기존 로그인

zip과 zip.sha256를 기존 로그인 홈에 놓고 다음을 실행한다. 토큰 파일은 필요 없다.

```bash
cd "$HOME"
sha256sum -c FDS_Ansible_Actions_Runner_v1.zip.sha256
unzip FDS_Ansible_Actions_Runner_v1.zip
cd FDS_Ansible_Actions_Runner_v1
sha256sum -c SHA256SUMS
sudo bash run.sh prepare
```

이미 같은 이름의 폴더가 있으면 기존 내용을 덮어쓰지 말고 새 폴더에 압축을 해제한다. `sudo`는 계정 검사·검토본 설치·UID 전환·증적 수집에 사용하며 Podman은 UID1001로 실행한다. 기존 앱 Runner 서비스·등록·방화벽·sudo 정책을 바꾸지 않는다.

최종 출력의 `HOME_EVIDENCE=` 파일과 같은 경로의 `.sha256`를 제출한다. 성공·실패 모두 `/home/server01_cicd-runner/ansible-actions-evidence-*/`에 생성한다. 실패 시 다른 단계로 진행하지 말고 이 두 증적만 제출하면 된다.

`STATUS=PASS_PREPARE`에는 다음이 모두 필요하다.

1. 전용 계정과 비sudo, systemd user bus, rootless Podman, SELinux Enforcing, cgroupv2/systemd 확인.
2. 실행 시점 CPU≥4개, 사용 가능 RAM≥6GiB, home 여유≥8GiB. Runner는 CPU2/RAM4GiB/PIDs512, proxy는 CPU0.25/RAM256MiB/PIDs128로 제한한다. 기존 앱 작업이 쓰는 자원도 고려해 한 세션만 실행한다.
3. r3에서 확인된 Python base 이미지가 전용 계정의 로컬 저장소에 있고 ID가 일치해야 한다. 자동으로 다른 태그를 pull해 대체하지 않는다.
4. 공식 Runner v2.337.0 Linux x64 파일 226,430,031bytes와 SHA256 검증, network=none 이미지 build, Listener 버전·실행 의존성 확인.
5. Runner 컨테이너 UID/GID1000, cap0, NNP, seccomp, SELinux container_t, root/socket mount readonly, loopback만 존재, CPU/RAM/PIDs 제한 및 직접 공인/사설주소 연결 거절 확인.
6. 제한 프록시를 통한 GitHub/PyPI HTTPS 4건과 사설·metadata·미허용 도메인 거절 4건 확인. HTTPS 응답 수신은 인증/API/Actions 성공 판정이 아니다.
7. 이번에 생성한 두 CID만 제거하고 private workspace를 정리한다. 하나라도 확인되지 않으면 FAIL. 이미지 캐시와 검토본 설치 폴더는 다음 단계에 사용한다.

`PREPARED=`는 UID1001 홈에 남는 검증 영수증의 절대 경로다. 이 영수증은 키트 manifest와 이미지 ID에 묶이며 키트를 수정하면 다시 prepare해야 한다. 복제하거나 수기로 고치지 않는다.

## 격리와 네트워크 범위

Runner 전체는 `--network=none` 컨테이너에서 실행한다. 컨테이너 내부127.0.0.1:3128 → readonly로 마운트한 Unix socket → 별도 rootless proxy의 연결만 제공한다. proxy는 HTTPS CONNECT443과 코드에 고정된 GitHub/PyPI hostname만 허용하고 DNS 결과 전체가 공인 주소인지 검사한 후 같은 주소로 연결한다. 사설주소, loopback, metadata, IP literal, 다른 포트, DNS의 공인·사설 혼합 결과를 거절한다.

`*.actions.githubusercontent.com`, `*.blob.core.windows.net`는 Actions 통신에 필요한 suffix 허용 범위다. 이는 공개 목적지 제한이며 특정 저장소만을 식별하는 애플리케이션 방화벽은 아니다. 이 환경에 운영 자격증명을 넣지 않는다. 새로운 도메인이나 필요한 Runner 업데이트는 공식 변경을 확인하고 코드 리뷰·prepare 후 반영한다.

Unix socket의 SELinux 공유와 .NET 의존성은 prepare의 실제 확인 대상이다. 실패를 해결하려고 `--privileged`, SELinux disable, host network, daemon socket, 운영 계정 재사용으로 변경하지 않는다. 컨테이너는 호스트 커널을 공유하며 VM 경계로 간주하지 않는다.

## 후속 단계 — prepare 증적 확인 후

### 1. 단기 토큰 발급·등록 후 해제 검사

관리 호스트 ansible01에서 같은 검토본을 열고 기존 관리 로그인으로 실행한다.

```bash
python3 -I -B admin-token.py
```

도구는 해당 관리 호스트의 `gh` 인증으로 `321Team/infra-ansible` 등록/제거 단기 토큰만 발급하고 로그인 홈에0600 packet을 만든다. PAT/gh 인증 파일을 Runner 호스트로 복사하지 않는다. `TOKEN_PACKET=` 파일은 자격증명이므로 이 대화나 증적에 첨부하지 않는다. 기존 승인된 사설 파일 전송 경로로 cicd-runner01 로그인 홈에0600으로 전달한다. 등록 시점에 두 토큰 모두 10분 이상, 120분 이하가 남아 있어야 한다.

cicd-runner01에서 실제 출력 경로로 다음 두 변수를 채운다.

```bash
PREPARED_PATH='/home/ansible-verify/ansible-actions-실제ID/evidence/PREPARED.json'
TOKEN_PATH="$HOME/ansible-runner-token-실제이름.json"
sudo bash run.sh registration-check --prepared "$PREPARED_PATH" --token-file "$TOKEN_PATH"
```

등록 이름은 `ansible-ci-<새 UUID>`이고 labels는 `self-hosted,Linux,X64,fds-ci,ansible-isolated`다. 기존 이름으로 replace하지 않는다. 이 모드는 Listener를 시작하지 않으며 등록 후 즉시 remove한다. `PASS_REGISTRATION_CHECK`는 config/remove 반환코드·선별 identity·컨테이너 정리 통과를 뜻한다. 관리 호스트에서도 해당 ID/name이 저장소 Runner 목록에서 사라졌는지 확인해야 한다.

등록/제거 또는 세션이 중단되면 GitHub에 offline record가 남을 수 있다. 증적의 repository 및 `runner_name`/`agentId`와 관리 호스트 API 목록을 대조해 이번 생성 항목만 정리한다. CID 누락·정리 실패라면 dedicated_run/CLEANUP.json을 기준으로 확인하고 재실행 전에 남은 컨테이너를 해결한다. 전체 Runner 삭제나 Podman prune은 사용하지 않는다.

### 2. 활성화 검토 후 Job1개 세션

PR17의 workflow는 아직 `docs/ci/ansible-regression.workflow.yml`에 있는 비활성 템플릿이다. 이 키트는 workflow를 `.github/workflows`로 복사하거나 변수/정책을 활성화하지 않는다. 먼저 새 격리 Runner, 같은 저장소 PR만 실행, contents:read, secret 없음, 정확한 source SHA 및 정상/고의 결함 검증계획을 독립 리뷰한다.

활성화 변경이 승인·반영되면 Runner selector의 후보는 `["self-hosted","Linux","X64","fds-ci","ansible-isolated"]`다. actual Runner의 API labels와 일치하는지 확인한다. 준비·등록 증적만으로 활성화 승인을 대체하지 않는다.

새 단기 토큰 packet으로 한 세션을 시작한다.

```bash
sudo bash run.sh serve --prepared "$PREPARED_PATH" --token-file "$TOKEN_PATH"
```

최대1시간, Job1개 후 종료하는 ephemeral Runner다. 정상/고의 결함 시험은 각각 새로운 세션이 필요하다. 외부 호스트 controller가 timeout·종료 후 정확한 CID를 정리한다. `SESSION_ENDED_REQUIRES_CI_REVIEW`는 Job 종료를 관측했음을 의미하며 Job 자체가 Failed인 경우에도 나올 수 있다. GitHub에서 Run ID, Attempt, source/workflow/check SHA, 실제 conclusion, artifact SHA와 실패 차단을 별도로 검증한다. 정상 종료 전 중단되면 관리 API의 등록 제거 확인이 필요하다.

Runner는 자동 업데이트를 비활성화한 버전 고정 이미지다. GitHub의 업데이트 허용 기간과 보안 업데이트 요구를 계속 충족해야 하며 버전 갱신 시 코드/이미지 검토·prepare를 반복한다. 장기간 운영용 상시 서비스나 재부팅 자동 복구 서비스는 제공하지 않는다.

## 증적·토큰 처리

- token packet은 root launcher → runuser controller → `podman -i` stdin으로 전달한다. Podman argv/env·증적에는 원문을 넣지 않는다. config child에만 공식 `ACTIONS_RUNNER_INPUT_TOKEN` env 입력을 사용한다.
- Runner `_diag`, `.credentials`, raw native output, token packet은 archive에서 제외한다. job을 실행한 모드에서는 컨테이너 출력의 임의 문자열을 수집하지 않고 고정 필드와 상태만 선별한다.
- prepare는 토큰을 읽지 않으므로 실패 분석용 build/container 로그 끝64KiB를 포함할 수 있다.
- workspace 삭제는 컨테이너 제거 확인 뒤 수행한다. 정리 실패 때는 FAIL과 잔존 위치를 기록하며 credential workspace가 남을 수 있으므로 증적 확인 후 해당 위치만 정리한다.
- 원본 token packet은 자동 삭제하지 않는다. 사용 후 발급·만료 정책에 따라 관리하고, 증적 제출 대상으로 선택하지 않는다.

## 로컬 검증과 실제 검증의 구분

`validation/RESULTS.json`과 `validation/unit.log`는 제작 환경의 단위·프로토콜 모형·파일/프로세스 경계 검사다. `python3 -I -B test-kit.py`로 재현한다. 실제 Podman build, UDS/SELinux 통신, Runner 등록, 실제 Actions는 제작 환경에서 NOT_RUN이다. 자체 코드 리뷰 기록은 독립 리뷰 승인이나 실제 서버 실행 증적이 아니다.

## 공식 근거

- [Runner v2.337.0 release와 checksum](https://github.com/actions/runner/releases/tag/v2.337.0)
- [해당 버전의 token env 처리](https://github.com/actions/runner/blob/v2.337.0/src/Runner.Listener/CommandSettings.cs)
- [GitHub Runner 프록시 설정](https://docs.github.com/en/actions/how-tos/manage-runners/use-proxy-servers)
- [Runner 통신·ephemeral·업데이트 정책](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)
- [Podman run의 userns·mount·보안 옵션](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
