# Shared explicit engine selection. Sourcing does not change shell options.
# Unset FDS_ANSIBLE_ENGINE_DIR preserves the caller's existing PATH behavior.
fds_engine_init() {
  fds_engine_dir="${FDS_ANSIBLE_ENGINE_DIR:-}"
  fds_engine_version="${FDS_ANSIBLE_ENGINE_VERSION:-}"
  if [[ -z "$fds_engine_dir" ]]; then
    if [[ -n "$fds_engine_version" ]]; then
      printf 'STOP: engine version requires FDS_ANSIBLE_ENGINE_DIR\n' >&2
      return 64
    fi
    return 0
  fi
  if [[ "$fds_engine_dir" != /* || ! -d "$fds_engine_dir" ||
        "$fds_engine_dir" == *$'\n'* || "$fds_engine_dir" == *$'\r'* ]]; then
    printf 'STOP: engine directory must be an existing absolute path\n' >&2
    return 64
  fi
  case "$fds_engine_version" in
    2.16.19|2.21.3) ;;
    *) printf 'STOP: explicit engine version must be 2.16.19 or 2.21.3\n' >&2; return 64 ;;
  esac
  local cli output first
  for cli in ansible-playbook ansible-inventory ansible ansible-config; do
    if [[ ! -f "$fds_engine_dir/$cli" || ! -x "$fds_engine_dir/$cli" ]]; then
      printf 'STOP: selected engine CLI missing: %s\n' "$cli" >&2
      return 64
    fi
    output=$("$fds_engine_dir/$cli" --version 2>&1) || {
      printf 'STOP: selected engine version query failed: %s\n' "$cli" >&2
      return 64
    }
    first="${output%%$'\n'*}"
    if [[ "$first" != "$cli [core $fds_engine_version]" ]]; then
      printf 'STOP: selected engine version mismatch: %s\n' "$cli" >&2
      return 64
    fi
  done
}

fds_engine_exec() {
  local cli="$1"
  shift
  case "$cli" in
    ansible-playbook|ansible-inventory|ansible|ansible-config) ;;
    *) printf 'STOP: unsupported Ansible CLI\n' >&2; return 64 ;;
  esac
  if [[ -z "$fds_engine_dir" ]]; then
    "$cli" "$@"
  else
    printf 'FDS_ENGINE_EXEC=%s CORE=%s SSH_USETTY=false\n' \
      "$fds_engine_dir/$cli" "$fds_engine_version" >&2
    # Restrict-key-compatible SSH transport; no global PATH or config mutation.
    ANSIBLE_SSH_USETTY=false "$fds_engine_dir/$cli" "$@"
  fi
}
