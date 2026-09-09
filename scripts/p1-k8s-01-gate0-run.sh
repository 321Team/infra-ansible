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
# F07 재검토 (권욱님 코드 리뷰): 이전 수정은 `ansible-playbook | tee`
# 파이프라인 다음 줄에서 PIPESTATUS를 읽고 .meta를 썼다. 하지만
# set -Eeuo pipefail 상태에서는 파이프라인이 실패하면 그 다음 줄에
# 도달하기 전에 셸이 종료되어, 실패한 실행은 .meta가 아예 생성되지
# 않았다. 파이프라인을 if/else로 감싸 set -e가 그 지점에서 발동하지
# 않게 하고, 성공·실패 두 경로 모두에서 PIPESTATUS[0]을 즉시 저장한
# 뒤 .meta를 작성하고 나서 실제 종료 코드를 반환한다.
run_playbook() {
  local label="$1"
  shift
  local exit_code
  local run_head_sha
  run_head_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"

  if ansible-playbook -i "${repo_root}/inventory/hosts.yml" "$@" \
      2>&1 | tee "${evidence_root}/${timestamp}_${label}.txt"; then
    exit_code="${PIPESTATUS[0]}"
  else
    exit_code="${PIPESTATUS[0]}"
  fi

  {
    echo "log_file=${timestamp}_${label}.txt"
    echo "head_sha=${run_head_sha}"
    echo "exit_code=${exit_code}"
  } > "${evidence_root}/${timestamp}_${label}.meta"

  return "${exit_code}"
}

case "${action}" in
  syntax)
    ansible-playbook -i "${repo_root}/inventory/hosts.yml" --syntax-check \
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
      ansible --version
      echo '```'
      echo
      echo "### ansible-config dump --only-changed"
      echo '```text'
      (cd "${repo_root}" && ansible-config dump --only-changed)
      echo '```'
      echo
      # F07 재검토: 이전에는 *.meta 파일을 기준으로 순회했기 때문에,
      # 실행이 중단되어 .meta가 없는 실패 로그는 인덱스에 아예 나타나지
      # 않았다 (누락이 "정보 없음"이 아니라 "표시 자체가 없음"으로
      # 보였다). *.txt 로그를 기준으로 순회하고 대응하는 .meta 존재
      # 여부를 개별 확인해, 실행 정보가 없는 로그도 명시적으로 드러낸다.
      echo "## Runs (HEAD/exit code as recorded at run/check time, not finalize time)"
      for log_file_path in "${evidence_root}"/*.txt; do
        [ -e "${log_file_path}" ] || continue
        log_name="$(basename "${log_file_path}")"
        meta_file="${log_file_path%.txt}.meta"
        echo
        echo "- Log: \`${log_name}\`"
        if [ -e "${meta_file}" ]; then
          # shellcheck disable=SC1090
          source "${meta_file}"
          echo "  - Run HEAD: \`${head_sha}\`"
          echo "  - Exit code: ${exit_code}"
          if [ "${head_sha}" != "${finalize_head_sha}" ]; then
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