# 구현 전 딥리뷰 — Ansible 전용 Actions Runner

사용자의 2026-09-16 후속 착수 지시에 따라 이전 RUNNER_PLAN을 구현한다. 코드 작성 전에 이 설계 검토를 기록했다. 실제 서버에는 직접 접속할 수 없으며 제작 환경에는 Podman이 없다. 따라서 로컬 단위/모형 검증과 서버 prepare 검증을 분리한다.

## 입력과 범위

- infra-ansible Runner0대, infra-cicd ID2/cicd-runner01 online 확인. 기존 앱 Runner 계정 UID1000과 별도 시험 계정 ansible-verify UID1001/GID1002를 분리한다.
- 기존 r3의 Python3.12-bookworm 이미지 ID `sha256:e8565fa265f973c06f0515fac7aa9d102edae01b5677d69216900b84029c6ad0` 및 실제 두 엔진 PASS 근거를 사용한다. 이 이미지가 Runner를 지원하는지는 신규 self-test 대상이다.
- 공식 actions/runner v2.337.0 Linux x64 archive SHA256 `70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613`, release API asset digest와 release 본문이 일치한다. 다운로드·구동은 제작 환경에서 아직 하지 않았다.
- Runner의 ephemeral 등록은 Job1개 후 GitHub 등록을 해제하지만 로컬 파일 정리를 대신하지 않는다. 토큰은 gh/PAT가 아닌 등록·제거용 단기 입력만 런타임에 전달한다.

## 발견 사항과 반영할 설계

1. **직접 네트워크를 가진 Runner는 내부망 접근 경계가 불충분하다.** Runner 컨테이너 network=none 유지. 루프백 TCP → 전용 Unix socket → rootless proxy sidecar의 CONNECT 경로만 제공한다. 허용된 GitHub/PyPI hostname의 공인주소443만 연결한다. 사설/loopback/link-local/metadata/IP literal/잘못된 host·port와 DNS rebinding을 차단한다. ACL은 root 소유 이미지 코드에 고정하고 임의 config로 확대하지 않는다.
2. **Unix socket·SELinux 실제 호환성은 아직 미검증이다.** private0700 호스트 디렉터리와 두 컨테이너에만 공유하는 :z socket mount를 사용한다. Runner에는 이 디렉터리를 ro로 준다. prepare가 실제 컨테이너 UID1000·cap0·NNP·seccomp·SELinux·network=lo와 proxy 허용/거절, Listener --version을 검사한다. 실패 시 등록 토큰을 읽거나 Runner를 등록하지 않는다.
3. **관리 토큰과 원본 Runner 설정은 증적 유출 위험이 있다.** 관리 gh 토큰은 ansible01에 유지한다. 단기 토큰 packet은0600 파일에 저장하고 서버 전달 후 stdin으로만 넘긴다. podman argv/env·명령 기록에는 원문을 넣지 않는다. Runner config의 공식 ACTIONS_RUNNER_INPUT_TOKEN 사용 경로를 v2.337.0 CommandSettings.cs에서 확인했다. Runner 원문 _diag/.credentials·packet은 압축하지 않는다. 단계·반환코드·선별 상태만 외부 증적으로 남긴다.
4. **서비스 재사용은 권한 승계가 아니다.** root launcher는 기존 체크 도구로 전용 계정·비sudo·운영 자격증명 경로 부재를 확인하고 모든 Podman 실행은 UID1001로 낮춘다. 기존 앱 서비스·계정·방화벽·등록 URL은 변경하지 않는다. root는 설치 후 전용 계정 소유 코드를 실행하지 않는다.
5. **Job exit0은 CI 성공과 다르다.** serve 결과는 Runner session 종료 및 정리 결과로만 표시한다. Job 판정은 이후 Run/Attempt/Source·Workflow·Check SHA/artifact를 GitHub에서 별도로 확인한다. registration-check는 등록 후 바로 제거하며 Job을 실행하지 않는다.
6. **수명은 외부에서 관리한다.** 호스트 wrapper가 두 정확한 CID만 stop/rm하고 이번 작업의 private workspace만 삭제한다. 기존 이미지/다른 컨테이너/서비스를 prune하지 않는다. 실패·취소·timeout에서도 증적과 cleanup 상태를 보존한다. 로그/결과 파일은 고정 이름·일반 파일·크기 제한·no symlink로 취급한다.
7. **제작 환경의 성공을 실서버 성공으로 표시하지 않는다.** prepare를 기본 실행 안내로 제공한다. image build/Listener 런타임·Unix socket/SELinux·외부 HTTPS 허용/거절의 실제 통과 뒤 등록 검증으로 진행한다. 독립 활성화 리뷰 및 정상/고의 결함 Actions는 별도다.

## 검증할 위험 경로

- CONNECT hostname 경계·IP literal·사설/혼합 DNS·포트·헤더 길이·프록시 우회 거절.
- Runner/proxy 명령에 host network·daemon socket·privileged·sudo·토큰 argv/env가 없는지 확인.
- token packet repository·만료·종류·크기·파일 소유권/권한 검증, 비밀이 증적에 들어가지 않는지 확인.
- prepared artifact와 현재 bundle/image binding, 잘못된 이미지·정리 실패·result 누락의 nonzero 전달.
- 호스트 prepare의 실제 container/네트워크는 제작 환경에서 NOT_RUN이며 서버 증적을 받기 전 등록 가능으로 올리지 않는다.

공식 근거: https://github.com/actions/runner/releases/tag/v2.337.0 , https://github.com/actions/runner/blob/v2.337.0/src/Runner.Listener/CommandSettings.cs , https://docs.github.com/en/actions/how-tos/manage-runners/use-proxy-servers , https://docs.github.com/en/actions/reference/runners/self-hosted-runners , https://docs.podman.io/en/latest/markdown/podman-run.1.html .
