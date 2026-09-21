# Local paired-migration regression tests

`test_migration.py` uses the actual `fds_ntp_migration` module and a supplied
`chronyd -p` executable. It operates on fresh local fixture files. The observed
main configuration is preserved verbatim in `fixtures/observed-chrony.conf`;
the harness checks SHA256
`147346c1b876b87dfad3bd436c62bc137c36723137ed5b647cf376a9f54e66aa`.

Run with Python containing PyYAML/Jinja2 and ansible-core 2.16.19:

```bash
TEST_OUTPUT=$(mktemp -d /tmp/ntp-migration-tests.XXXXXXXX)
python tests/ntp_source/test_migration.py \
  --ansible-playbook /path/to/ansible-playbook \
  --chronyd /path/to/chronyd \
  --output "$TEST_OUTPUT"
```

The process must already run as uid 0 to exercise production ownership checks
without weakening them. All fixture ancestors must be root-owned and protected;
a sticky `/tmp` ancestor is supported. Do not alter workspace or system directory
permissions to make a test pass. `--suite module`, `--suite flow`, and repeatable
`--case NAME` select focused subsets. A fresh output directory is needed for
each invocation.

The module scenarios check client/source effective candidates, exact-file
include isolation, unknown main drift, file and baseline safety guards,
immutable baselines, invocation snapshots, real partial-write failure recovery,
check/plan non-mutation, public-address validation, and rollback without a
current upstream selection. Configuration bytes, uid/gid, modes, links, and
extended attributes are compared. User xattrs and POSIX default ACLs are real
filesystem fixtures. When a CI user namespace maps only uid 0, non-root ownership
is explicitly simulated in `lstat`; `calls.json` records this limitation.

The flow scenarios run real Ansible role/module/block/rescue and targeted
rollback logic against temporary paths. Only service operations and `chronyc`
observations are replaced with `fixture_action.py`. A non-target connection
sentinel raises on any I/O attempt without opening a network connection.
The source-address fixtures are parser inputs, not an operational NTP selection.

`RESULTS.json`, per-case results, Ansible stdout/stderr, and module-call records
are written into the output directory. A PASS does not establish network
reachability, real service convergence, SELinux behavior, operating-system
rollout acceptance, or successful field rollback. Existing drop-in-only cases
remain in `test_ntp_source.py` and should also be run when the shared role changes.
