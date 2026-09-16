# 코드 작성 후 자체 딥리뷰

2026-09-16. 구현 전 검토는 `DEEP_REVIEW.md`에 기록했다. 이 문서는 수정 후 코드 경계 재검토이며 독립 리뷰 승인은 아니다.

| 위험 경로 | 코드 처리 | 검증 범위 |
|---|---|---|
| 일반 network Runner의 내부망 접근 | network=none + readonly UDS + 고정 CONNECT 목적지, 전 DNS 결과 공인 검증 후 같은 IP 사용 | 명령·hostname·DNS·프로토콜 모형 테스트. 실제 UDS/SELinux는 prepare |
| root 설치가 linked directory를 따라가는 문제 | 모든 link/special/hardlink 거절, manifest 이름 제한, root-private 디렉터리에 목록 내 bounded 일반 파일만 복사 후 hash 검증 | empty linked directory 포함 부정 테스트 |
| 등록 토큰이 argv/env/log에 남는 문제 | launcher/host stdin, config child env만 사용, parent dumpable=0, native/private 로그 export 제외 | fake secret stdin 전달·명령 기록·선별 export 테스트. 실제 GitHub 미실행 |
| 등록 identity/해제 실패를 통과 처리 | 정확한 repository/name/id, config/remove rc 검증. registration-check 예외 시 자기 `.runner`가 생겼으면 remove 시도 | 판정 부정 테스트. API 관측 별도 |
| result 누락·OOM·rc1을 PASS로 처리 | image ID, container state/ExitCode/OOM, 모든 격리 항목 및 8개 probe 일치 필수 | result 부재와 조건별 부정 테스트 |
| CID 부재 또는 삭제 실패인데 workspace 제거 | 시작 시도 후 CID 부재는 FAIL, 두 정확한 CID rm + exists=1 확인, 확인 실패 시 workspace 보존 | 정확한 CID·잔존·CID 누락 모형 테스트 |
| root가 증적 link를 읽거나 archive를 추출 | dirfd/O_NOFOLLOW/regular/owner/nlink/size, sha 검증, 고정 JSON member bounded read만 수행 | symlink 거절·고정 결과 수집 테스트 |
| 기존 PASS를 다른 코드·이미지에 재사용 | PREPARED path/owner0600, bundle manifest/image ID/image label 모두 결합 | 잘못된 bundle/image 부정 테스트 |
| Runner 정상 종료를 CI 성공으로 오인 | serve는 SESSION_ENDED_REQUIRES_CI_REVIEW, Job 실패도 별도 Run/Attempt/SHA/artifact 검증 대상 | Failed Job 결과로도 CI 성공 판정이 나오지 않음 확인 |

## 실제 실행 전 남은 확인

- 공식 Runner archive 다운로드·base 이미지 build·Listener .NET 의존성, rootless keep-id와 user manager, SELinux Unix socket peer 접근, 공인주소443 실제 연결은 제작 환경에서 NOT_RUN이다.
- 제작 환경에 Podman이 없고 AF_UNIX socket 생성이 EPERM이므로 실제 컨테이너 및 proxy 통합 시험을 통과했다고 주장하지 않는다. 프로토콜 검사는 fake peer/validated-address 전달 경계 모형이다.
- `prepare`가 실패하면 등록하지 않는다. 로그/컨테이너 정리 상태를 확인해 구체적인 원인을 수정한 새 manifest로 다시 prepare한다. 보안 옵션을 완화하는 자동 fallback은 없다.
- Runner 세션은 일회용이며 상시 운영 서비스가 아니다. 호스트 재부팅·SIGKILL·전원 중단은 Python finally 정리를 보장하지 않으므로 같은 UUID/CID와 GitHub ID/name의 잔존을 관리 호스트에서 확인해야 한다.
- 모든 키트 자체 증적은 로컬 상태 기록이지 외부 attestation이 아니다. Job이 수정할 수 있는 session 결과를 독립 CI 성공 근거로 사용하지 않는다. 기존 앱 Runner의 관측·이슈 AC·활성화 리뷰 상태는 별도로 유지한다.


## v1.1 수정 후 검토 — 2026-09-16

실제 제출 v1 결과는 podman-info rc1, 컨테이너/등록 미착수다. 직접 원인은 stdout/stderr 누락으로 아직 확정하지 않았다. `PREPARE_FAILURE_REVIEW.md`의 수정 전 검토 후 다음을 반영했다.

- root launcher의 dedicated child cwd는 검증된 ansible-verify 홈으로, controller의 명령 cwd는 이번 run directory로 명시했다.
- Podman은 r3에서 사용한 local/systemd 옵션을 명시한다. 설정파일이나 계정 정책은 수정하지 않는다.
- stdout/stderr를 분리하고 prepare 고정 단계 로그만 각64KiB 보존한다. rc1/timeout/spawn failure 및 cleanup 명령도 포함한다. credentials 단계는 원문 export를 하지 않는다.
- diagnostics의 symlink·hardlink·special file을 거절하고, 수집 실패가 있으면 prepare PASS를 막는다.
- v1의 27건과 새 경계 검사10건, 총37건 PASS. 실제 Python 자식 프로세스의 cwd·rc1/stderr·timeout·JSON 경고 분리와 archive 보존을 확인했다. 실제 UID1001 Podman과 SELinux/Unix socket은 이번 제작 환경에서 실행하지 않았다.

검증 범위가 부족했던 v1의 prepare 오류 수집 경로를 회귀 대상에 추가했다. 자체 수정/검증 완료를 실서버 장애 해소나 독립 리뷰 승인으로 표시하지 않는다.
