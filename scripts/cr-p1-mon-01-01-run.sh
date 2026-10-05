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

# Load from this wrapper, not the caller working directory.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib/ansible-engine.sh" || exit 1
fds_engine_init || exit "$?"

run_playbook() {
  local label="$1"
  local target="$2"
  shift 2
  # PID-qualified so two processes invoking the same subcommand within the
  # same wall-clock second (identical $timestamp) never tee to the same
  # path; run_id in the header alone only identifies a log after the fact,
  # it does nothing to stop two processes from colliding on one filename.
  local logfile="${evidence_root}/${timestamp}_$$_${label}.txt"
  local run_sha run_tree input_hash
  run_sha="$(git -C "${repo_root}" rev-parse --verify HEAD)"
  run_tree="clean"
  git -C "${repo_root}" diff --quiet --ignore-submodules HEAD -- || run_tree="dirty"
  input_hash="$(cat "${repo_root}/inventory/hosts.yml" "${repo_root}/inventory/group_vars/all.yml" \
    | sha256sum | cut -d' ' -f1)"
  {
    printf '# run_id=%s_%s commit=%s tree=%s label=%s target=%s input_hash=%s started=%s\n' \
      "${timestamp}" "$$" "${run_sha}" "${run_tree}" "${label}" "${target}" \
      "${input_hash}" "$(date -Iseconds)"
    set +e
    fds_engine_exec ansible-playbook -i "${repo_root}/inventory/hosts.yml" "$@" 2>&1
    rc=$?
    set -e
    printf '# rc=%s finished=%s\n' "${rc}" "$(date -Iseconds)"
    exit "${rc}"
  } | tee "${logfile}"
  last_log_file="${logfile}"
}

# Fails the run unless every non-localhost PLAY RECAP line in the just-
# produced log shows a true no-op (changed=0, unreachable=0, failed=0), AND
# the set of hosts that actually appear in the recap is exactly the set
# inventory says egress_proxy should contain — not a subset, not a superset,
# not a completely different host. ansible-playbook itself exits 0 for a
# successful run that still changed things (or ran against the wrong hosts),
# so this is the only thing that actually enforces "the second apply ran
# against the right target(s) and was a true no-op" rather than leaving it
# to whoever reads the log afterward. Checking every matching line (not just
# the last) matters once there is more than one real target host: a passing
# recap for the last host must not hide a changed>0 recap for an earlier
# one, and the localhost guard play's own recap (always ok=1 changed=0,
# unrelated to the actual target) is excluded so it can't be mistaken for
# real evidence.
assert_idempotent() {
  local logfile="$1"
  local recap_lines expected_hosts actual_hosts
  recap_lines="$(grep -E '^[^[:space:]]+[[:space:]]*: ok=[0-9]+[[:space:]]+changed=[0-9]+[[:space:]]+unreachable=[0-9]+[[:space:]]+failed=[0-9]+' "${logfile}" \
    | grep -v '^localhost[[:space:]]')"
  if [[ -z "${recap_lines}" ]]; then
    echo "IDEMPOTENCY CHECK FAILED: no non-localhost PLAY RECAP line found in ${logfile}" >&2
    exit 1
  fi
  if printf '%s\n' "${recap_lines}" | grep -qvE 'changed=0[[:space:]]+unreachable=0[[:space:]]+failed=0'; then
    echo "IDEMPOTENCY CHECK FAILED: one or more target hosts were not a no-op:" >&2
    printf '%s\n' "${recap_lines}" >&2
    exit 1
  fi
  expected_hosts="$(fds_engine_exec ansible-inventory -i "${repo_root}/inventory/hosts.yml" --graph egress_proxy \
    | sed -n 's/^.*--//p' | grep -vE '^@|:$' | sort)"
  actual_hosts="$(printf '%s\n' "${recap_lines}" | awk '{print $1}' | sort)"
  if [[ "${expected_hosts}" != "${actual_hosts}" ]]; then
    echo "IDEMPOTENCY CHECK FAILED: recap host set does not match the egress_proxy inventory:" >&2
    echo "  expected: $(printf '%s' "${expected_hosts}" | tr '\n' ' ')" >&2
    echo "  actual:   $(printf '%s' "${actual_hosts}" | tr '\n' ' ')" >&2
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
    run_playbook "precheck" "egress_proxy" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-precheck.yml"
    ;;
  apply)
    require_change_approval
    require_clients_confirmed
    run_playbook "apply_check_diff" "egress_proxy" --check --diff \
      -e "cr_mon_change_approved=${change_id}" \
      -e "cr_mon_proxy_clients_confirmed=true" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    run_playbook "apply" "egress_proxy" \
      -e "cr_mon_change_approved=${change_id}" \
      -e "cr_mon_proxy_clients_confirmed=true" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    run_playbook "apply_idempotency" "egress_proxy" \
      -e "cr_mon_change_approved=${change_id}" \
      -e "cr_mon_proxy_clients_confirmed=true" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-apply.yml"
    assert_idempotent "${last_log_file}"
    ;;
  verify)
    run_playbook "verify" "egress_proxy" \
      "${repo_root}/playbooks/cr-p1-mon-01-01-verify.yml"
    ;;
  rollback)
    require_change_approval
    run_playbook "rollback" "egress_proxy" \
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
        header="$(head -n1 "${f}" 2>/dev/null)"
        footer="$(tail -n2 "${f}" 2>/dev/null)"
        run_id="$(printf '%s' "${header}" | grep -oE 'run_id=[^ ]+' | cut -d= -f2- || true)"
        run_commit="$(printf '%s' "${header}" | grep -oE 'commit=[0-9a-f]+' | cut -d= -f2 || true)"
        run_target="$(printf '%s' "${header}" | grep -oE 'target=[^ ]+' | cut -d= -f2 || true)"
        run_rc="$(printf '%s' "${footer}" | grep -oE '^# rc=[0-9-]+' | tail -n1 | cut -d= -f2 || true)"
        meta=""
        [[ -n "${run_id}" ]] && meta="run_id: ${run_id}"
        [[ -n "${run_target}" ]] && meta="${meta}${meta:+, }target: ${run_target}"
        [[ -n "${run_commit}" ]] && meta="${meta}${meta:+, }commit: ${run_commit}"
        [[ -n "${run_rc}" ]] && meta="${meta}${meta:+, }rc: ${run_rc}"
        if [[ -n "${meta}" ]]; then
          echo "- \`${fname}\` (${meta})"
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
