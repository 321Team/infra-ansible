#!/bin/bash
# Sourced by the two fixed-host entry points. Never change HOME or input modes.
stop() { printf 'STOP: %s\n' "$1" >&2; exit 1; }
check_login() {
  local expected_user=$1 expected_host=$2 expected_home=$3 uid home_mode parent_mode
  uid=$(id -u)
  [[ "$uid" -ge 1000 && $(id -un) == "$expected_user" ]] || stop 'wrong login account; use the original normal login'
  [[ $(hostname -s) == "$expected_host" ]] || stop 'wrong host'
  TASK_LOGIN_HOME=$(getent passwd "$uid" | cut -d: -f6)
  [[ "$TASK_LOGIN_HOME" == "$expected_home" && "${HOME:-}" == "$expected_home" ]] || stop 'home identity mismatch'
  [[ -d /home && ! -L /home && -d "$TASK_LOGIN_HOME" && ! -L "$TASK_LOGIN_HOME" ]] || stop 'linked or missing home'
  [[ $(stat -c %u /home) == 0 && $(stat -c %u "$TASK_LOGIN_HOME") == "$uid" ]] || stop 'home owner mismatch'
  [[ -x "$TASK_LOGIN_HOME" && -w "$TASK_LOGIN_HOME" ]] || stop 'home is not writable/searchable; do not chmod it from this kit'
  home_mode=$(stat -c %a "$TASK_LOGIN_HOME"); parent_mode=$(stat -c %a /home)
  (( (8#$home_mode & 0022) == 0 && (8#$parent_mode & 0022) == 0 )) || stop 'home path is group/world writable'
}
