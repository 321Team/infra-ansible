#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

change_id="CR-P1-ANS-01-01"
expected_base="98cf3f826ac0805bcc771ad760a15d931c1bd414"
repo_root="$(git rev-parse --show-toplevel)"
evidence_root="${CR_EVIDENCE_DIR:-${repo_root}/docs/evidence/${change_id}}"
action="${1:-}"
timestamp="$(date '+%Y%m%dT%H%M%S%z')"

test "$(hostnamectl --static)" = "ansible01"
test "$(id -un)" = "server01_ansible"
test -n "${ANSIBLE_PRIVATE_KEY_FILE:-}"
test -r "${ANSIBLE_PRIVATE_KEY_FILE}"
git -C "${repo_root}" merge-base --is-ancestor "${expected_base}" HEAD
mkdir -p "${evidence_root}"

# Load from this wrapper, not the caller working directory.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib/ansible-engine.sh" || exit 1
fds_engine_init || exit "$?"

run_playbook() {
  local label="$1"
  shift
  fds_engine_exec ansible-playbook -i "${repo_root}/inventory/hosts.yml" "$@" \
    2>&1 | tee "${evidence_root}/${timestamp}_${label}.txt"
}

require_change_approval() {
  test "${CR_CHANGE_APPROVED:-}" = "${change_id}"
}

case "${action}" in
  precheck)
    run_playbook "precheck" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-precheck.yml"
    ;;
  control-plane)
    require_change_approval
    run_playbook "control_plane_check_diff" --check --diff \
      -e "cr_dns_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-apply-control-plane.yml"
    run_playbook "control_plane_apply" \
      -e "cr_dns_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-apply-control-plane.yml"
    run_playbook "control_plane_idempotency" \
      -e "cr_dns_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-apply-control-plane.yml"
    ;;
  worker02-session)
    require_change_approval
    test "$#" -ge 3 && test "$#" -le 4
    session_action="$2"
    session_id="$3"
    session_hash="${4:-}"
    case "$session_action" in prepare|apply|reapply|rollback) ;; *) exit 64 ;; esac
    [[ "$session_id" =~ ^w02-[0-9]{8}T[0-9]{6}-[a-f0-9]{8}$ ]]
    test "${CR_DNS_SESSION_APPROVED:-}" = "${session_id}:${session_action}"
    if [[ "$session_action" == prepare ]]; then
      test -z "$session_hash"
    else
      [[ "$session_hash" =~ ^[a-f0-9]{64}$ ]]
    fi
    # This entrypoint always uses a selected pinned engine and reviewed clean source.
    test -n "$fds_engine_dir"
    session_source="$(git -C "$repo_root" rev-parse HEAD)"
    test "${CR_DNS_SOURCE_SHA:-}" = "$session_source"
    git -C "$repo_root" diff --quiet HEAD --
    session_untracked="$(git -C "$repo_root" ls-files --others --exclude-standard -- \
      library module_utils roles playbooks scripts inventory ansible.cfg)"
    test -z "$session_untracked"
    session_flags=()
    case "${CR_DNS_CHECK_ONLY:-0}" in
      0) ;;
      1) session_flags=(--check --diff) ;;
      *) exit 64 ;;
    esac
    run_playbook "worker02-${session_id}-${session_action}-$(date +%s%N)" \
      "${session_flags[@]}" \
      -e "cr_dns_change_approved=${change_id}" \
      -e "cr_dns_session_action=${session_action}" \
      -e "cr_dns_session_id=${session_id}" \
      -e "cr_dns_session_approved=${CR_DNS_SESSION_APPROVED}" \
      -e "cr_dns_session_source=${session_source}" \
      -e "cr_dns_session_sha256=${session_hash}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-worker02-session.yml"
    ;;
  workers)
    require_change_approval
    run_playbook "workers_check_diff" --check --diff \
      -e "cr_dns_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-apply-workers.yml"
    run_playbook "workers_apply" \
      -e "cr_dns_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-apply-workers.yml"
    run_playbook "workers_idempotency" \
      -e "cr_dns_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-apply-workers.yml"
    ;;
  verify)
    run_playbook "verify_all_nodes" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-verify.yml"
    ;;
  verify-worker02)
    run_playbook "verify_worker02" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-verify-worker02.yml"
    ;;
  rollback)
    require_change_approval
    rollback_host="${2:-}"
    test -n "${rollback_host}"
    run_playbook "rollback_${rollback_host}" \
      -e "cr_dns_rollback_host=${rollback_host}" \
      -e "cr_dns_rollback_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ans-01-01-rollback.yml"
    ;;
  finalize)
    head_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
    {
      echo "# ${change_id} Evidence Index"
      echo
      echo "- Generated: ${timestamp}"
      echo "- Repository: 321Team/infra-ansible"
      echo "- Commit: ${head_sha}"
      echo "- Expected base: ${expected_base}"
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
    echo "usage: $0 {precheck|control-plane|workers|worker02-session ACTION ID [SHA256]|verify|verify-worker02|rollback HOST|finalize}" >&2
    exit 64
    ;;
esac
