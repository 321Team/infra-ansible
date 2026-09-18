# Field migration validation — 2026-09-18

**LOCAL validation PASS; production runtime and firewall apply NOT RUN.**
Base PR #24: `63797f3fcb7cfaa3ec8281b2ec6faa32948d84b3`.
Final migration module SHA256:
`bfc9a6587cd5a7314690f25766eac21b3340413155768fc5377e56eb7053e66e`.
The PR description records the resulting full commit HEAD. Earlier PR approvals
do not approve the new implementation, and AI review is not independent human
approval under `docs/REVIEW_POLICY.md`.

| Check | Result | What actually ran |
|---|---|---|
| New migration regression | 68/68 PASS | 49 module/file/parser cases and 19 Ansible role flows |
| Existing role regression | 48/48 PASS | Real Ansible task flow; external host commands and parser mocked |
| Wrapper | 16/16 PASS | Real shell wrapper with fake host identity/Git/playbook commands |
| Egress request | 9/9 PASS | Offline renderer and invalid-input tests; empty production list rejected |
| Independent chrony parser | 14/14 PASS | Locally built chronyd 4.8 `-p`, no daemon or NTP traffic |
| NTP playbook syntax | 5/5 PASS | ansible-core 2.16.19, no managed host contact |
| Targeted regressions | PASS | SELinux snapshot idempotency model; real file apply/rollback contention |

These groups overlap and must not be summed into a count of independent
runtime acceptance criteria. No Actions CI or production NTP test was run.

## Coverage and corrections

The tests use the collected main bytes, SHA256
`147346c1b876b87dfad3bd436c62bc137c36723137ed5b647cf376a9f54e66aa`.
They exercise source and client candidates, original/unsupported layouts,
baseline schema/identity/hash guards, symlink/hardlink/ownership checks,
check mode, immutable baseline retention, idempotency, write failures,
restart/wait/verification failures, invocation recovery and selected-host
manual rollback. They also reject unsupported file xattrs/default ACLs and
invalid public-IP selections. Source rollback remains available without a
current upstream list.

Both files' actual temporary bytes and metadata are checked after failures.
The Ansible flow tests execute the custom module rather than replacing it;
service and chronyc observations are mocked. Public IPs appearing in fixture
data are offline syntax examples, not selected production servers. The test
process does not query them.

Testing found and corrected a real source-verification defect: a Jinja
replacement backreference made a valid three-address list compare unequal
and caused rollback. Positive source selection, incorrect source selection,
offset rejection and recovery were rerun after the correction. Independent
review also found and verified fixes for a new file's SELinux-label comparison
and competing pair apply/rollback writes. File commits now use a nonblocking
state-directory lock; it does not span Ansible restart/verify tasks.

The first ownership tests encountered a container UID namespace that only
permits UID 0. Four ownership scenarios therefore explicitly model lstat's
uid field; this is not a claim that kernel chown isolation was tested. Other
file writes, mode changes, supported ACL/xattr operations and parser calls
use real temporary files. The strengthened ancestor guard correctly rejected
the writable scratch ancestor; final fixtures ran in protected temporary
directories without changing workspace permissions or weakening the guard.

## Reproduction

Use a disposable test environment, not a production controller/host. The
new file-transaction tests require UID 0 in that isolated environment because
the production module deliberately requires root-owned configuration paths.
Provide Python, PyYAML, Jinja2, ansible-core 2.16.19 and a chronyd 4.8 parser
binary. Activate that Ansible virtual environment so `python3` uses the same
installed dependencies; the scratch environment's system Python is insufficient.
Do not bind production configuration/state paths into the test environment.

```bash
python3 tests/ntp_source/test_ntp_source.py --ansible-playbook /path/to/ansible-playbook
python3 tests/ntp_source/test_migration.py --help
python3 tests/ntp_source/test_migration.py \
  --chronyd /path/to/chronyd \
  --ansible-playbook /path/to/ansible-playbook \
  --output /tmp/ntp-migration-validation
python3 tests/ntp_source/test_wrapper.py
python3 -m unittest discover -s tests/ntp_source -p test_egress_contract.py -v
```

The parser was built from the official
[chrony 4.8 source archive](https://chrony-project.org/releases/chrony-4.8.tar.gz),
SHA256 `33ea8eb2a4daeaa506e8fcafd5d6d89027ed6f2f0609645c6f149b560d301706`.
Its build disables NTS, readline/editline, secure hashes, libcap and seccomp.
This tests configuration parsing on the same chrony version; it is not the
target `chrony-4.8-2.el10.x86_64` RPM, a running daemon or an Enforcing host.

## Remaining runtime inputs and limits

The production upstream list is deliberately empty. Three actual service
addresses, compatible leap handling, service-use policy and control01-only
egress must be selected and recorded before source migration. The earlier
no-new-external-egress decision is explicitly identified as a policy delta.
The egress renderer is review data and does not configure a firewall or prove
that other clients' direct Internet traffic is blocked.

Host binary/path/options, SELinux behavior, actual replies and offsets,
60-second samples six times, five-minute loss/recovery and reboot behavior
remain untested. `makestep 1.0 3` is retained, so restart is not guaranteed
step-free. File locking does not authorize concurrent controller workflows,
and the two files are not a power-loss-atomic unit. Preserve the baseline
and coordinate firewall recovery with the original pool/DHCP configuration.
