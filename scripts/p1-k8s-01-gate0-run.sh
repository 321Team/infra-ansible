#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ticket_id="P1-K8S-01"
repo_root="$(git rev-parse --show-toplevel)"
evidence_root="${GATE0_EVIDENCE_DIR:-${repo_root}/docs/evidence/${ticket_id}}"
action="${1:-}"
timestamp="$(date '+%Y%m%dT%H%M%S%z')"

test "$(hostnamectl --static)" = "ansible01"
test "$(id -un)" = "server01_ansible"
test -n "${ANSIBLE_PRIVATE_KEY_FILE:-}"
test -r "${ANSIBLE_PRIVATE_KEY_FILE}"
mkdir -p "${evidence_root}"

# F07 (권욱님 코드 리뷰, 최소 보완): finalize가 "지금 시점" HEAD만 인덱스에
# 남기면 run(A) 직후 checkout(B) → finalize(B) 순서에서 A의 로그가 B에서
# 검증된 것으로 오인될 수 있다. run/check 실행 시점의 HEAD·종료 코드를
# 로그와 함께 남기고, finalize는 이 값을 그대로 인용한다.
#
# F07 재검토 (권욱님 코드 리뷰):
# 이전 수정은 ansible-playbook | tee 파이프라인의 성공·실패 경로에서
# PIPESTATUS[0]만 참조했다. 그러나 PIPESTATUS[0]은 ansible-playbook의
# 종료 코드만 의미하므로, ansible이 성공했더라도 tee가 실패하면
# exit_code=0으로 잘못 기록될 수 있다.
#
# 따라서 set -e가 파이프라인 실패에서 함수를 즉시 종료시키지 않도록
# 파이프라인을 if 조건 안에서 실행하고, 각 경로에서 PIPESTATUS 배열
# 전체를 즉시 복사한다. 이후 ansible/tee 각각의 종료 코드를 기록하고,
# pipefail과 동일하게 마지막 non-zero 종료 코드를 최종 exit_code로
# 사용한다. (참고: "|| true"로 파이프라인 실패를 무마하는 방식은
# 채택하지 않는다 — true가 실행되는 순간 그 자체가 새 명령이 되어
# PIPESTATUS를 덮어쓸 수 있기 때문이다.)
# Load from this wrapper, not the caller working directory.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib/ansible-engine.sh" || exit 1
fds_engine_init || exit "$?"

run_playbook() {
  local label="$1"
  shift
  local exit_code
  local ansible_rc
  local tee_rc
  local run_head_sha
  local -a pipe_status

  run_head_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"

  if fds_engine_exec ansible-playbook -i "${repo_root}/inventory/hosts.yml" "$@" \
      2>&1 | tee "${evidence_root}/${timestamp}_${label}.txt"; then
    pipe_status=("${PIPESTATUS[@]}")
  else
    pipe_status=("${PIPESTATUS[@]}")
  fi

  ansible_rc="${pipe_status[0]}"
  tee_rc="${pipe_status[1]}"

  # pipefail과 동일하게 마지막 non-zero 종료 코드를 최종 코드로 사용한다.
  if [ "${tee_rc}" -ne 0 ]; then
    exit_code="${tee_rc}"
  else
    exit_code="${ansible_rc}"
  fi

  {
    echo "log_file=${timestamp}_${label}.txt"
    echo "head_sha=${run_head_sha}"
    echo "ansible_exit_code=${ansible_rc}"
    echo "tee_exit_code=${tee_rc}"
    echo "exit_code=${exit_code}"
  } > "${evidence_root}/${timestamp}_${label}.meta"

  return "${exit_code}"
}

