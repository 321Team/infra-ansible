# v1.3 코드 작성 전 딥리뷰

대상: PR19 HEAD 2fae52a9e09e33b8c8bff6c653b8533d8b52dc47의 Runner v1.2.
입력: 서버 증적 SHA256 dc2cd0c482e4a913e2824d90fad05b8c5e392c1c83f3a120fb2e5b16fdf2e02b,
Run35139314896/Attempt1, Job104939547998, artifact10465860514
ZIP SHA256 e678eead880bd62a47b6c41428ad519646c54f66b315eb552890b82240eeb1a3.

## 확인한 사실과 원인

서버 외부/내부 manifest 및 Actions artifact396행/fixture231행을 검증했다.
Runner ID4/name ansible-ci-cffaab5978b74334828fc94e91fc9de7이 Job을 실행했다.
기존 격리14개와 로컬 컨테이너·proxy·workspace 정리는 통과했으나 GitHub 등록 부재는 아직 미확인이다.
32개 syntax rc0에도 2.16.19/2.21.3 baseline 각각 PASS0/FAIL0/ERROR14다.
두 원본 regression.log 모두 /dev/shm의 Errno30 Read-only file system으로 multiprocessing이 중단됐다.
14개 matrix 실행 모두 같은 원인으로 ERROR14다. 의도한 결함 탐지 성공이 아니다.

Podman 공식 문서 https://docs.podman.io/en/latest/markdown/podman-run.1.html 의
--read-only-tmpfs 항목은 false일 때 /dev 및 /dev/shm이 읽기 전용이라고 명시한다.
--tmpfs는 선택 경로의 쓰기 가능한 임시 메모리 마운트를 지원한다.
v1.2 prepare는 Listener/네트워크/격리만 확인해 Ansible의 실제 IPC 요구를 놓쳤다.

## 수정 범위·검토 판단

1. Runner에만 --ipc=private 및 /dev/shm 전용64MiB tmpfs(rw,nosuid,nodev,noexec,mode1777)를 추가한다.
   Proxy, root-readonly, network none, capabilities0, SELinux, CPU2/RAM4GiB/PIDs512는 유지한다.
   --ipc=host, 호스트 /dev/shm bind, privileged, 보안 설정 전체 해제는 사용하지 않는다.
2. /proc/self/mountinfo와 statvfs로 tmpfs/rw/크기 상한/보호 옵션을 확인한다.
   별도 bounded subprocess에서 Python fork/spawn context의 semaphore 생성과 spawn 자식 통신을 확인한다.
   이 검사는 모든 모드에서 등록 토큰을 읽기 전에 수행하고 실패 시 등록·prepare PASS를 차단한다.
   고정 boolean만 증적으로 내보내고 원시 예외·토큰·job 문자열을 추가하지 않는다.
3. bundle/image/PREPARED 바인딩을 유지한다. 변경한 코드로 새 이미지와 새 prepare 증적이 필요하다.
   구 v1.2 영수증을 수정하거나 v1.3에 재사용하지 않는다. 즉시 Actions rerun은 하지 않는다.
4. 부재 확인은 ansible01에서 gh GET으로 ID4 및 정확한 name 둘 다 검사한다. 삭제API는 없다.
   prepare wrapper는 고정 원래 사용자/호스트/홈·bundle hash 확인 뒤 호출하고 token 입력이 없다.
   홈 chmod/삭제/환경변수 HOME 재설정은 없다. 증적은 원래 로그인 홈의 신규 경로다.
5. 회귀검증: 원본정책테스트·등록파서테스트, shm mount 변이 거절, IPC fail-closed,
   실제 Python IPC probe(가능하면)와 잘못된호스트 조기거절. 로컬/mock와 서버Runtime은 구분한다.
6. 실제Actions source/Workflow는 변경하지 않는다. 정상 재시험은 새prepare·ID4부재 확인 뒤 수행한다.
   결함시험·독립승인·병합·운영적용·Issue5완료는 이번수정으로 선언하지 않는다.

64MiB와 해당 검사는 정본의 최소권한·격리·추적 요구를 구현하는 권장값이지 정본의 숫자 요구가 아니다.
