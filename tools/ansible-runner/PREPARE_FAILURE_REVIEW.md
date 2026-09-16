# v1 prepare 실패 — 수정 전 딥리뷰

2026-09-16. 이 문서는 v1.1 코드 수정 전에 작성했다.

## 확정된 사실

- 입력 `ansible-actions-runner-evidence.tar.gz`: 3,779bytes, SHA256 `fe7e908018bc38f192154a429673150ba5e4c07cbdf73b322f651c9c3820bdaa`. 외부 checksum, 외부/내부 SHA256SUMS, 내장 archive checksum이 모두 일치했다. checksum은 포함된 바이트의 무결성이며 원격 실행의 독립 인증은 아니다.
- 2026-09-16 14:26:51 UTC(23:26:51 KST), `server01_cicd-runner`에서 v1 manifest `9006c07bd04fce3ff12f8d2a7bd3289059cea0e870632c494e8b0dfb14132907` 실행. 전용 계정 UID1001/GID1002·home0700·password locked·자격증명 경로 부재 검사 PASS, 정확한 비sudo denial 확인.
- `getenforce` rc0 후 `podman info --format=json` rc1. host/home 결과 FAIL. Runner/proxy 모두 NOT_CREATED, workspace REMOVED, registration_attempted=false. 이미지 build·Runner 등록·Actions로 진행하지 않았다.
- archive에는 podman-info stdout/stderr가 없다. v1 `runner.py`는 private 로그를 만들지만 실패 시 image-build/proxy-start/container 세 로그만 export하고 cleanup에서 private를 삭제한다. 따라서 현재 증적만으로 Podman rc1의 직접 원인을 확정할 정보가 부족하다.

## 코드 대조와 수정 설계

1. **로그 소실은 확정된 결함이다.** prepare의 고정된 비밀 없는 단계 stdout/stderr를 각각 끝64KiB까지 보존하고 길이·truncation·반환코드·timeout을 별도 JSON에 기록한다. 성공/실패/timeout/실행파일 부재에도 cleanup 전에 기록한다. 이후 토큰을 쓰는 registration-check/serve에는 이 원문 export를 적용하지 않는다.
2. **CWD 전달에 회귀가 있다.** 성공했던 r3는 dedicated main에서 `os.chdir(ROOT)`를 수행했다. v1 root launcher는 operator-side ROOT에서 runuser를 실행하며 dedicated controller의 Popen은 cwd를 지정하지 않는다. 현재 code path가 기존 로그인 홈의 작업 디렉터리를 UID1001에 넘기는 것은 확인된다. 실제 해당 경로의 접근 거절이 Podman rc1 원인인지는 stderr가 없어 확정하지 않는다. launcher는 전용 계정 홈, controller의 모든 명령은 이번 UID1001 소유 run directory에서 실행한다. 로그인 홈 권한을 완화하지 않는다.
3. **Podman 실행 조건을 확인된 r3와 맞춘다.** 모든 명령에 `--remote=false --cgroup-manager=systemd`를 명시한다. 호스트 설정 파일은 변경하지 않는다. 이 차이가 이번 rc1의 원인이었다는 주장은 하지 않는다.
4. **기계 판독 출력과 경고를 분리한다.** v1은 stdout/stderr를 합친 뒤 json.loads한다. rc0이어도 stderr warning이 있으면 JSON 판독 실패 가능성이 있다. stdout만 파싱하고 stderr는 별도 보존한다. 실제 제출 실패는 rc1이며 이 문제의 실제 발생 증거는 없다.
5. **오류 수집 자체도 실패 조건이다.** 로그 링크/special file을 따라가지 않고 지정한 private 일반 파일만 bounded read한다. 수집 실패를 명시하고 prepare PASS로 올리지 않는다. chmod/sudo/SELinux 완화, Podman reset/prune, 다른 계정/daemon 전환 fallback은 추가하지 않는다.

## 검증 계획·한계

기존 27건에 더해 전용 cwd 전달, rc1 stderr의 cleanup 이후 잔존, JSON+stderr warning 분리, timeout/spawn error 기록, oversized log tail, credential 단계 원문 미수집, root launcher cwd를 회귀 검증한다. 최소 재현에는 Podman 대신 실제 로컬 자식 프로세스를 사용한다. 실서버 Podman/SELinux/Runner 결과와 구분한다. 수정본 prepare를 새 폴더에서 재실행하고 동일한 홈 증적 두 파일로 판정한다.