case "${action}" in
  syntax)
    fds_engine_exec ansible-playbook -i "${repo_root}/inventory/hosts.yml" --syntax-check \
      "${repo_root}/playbooks/p1-k8s-01-gate0-precheck.yml"
    ;;
  check)
    run_playbook "gate0_check_diff" --check --diff \
      "${repo_root}/playbooks/p1-k8s-01-gate0-precheck.yml"
    ;;
  run)
    run_playbook "gate0_precheck" \
      "${repo_root}/playbooks/p1-k8s-01-gate0-precheck.yml"
    ;;
  finalize)
    finalize_head_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
    {
      echo "# ${ticket_id} Gate 0 Evidence Index"
      echo
      echo "- Generated: ${timestamp}"
      echo "- Repository: 321Team/infra-ansible"
      echo "- Finalize HEAD: ${finalize_head_sha}"
      echo "- Working directory: $(pwd)"
      echo
      echo "## Environment (per code review request)"
      echo '```text'
      fds_engine_exec ansible --version
      echo '```'
      echo
      echo "### ansible-config dump --only-changed"
      echo '```text'
      (cd "${repo_root}" && fds_engine_exec ansible-config dump --only-changed)
      echo '```'
      echo
      # F07 재검토: *.meta 기준 순회는 실행이 중단되어 .meta가 없는
      # 실패 로그를 인덱스에서 아예 누락시켰다. *.txt 로그를 기준으로
      # 순회하고 대응하는 .meta 존재 여부를 개별 확인해, 실행 정보가
      # 없는 로그도 명시적으로 드러낸다.
      #
      # F07 재재검토 (권욱님 코드 리뷰): source는 새 스코프를 만들지
      # 않으므로, 루프 반복 사이에 이전 .meta에서 설정된
      # head_sha/ansible_exit_code/tee_exit_code/exit_code 변수가
      # 그대로 남아 있었다. 구형 .meta처럼 일부 필드가 없는 파일을
      # source하면 그 필드는 갱신되지 않고 직전 반복의 값을 그대로
      # 재사용해 잘못된 값이 출력됐다. 매 반복 시작 시 이 변수들을
      # 명시적으로 UNKNOWN으로 초기화한 뒤 source하여, 없는 필드는
      # 반드시 UNKNOWN으로 표시되게 한다.
      echo "## Runs (HEAD/exit code as recorded at run/check time, not finalize time)"
      for log_file_path in "${evidence_root}"/*.txt; do
        [ -e "${log_file_path}" ] || continue
        log_name="$(basename "${log_file_path}")"
        meta_file="${log_file_path%.txt}.meta"
        echo
        echo "- Log: \`${log_name}\`"
        if [ -e "${meta_file}" ]; then
          head_sha="UNKNOWN"
          exit_code="UNKNOWN"
          ansible_exit_code="UNKNOWN"
          tee_exit_code="UNKNOWN"
          # shellcheck disable=SC1090
          source "${meta_file}"
          echo "  - Run HEAD: \`${head_sha}\`"
          echo "  - Ansible exit code: ${ansible_exit_code}"
          echo "  - tee exit code: ${tee_exit_code}"
          echo "  - Final exit code: ${exit_code}"
          if [ "${ansible_exit_code}" = "UNKNOWN" ] || [ "${tee_exit_code}" = "UNKNOWN" ]; then
            echo "  - ⚠ INCOMPLETE METADATA: this .meta predates per-command exit code tracking (ansible/tee breakdown unavailable)"
          fi
          if [ "${head_sha}" != "UNKNOWN" ] && [ "${head_sha}" != "${finalize_head_sha}" ]; then
            echo "  - ⚠ WARNING: run HEAD differs from finalize HEAD (${finalize_head_sha})"
          fi
        else
          echo "  - ⚠ NO EXECUTION METADATA: run/check terminated before metadata was recorded (HEAD/exit code unknown)"
        fi
      done
      echo
      echo "## Files"
      find "${evidence_root}" -maxdepth 1 -type f \
        ! -name EVIDENCE_INDEX.md ! -name SHA256SUMS \
        -printf '%f\n' | sort | sed 's/^/- `/' | sed 's/$/`/'
    } > "${evidence_root}/EVIDENCE_INDEX.md"
    (
      cd "${evidence_root}"
      find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum > SHA256SUMS
      sha256sum --check SHA256SUMS \
        > "${timestamp}_integrity_check.txt"
      find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum > SHA256SUMS
      sha256sum --check SHA256SUMS
    )
    ;;
  *)
    echo "usage: $0 {syntax|check|run|finalize}" >&2
    exit 64
    ;;
esac