#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

change_id="CR-P1-NTP-01-01"
repo_root="$(git rev-parse --show-toplevel)"
evidence_root="${CR_EVIDENCE_DIR:-${repo_root}/docs/evidence/${change_id}}"
action="${1:-}"
timestamp="$(date '+%Y%m%dT%H%M%S%z')"

# Explicitly select the reviewed paired migration; an unset variable keeps
# the existing drop-in-only procedure. Apply approval remains separate.
ntp_mode_args=()
case "${CR_NTP_MIGRATE_MAIN:-0}" in
  0) ;;
  1) ntp_mode_args=(-e '{"cr_ntp_migrate_main":true}') ;;
  *) echo "STOP: CR_NTP_MIGRATE_MAIN must be 0 or 1" >&2; exit 64 ;;
esac

test "$(hostnamectl --static)" = "ansible01"
test "$(id -un)" = "server01_ansible"
test -n "${ANSIBLE_PRIVATE_KEY_FILE:-}"
test -r "${ANSIBLE_PRIVATE_KEY_FILE}"
mkdir -p "${evidence_root}"
source_head_file="${evidence_root}/SOURCE_HEAD"
source_invalid_file="${evidence_root}/SOURCE_BINDING_INVALID"

read_bound_source() {
  if [[ ! -f "${source_head_file}" || -L "${source_head_file}" ]]; then
    echo "STOP: evidence has no regular SOURCE_HEAD; preserve it and use a new evidence directory" >&2
    return 1
  fi
  bound_source_head="$(cat "${source_head_file}")"
  if [[ ! "${bound_source_head}" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]]; then
    echo "STOP: invalid evidence SOURCE_HEAD" >&2
    return 1
  fi
  if [[ -e "${source_invalid_file}" ]]; then
    echo "STOP: source changed during an earlier execution; preserve this evidence for review" >&2
    return 1
  fi
}

require_clean_source() {
  current_source_head="$(git -C "${repo_root}" rev-parse --verify HEAD)" || return 1
  local tracked_status
  tracked_status="$(git -C "${repo_root}" status --porcelain --untracked-files=no --ignore-submodules=none)" || return 1
  if [[ -n "${tracked_status}" ]]; then
    echo "STOP: tracked source has uncommitted changes" >&2
    return 1
  fi
}

bind_source() {
  require_clean_source || return 1
  if [[ ! -e "${source_head_file}" && ! -L "${source_head_file}" ]]; then
    if [[ -n "$(find "${evidence_root}" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
      echo "STOP: existing evidence has no SOURCE_HEAD; preserve it and use a new evidence directory" >&2
      return 1
    fi
    # Do not replace a marker written by another invocation.
    (set -o noclobber; printf '%s\n' "${current_source_head}" > "${source_head_file}") || return 1
  fi
  read_bound_source || return 1
  if [[ "${current_source_head}" != "${bound_source_head}" ]]; then
    echo "STOP: this evidence directory belongs to another source HEAD; use a new evidence directory" >&2
    return 1
  fi
}

run_playbook() {
  local label="$1"
  shift
  bind_source || return 1
  local log_file run_rc=0
  log_file="$(mktemp "${evidence_root}/${timestamp}_${label}.XXXXXX.txt")"
  {
    printf 'SOURCE_HEAD=%s\n' "${bound_source_head}"
    ansible-playbook -i "${repo_root}/inventory/hosts.yml" "${ntp_mode_args[@]}" "$@"
  } 2>&1 | tee "${log_file}" || run_rc=$?
  if ! require_clean_source || [[ "${current_source_head}" != "${bound_source_head}" ]]; then
    printf 'STOP: source changed during execution; this evidence requires review\n' \
      | tee -a "${log_file}" > "${source_invalid_file}"
    return 1
  fi
  return "${run_rc}"
}

require_change_approval() {
  test "${CR_CHANGE_APPROVED:-}" = "${change_id}"
}

case "${action}" in
  precheck)
    run_playbook "precheck" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-precheck.yml"
    ;;
  source)
    # Must run before `clients` — the client nodes will be refused by
    # control01 (no `allow` yet) until this step has applied.
    require_change_approval
    run_playbook "source_check_diff" --check --diff \
      -e "cr_ntp_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-apply-source.yml"
    run_playbook "source_apply" \
      -e "cr_ntp_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-apply-source.yml"
    run_playbook "source_idempotency" --check --diff \
      -e '{"cr_ntp_require_no_change":true}' \
      -e "cr_ntp_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-apply-source.yml"
    ;;
  clients)
    require_change_approval
    run_playbook "clients_check_diff" --check --diff \
      -e "cr_ntp_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-apply-clients.yml"
    run_playbook "clients_apply" \
      -e "cr_ntp_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-apply-clients.yml"
    run_playbook "clients_idempotency" --check --diff \
      -e '{"cr_ntp_require_no_change":true}' \
      -e "cr_ntp_change_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-apply-clients.yml"
    ;;
  verify)
    run_playbook "verify_all_nodes" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-verify.yml"
    ;;
  rollback)
    require_change_approval
    rollback_host="${2:-}"
    test -n "${rollback_host}"
    run_playbook "rollback_${rollback_host}" \
      -e "cr_ntp_rollback_host=${rollback_host}" \
      -e "cr_ntp_rollback_approved=${change_id}" \
      "${repo_root}/playbooks/cr-p1-ntp-01-01-rollback.yml"
    ;;
  finalize)
    # Finalization may happen from a later checkout; the observed run owns its HEAD.
    read_bound_source
    {
      echo "# ${change_id} Evidence Index"
      echo
      echo "- Generated: ${timestamp}"
      echo "- Repository: 321Team/infra-ansible"
      echo "- Commit: ${bound_source_head}"
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
    echo "usage: $0 {precheck|source|clients|verify|rollback HOST|finalize}" >&2
    exit 64
    ;;
esac
