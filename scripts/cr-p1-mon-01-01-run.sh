#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

change_id="CR-P1-MON-01-01"
repo_root="$(git rev-parse --show-toplevel)"
evidence_root="${CR_EVIDENCE_DIR:-${repo_root}/docs/evidence/${change_id}}"
action="${1:-}"
timestamp="$(date '+%Y%m%dT%H%M%S%z')"
last_log_file=""

test "$(hostnamectl --static)" = "ansible01"
test "$(id -un)" = "server01_ansible"
test -n "${ANSIBLE_PRIVATE_KEY_FILE:-}"
test -r "${ANSIBLE_PRIVATE_KEY_FILE}"
mkdir -p "${evidence_root}"

run_playbook() {
  local label="$1"
  shift
  local logfile="${evidence_root}/${timestamp}_${label}.txt"
  local run_sha run_tree
  run_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
  run_tree="clean"
  git -C "${repo_root}" diff --quiet --ignore-submodules HEAD -- || run_tree="dirty"
  {
    printf '# commit=%s tree=%s label=%s started=%s\n' \
      "${run_sha}" "${run_tree}" "${label}" "$(date -Iseconds)"
    ansible-playbook -i "${repo_root}/inventory/hosts.yml" "$@" 2>&1
  } | tee "${logfile}"
  last_log_file="${logfile}"
}

# Fails the run unless the just-produced log's PLAY RECAP shows a true no-op
# (changed=0, unreachable=0, failed=0). ansible-playbook itself exits 0 for a
# successful run that still changed things, so this is the only thing that
# actually enforces "the second apply must be a no-op" rather than leaving it
# to whoever reads the log afterward.
assert_idempotent() {
  local logfile="$1"
  local recap
  recap="$(grep -E ' : ok=[0-9]+[[:space:]]+changed=[0-9]+[[:space:]]+unreachable=[0-9]+[[:space:]]+failed=[0-9]+' "${logfile}" | tail -n1)"
  if [[ -z "${recap}" ]]; then
    echo "IDEMPOTENCY CHECK FAILED: no PLAY RECAP line found in ${logfile}" >&2
    exit 1
  fi
  if ! printf '%s\n' "${recap}" | grep -qE 'changed=0[[:space:]]+unreachable=0[[:space:]]+failed=0'; then
    echo "IDEMPOTENCY CHECK FAILED: ${recap}" >&2
    exit 1
  fi
}

require_change_approval() {
  test "${CR_CHANGE_APPROVED:-}" = "${change_id}"
}

require_clients_confirmed() {
  test "${CR_PROXY_CLIENTS_CONFIRMED:-}" = "${change_id}"
}

case "${action}" in
  precheck)
    run_playbook "precheck" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-precheck.yml"
    ;;
  apply)
    require_change_approval
    require_clients_confirmed
    run_playbook "apply_check_diff" --check --diff \
      -e "cr_mon_change_approved=${change_id}" \
      -e "cr_mon_proxy_clients_confirmed=true" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    run_playbook "apply" \
      -e "cr_mon_change_approved=${change_id}" \
      -e "cr_mon_proxy_clients_confirmed=true" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    run_playbook "apply_idempotency" \
      -e "cr_mon_change_approved=${change_id}" \
      -e "cr_mon_proxy_clients_confirmed=true" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    assert_idempotent "${last_log_file}"
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
    {
      echo "# ${change_id} Evidence Index"
      echo
      echo "- Generated: ${timestamp}"
      echo "- Repository: 321Team/infra-ansible"
      echo "- Finalize commit: $(git -C "${repo_root}" rev-parse --verify HEAD)"
      echo
      echo "## Files"
      while IFS= read -r -d '' f; do
        fname="$(basename "${f}")"
        run_commit="$(head -n1 "${f}" 2>/dev/null | grep -oE 'commit=[0-9a-f]+' | cut -d= -f2 || true)"
        if [[ -n "${run_commit}" ]]; then
          echo "- \`${fname}\` (commit: ${run_commit})"
        else
          echo "- \`${fname}\`"
        fi
      done < <(find "${evidence_root}" -maxdepth 1 -type f \
          ! -name EVIDENCE_INDEX.md ! -name SHA256SUMS -print0 | sort -z)
    } > "${evidence_root}/EVIDENCE_INDEX.md"
    (
      cd "${evidence_root}"
      # PID-qualified so two finalize invocations in the same wall-clock
      # second never target the same filename; a shared timestamp name here
      # previously meant the second run's SHA256SUMS listed the first run's
      # already-written integrity report, then truncated that same file via
      # the `>` redirect a moment later, failing its own just-computed hash.
      integrity_report="${timestamp}_$$_integrity_check.txt"
      find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
        | sort -z | xargs -0 sha256sum > SHA256SUMS
      sha256sum --check SHA256SUMS > "${integrity_report}"
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
