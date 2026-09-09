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
run_playbook() {
  local label="$1"
  shift
  local exit_code=0
  local run_head_sha
  run_head_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
  ansible-playbook -i "${repo_root}/inventory/hosts.yml" "$@" \
    2>&1 | tee "${evidence_root}/${timestamp}_${label}.txt"
  exit_code="${PIPESTATUS[0]}"
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
      echo "## Runs (HEAD/exit code as recorded at run/check time, not finalize time)"
      for meta_file in "${evidence_root}"/*.meta; do
        [ -e "${meta_file}" ] || continue
        # shellcheck disable=SC1090
        source "${meta_file}"
        echo
        echo "- Log: \`${log_file}\`"
        echo "  - Run HEAD: \`${head_sha}\`"
        echo "  - Exit code: ${exit_code}"
        if [ "${head_sha}" != "${finalize_head_sha}" ]; then
          echo "  - ⚠ WARNING: run HEAD differs from finalize HEAD (${finalize_head_sha})"
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