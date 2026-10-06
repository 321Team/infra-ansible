# Explicit Ansible engine selection (Phase 1)

Related: Issue #9; preparation PR #70; worker02 evidence in 321Team/fds-project-evidence#113.

The DNS, MON, NTP and Kubernetes Gate0 wrappers accept two opt-in environment variables:

| Variable | Requirement |
| --- | --- |
| `FDS_ANSIBLE_ENGINE_DIR` | Existing absolute directory containing the four Ansible CLI executables |
| `FDS_ANSIBLE_ENGINE_VERSION` | Explicit expected core version: `2.16.19` or `2.21.3` |

Example configuration values (not a deployment instruction):

```text
FDS_ANSIBLE_ENGINE_DIR=/home/server01_ansible/ansible-candidate.8oCqVUwx/result/runtime/venv-2.21.3/bin
FDS_ANSIBLE_ENGINE_VERSION=2.21.3
```

With both variables unset, wrappers retain their existing PATH lookup and SSH PTY configuration. A version without a directory is rejected. An explicit selection validates executable `ansible-playbook`, `ansible-inventory`, `ansible` and `ansible-config`, including each first `--version` line. All four are required even for a wrapper that only invokes playbook. Missing executables, failed version queries and mismatches stop with exit code 64; no fallback occurs.

Selected invocations use the same absolute directory, preserve arguments and command exit codes, and set `ANSIBLE_SSH_USETTY=false` for the invoked process. This avoids the default PTY request that failed with worker02's restricted key. The executable path, expected version and PTY setting are printed on stderr. Global PATH, system RPMs, SSH keys and configuration files are not modified. Existing approval, inventory, source binding, reapply and lock logic remains in the wrappers; the NTP lock's Python selection is unchanged.

The directory is trusted operator input: version checking executes its programs. This is a consistency check, not executable provenance verification or protection against concurrent replacement. Paths may contain spaces. Removing both selection variables returns to prior selection behavior; it does not roll back any remote changes.

## Validation and release boundary

Local command: `python3 -B -m unittest discover -s tests -p test_ansible_engine_selection.py -v` — 13 tests passed. Tests cover all four selected CLIs, argument boundaries, missing/mismatched executables, explicit old-engine selection, unset behavior, failure propagation, four wrapper dispatch paths and existing approval rejection. Wrapper integration uses mocked commands and a mocked NTP lock checker; it does not prove real lock behavior or execute operational Ansible/SSH.

`bash -n` passed for the helper and four wrappers. Reversing only the helper initialization and CLI dispatch substitutions reproduces all four base files byte-for-byte at `5454b77d508cdbfd0eef13e489cbc0322d11c653`.

The implementation has not been installed on ansible01 or run against a managed host. Existing worker02 apply/reapply and synthetic metadata restoration results are historical evidence, not execution of this helper. Required follow-up is code review and CI, then a separately scoped runtime invocation using the reviewed revision and approved host scope. Worker01 remains excluded while under another operator's control. Production key restoration and a global engine switch are not part of this change.
