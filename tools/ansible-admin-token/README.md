# ansible01 토큰 발급 보완 v1.1.1

사용자 화면의 ZIP/manifest 확인은 통과했고 기존 admin-token.py가 `STOP: RuntimeError`로 종료됐다. 원본 코드는 예외 종류만 출력하므로 현재 직접 원인은 **UNKNOWN**이다. 일부 토큰 POST가 성공한 뒤 실패했을 가능성도 배제하지 않는다. Runner 등록/Job 실행은 이 도구의 기능이 아니다.

이 보완 도구는 ansible01 관리 계정에서만 실행한다. **cicd-runner01의 Runner v1.1 폴더·ZIP·PREPARED.json을 수정하지 않는다.** 기존 `PASS_PREPARE`에 사용된 bundle manifest는 `ecff16d871d7b08cd9aa72e580e54830b61d438ec9dcbbf3847bbac2f690ff46`이며 유지한다. 별도 관리 helper의 추가는 준비된 Runner 이미지 교체를 요구하지 않는다.

## 실행

이 ZIP과 sidecar를 ansible01 기존 관리 로그인 홈에 복사한 후, sudo 없이 실행한다.

```bash
(
set -euo pipefail
cd "$HOME"
sha256sum -c FDS_Ansible_Admin_Token_v1_1_1.zip.sha256
TASK_ADMIN_DIR=$(mktemp -d "$HOME/ansible-admin-tool.XXXXXXXX")
unzip -q FDS_Ansible_Admin_Token_v1_1_1.zip -d "$TASK_ADMIN_DIR"
cd "$TASK_ADMIN_DIR/FDS_Ansible_Admin_Token_v1_1_1"
sha256sum -c SHA256SUMS
python3 -I -B admin-token.py
)
```

조회/발급은 `github.com`, `321Team/infra-ansible`에 고정한다. 기존 gh 인증을 사용하며 로그인·권한·인증 파일·호스트 설정은 수정하지 않는다. 먼저 저장소 GET을 확인한 후 registration-token/remove-token POST를 순서대로 호출한다. 저장소 읽기와 `repository_admin_reported=true`는 토큰 POST 권한 통과를 보장하지 않는다.

일반 로그인 사용자/홈을 검증할 수 없거나 홈 쓰기 자체가 실패하면 고정 STOP 코드만 출력한다. 그 외 실패는 가능한 한 홈의 새0700 폴더에 증적을 남기고 exit1로 끝난다. 네트워크·강제 종료·전원 중단 등에 의해 항상 증적이 생성된다고 보장하지 않는다.

## 결과별 다음 행동

- `PASS_TOKEN_PACKET`: `TOKEN_PACKET=` 파일이 홈에0600으로 생성됐다. 해당 파일만 기존 WinSCP/SFTP 방법으로 cicd-runner01 기존 로그인 홈에 비공개 전송한다. PAT/gh 인증 파일은 전송하지 않는다. packet은 증적이 아니며 대화나 GitHub에 올리지 않는다.
- `FAIL`: `FAILED_STAGE`, `HTTP_STATUS`, `RETURNCODE`, `HINT`, `REMAINING_SECONDS`, `ERRNO` 중 해당 항목을 출력한다. 직접 원인을 확정하기 위한 진단 단서이며 임의 권한 확대나 보안 설정 변경을 하지 않는다.
- 성공/실패 모두 `HOME_EVIDENCE=`의 `ansible-admin-token-evidence.tar.gz`와 `.sha256`만 제출한다. archive에는 생성한 RESULT.json과 SHA256SUMS만 있다. token/API 응답/인증 헤더/gh 원문 stderr/packet 경로는 넣지 않는다.
- 반환코드0/HTTP201 발급 결과와 packet 검증이 모두 충족돼야 packet을 남긴다. 일부 발급 후 실패하면 packet은 생성하지 않는다. 이미 발급된 단기 토큰의 원격 취소를 수행했다고 주장하지 않는다.

| 코드/관측 | 확인할 내용 |
|---|---|
| LOGIN_USER_REQUIRED / ANSIBLE01_REQUIRED | ansible01 기존 일반 로그인으로 실행 여부 |
| MEMORY_PROTECTION_FAILED + errno | 해당 프로세스의 prctl 거절 원인; 보호를 끄고 우회하지 않음 |
| GH_NOT_FOUND | 관리 계정 PATH에서 gh 존재 여부 |
| HTTP401 또는 AUTH_LOGIN_REQUIRED | 관리 호스트의 기존 gh 인증 상태 |
| HTTP403 | 토큰 권한·조직 정책·SSO·rate limit 등 추가 확인 필요; 원인을 특정하지 않음 |
| HTTP404 | 지정 저장소/endpoint 접근성; 저장소가 없다고 단정하지 않음 |
| DNS_LOOKUP_FAILED / TLS_CERTIFICATE_ERROR / API_TIMEOUT | 관리 호스트 연결·이름해석·인증서·응답 지연 |
| TOKEN_LIFETIME_OUT_OF_RANGE | 증적의 UTC 시간과 두 토큰 남은 초; 600~7200초 정책 유지 |
| TOKEN_FORMAT_INVALID / TOKEN_EXPIRY_INVALID | API 응답 계약 불일치; 원문 토큰 공개 금지 |

GitHub의 등록·제거 토큰은 발급 후1시간 유효하다. 두 토큰을 전달·검사하는 시점에 각각10분 이상 남아 있어야 한다. 성공하면 바로 다음 검사를 진행한다.

## 성공 후 cicd-runner01

기존 Runner v1.1 키트에서 실행한다. `read` 질문에는 전송한 packet의 절대 경로만 넣는다.

```bash
(
set -euo pipefail
cd "$HOME/FDS_Ansible_Actions_Runner_v1_1"
sha256sum -c SHA256SUMS
read -r -p '전송한 TOKEN_PACKET 절대 파일 경로: ' TASK_TOKEN_PATH
chmod 600 -- "$TASK_TOKEN_PATH"
sudo bash run.sh registration-check \
  --prepared /home/ansible-verify/ansible-actions-a1a17a5e782944ab924a6af14fae7a52/evidence/PREPARED.json \
  --token-file "$TASK_TOKEN_PATH"
)
```

등록 후 즉시해제 검사이며 Job Listener는 시작하지 않는다. 이 단계에서도 기존 로그인 홈에 생성된 HOME_EVIDENCE archive와 sidecar를 제출한다. 후속 실제 Actions, 독립 활성화 리뷰, merge, 운영 적용은 별도이며 아직 완료가 아니다.

## 검증 범위

`DEEP_REVIEW.md`는 코드 작성 전에 기록했다. `validation/`은 제작 환경의 단위·모형·실제 로컬 자식 프로세스 검증이다. 실제 ansible01 GitHub 토큰 발급·관리 계정 상태는 재실행 전까지 NOT_RUN이다. 테스트용 가짜 token만 사용했다. 기존 common.py의 packet 계약을 바이트 그대로 재사용한다.

공식 근거: [gh api](https://cli.github.com/manual/gh_api), [GitHub Runner tokens](https://docs.github.com/en/rest/actions/self-hosted-runners#create-a-registration-token-for-a-repository).
