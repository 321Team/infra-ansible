# Ansible Runner token input guard v1.0

기존의 입력 경로에 곧바로 chmod 600을 실행하는 안내를 폐기하고 이 도구로 대체한다.
**로컬 회귀시험 20/20 PASS. 실제 서버에서 이 보호 도구를 실행한 증적은 아직 없다.**
코드 작성 전 DEEP_REVIEW.md를 기록했으며 CODE_REVIEW.md는 자체 검토다.
독립 승인이나 실제 Actions 성공을 의미하지 않는다.

## 현재 상태와 사용 시점

2026-09-16 17:25:32–17:25:58 UTC의 제출 증적은 PASS_REGISTRATION_CHECK다.
Runner ID 3 / ansible-ci-f9e3ef4d85e44573891eaebcaffd5b1d의 등록·제거 rc0,
UTF-8 BOM 파싱·identity·격리·정리가 통과했다. 이 보호 도구를 사용하기 전 실행이다.
**보호 도구 확인만을 위해 토큰을 다시 발급하거나 등록 검사를 반복할 필요는 없다.**
다음 운영 확인은 관리 호스트에서 이번 ID/name의 API 목록 부재를 확인하는 것이다.

기존 Runner v1.2 24파일과 관리 토큰 도구 11파일은 변경하지 않았다.
기존 PREPARED/image 연결을 유지하므로 이 별도 도구 추가만으로 새 prepare가 필요하지 않다.

## 방어 범위

- cicd-runner01의 server01_cicd-runner 일반 로그인으로 실행한다. sudo로 실행하지 않는다.
- passwd 홈이 /home/server01_cicd-runner인지 확인한다. 환경변수 HOME을 신뢰 기준으로 쓰지 않는다.
- 홈 바로 아래 ansible-runner-token-<발급된이름>.json 일반 파일만 허용한다.
- 홈/디렉터리/심볼릭 링크/하드 링크/FIFO/다른 소유자/특수 권한/8KiB 초과 파일은 권한 변경 전에 거절한다.
- 같은 파일 디스크립터에서 JSON 형식·저장소·토큰 필드·남은 유효기간 10~120분을 확인한 후 fchmod(0600)만 실행한다.
- 입력 pathname으로 chmod하지 않는다. 이름이 디렉터리로 바뀌어도 그 디렉터리의 권한을 변경할 수 없다.
- 입력 검증 실패 때는 입력 파일과 홈 권한을 변경하지 않는다.
- 권한 적용 뒤 이름/메타데이터/증적 쓰기 검사에서 실패하면 검증한 파일은 0600으로 남을 수 있다.
  permission_changed로 이를 기록하며, 입력 경로에 대한 권한 복원을 시도하지 않는다.
- 재귀 chmod, 삭제, 계정·서비스 변경, 컨테이너 실행, Runner 등록, 외부 통신은 없다.
- 결과는 기존 로그인 홈의 새 ansible-token-input-evidence-* 0700 디렉터리에 RESULT.json과
  RESULT.json.sha256로 생성한다. 파일은 0600이다. 홈 자체가 부적합하면 터미널에서 중단하고 다른 위치에 쓰지 않는다.
- 증적에는 고정 오류 코드·상태·boolean만 저장한다. 토큰·입력 원문·토큰 해시·원시 예외를 남기지 않는다.
- 같은 UID의 동시 수정 자체를 보안 경계로 보장하지 않는다. 변경 감지 시 실패하고 이후 기존 launcher도 독립 재검증한다.

packet 계약은 검증된 Runner common.py와 같고 중복 JSON 키는 추가로 거절한다.

## 향후 토큰 입력 시 사용

