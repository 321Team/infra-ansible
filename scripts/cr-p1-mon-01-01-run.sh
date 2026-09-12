#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

change_id="CR-P1-MON-01-01"
repo_root="$(git rev-parse --show-toplevel)"
evidence_root="${CR_EVIDENCE_DIR:-${repo_root}/docs/evidence/${change_id}}"
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

require_change_approval() {
  test "${CR_CHANGE_APPROVED:-}" = "${change_id}"
}

case "${action}" in
  precheck)
    run_playbook "precheck" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-precheck.yml"
    ;;
  apply)
    require_change_approval
    run_playbook "apply_check_diff" --check --diff \
      -e "cr_mon_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    run_playbook "apply" \
      -e "cr_mon_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    run_playbook "apply_idempotency" \
      -e "cr_mon_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    ;;
  verify)
    run_playbook "verify" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-verify.yml"
    ;;
  rollback)
    require_change_approval
    run_playbook "rollback" \
      -e "cr_mon_rollback_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-rollback.yml"
    ;;
  finalize)
    head_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
    {
      echo "# ${change_id} Evidence Index"
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
    echo "usage: $0 {precheck|apply|verify|rollback|finalize}" >&2
    exit 64
    ;;
esac
