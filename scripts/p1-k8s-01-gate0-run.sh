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

run_playbook() {
  local label="$1"
  shift
  ansible-playbook -i "${repo_root}/inventory/hosts.yml" "$@" \
    2>&1 | tee "${evidence_root}/${timestamp}_${label}.txt"
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
    head_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
    {
      echo "# ${ticket_id} Gate 0 Evidence Index"
      echo
      echo "- Generated: ${timestamp}"
      echo "- Repository: 321Team/infra-ansible"
      echo "- Commit: ${head_sha}"
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