ZIP과 sidecar를 cicd-runner01 기존 로그인 홈에 전달한 후, 일반 로그인에서 다음처럼 새 디렉터리에 푼다.
HOME 변수 자체를 재정의하지 않는다.

    (
      set -euo pipefail
      umask 077
      cd "$HOME"
      sha256sum -c FDS_Ansible_Runner_Input_Guard_v1_0.zip.sha256
      TASK_GUARD_DIR=$(mktemp -d "$HOME/ansible-input-guard.XXXXXXXX")
      unzip -q FDS_Ansible_Runner_Input_Guard_v1_0.zip -d "$TASK_GUARD_DIR"
      cd "$TASK_GUARD_DIR/FDS_Ansible_Runner_Input_Guard_v1_0"
      sha256sum -c SHA256SUMS
      read -r -p 'Token packet 절대 경로: ' TASK_TOKEN_PATH
      if python3 -I -B safe_input.py --token-file "$TASK_TOKEN_PATH"; then
        printf '입력 보호 검사 통과. 이후 승인된 Runner 단계에서 위 TOKEN_FILE을 사용하세요.\n'
      else
        printf '중단: 출력된 증적만 확인하세요.\n' >&2
        exit 1
      fi
    )

출력 STATUS=PASS_TOKEN_INPUT 및 exit0일 때만 이후 승인된 Runner 명령에 TOKEN_FILE을 전달한다.
자동화와 연결할 때도 보호 도구 실패 후 launcher를 실행하지 않도록 명시적 조건문으로 묶는다.
토큰 파일은 증적으로 제출하지 않는다. HOME_EVIDENCE로 출력한 JSON과 sidecar만 제출한다.
이 도구는 만료한 토큰을 갱신하거나 실제 Runner 실행을 승인하지 않는다.

## 지금 필요한 읽기 전용 확인 — ansible01 관리 로그인

이번 등록 검사는 이미 PASS했다. 관리 호스트에서 해당 ID 또는 이름의 잔존 여부만 확인한다.
아래 쿼리는 infra-ansible만 읽으며 infra-cicd의 기존 Runner ID2를 변경하지 않는다.

    (
      set -euo pipefail
      umask 077
      TASK_ABSENCE_FILE=$(mktemp "$HOME/ansible-runner-absence.XXXXXXXX.txt")
      printf 'repository=321Team/infra-ansible\nrunner_id=3\nrunner_name=ansible-ci-f9e3ef4d85e44573891eaebcaffd5b1d\nqueried_at_utc=%s\n' \
        "$(date -u +%FT%TZ)" > "$TASK_ABSENCE_FILE"
      TASK_QUERY_RC=0
      if gh api --paginate 'repos/321Team/infra-ansible/actions/runners?per_page=100' \
        --jq '.runners[] | select(.id == 3 or .name == "ansible-ci-f9e3ef4d85e44573891eaebcaffd5b1d") | {id,name,status}' \
        >> "$TASK_ABSENCE_FILE"; then
        :
      else
        TASK_QUERY_RC=$?
      fi
      printf '\nquery_rc=%s\n' "$TASK_QUERY_RC" >> "$TASK_ABSENCE_FILE"
      sha256sum "$TASK_ABSENCE_FILE" > "$TASK_ABSENCE_FILE.sha256"
      cat "$TASK_ABSENCE_FILE"
      printf 'HOME_EVIDENCE=%s\n' "$TASK_ABSENCE_FILE"
      exit "$TASK_QUERY_RC"
    )

query_rc=0이며 Runner JSON 항목이 없어야 해당 시점 부재를 확인할 수 있다.
목록에 남아 있으면 증적을 검토하며 자동 삭제하거나 전체 Runner를 정리하지 않는다.
HOME_EVIDENCE 파일과 sidecar를 제출한다.

## 로컬 검증

    python3 -I -B test_safe_input.py

20개 시험은 임시 홈 하위의 합성 파일·토큰만 사용한다. 실제 서버 자격증명·Podman·GitHub API는 사용하지 않는다.
validation/unit.log와 unit.rc는 실제 실행 결과다. validation/RESULTS.json에서 로컬 시험과 서버 미실행을 구분한다.
기존 Runner의 49개 시험을 이 도구의 시험 개수로 전용하지 않는다.
