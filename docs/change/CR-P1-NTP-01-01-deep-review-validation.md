# NTP deployment deep-review follow-up validation

Date: 2026-09-18. Base: `945f3dcbf01e6be6f0d8d8369b826faa4a7f4f72`.
Findings: [PR24 D1-D4 review](https://github.com/321Team/infra-ansible/pull/24#issuecomment-5729182300).

The previous approved PR25 candidate addressed R1-R7. The additional
deployment review reproduced four conditional defects still present in this
base. This follow-up changes those paths; it does not claim a production
incident or transfer the earlier approval to new code.

| Finding | Reproduction | Follow-up behavior |
|---|---|---|
| D1 competing effective sources | Real chronyd 4.6.1 expands a nested sourcedir/pool while all five original main-file guard tasks return rc0 | Parse full effective config and the current managed fragment before mutation; reject client sourcedir and sources outside the fragment, preserving duplicates in comparison |
| D2 unrelated host blocks rollback | An earlier non-target local fixture has an unavailable interpreter; original fact gathering exits rc2 before reaching the selected target | Disable unused fact gathering so non-targets end before remote I/O; selected target restores its baseline with rc0 |
| D3 unsafe state directory | Original Ansible file task follows a symlink and changes its unrelated target from mode0755 to0700; baseline reading accepts the link | Stat the directory without following links before chmod/chown/read; reject symlinks, non-directories and non-root owners; require root/0700 for baseline reading |
| D4 wrong evidence HEAD | Real Git/Bash/checksums with mocked Ansible collect at A then finalize at B; original index labels A logs as B with rc0 | Bind the empty evidence directory to SOURCE_HEAD; reject mixed/dirty source; invalidate observed in-run source changes; finalize against the saved HEAD |

## Completed validation

| Check | Result | Scope |
|---|---|---|
| Integrated role regression | 48/48 PASS | Real Ansible 2.16.19 branching, template, file, restore and rescue; host/NTP/service commands and parser in this suite modelled |
| Existing wrapper regression | 8/8 PASS | Ordering, change approval value, failed-stage propagation, executable mode |
| Playbook syntax | 10/10 PASS | Five NTP playbooks each on Ansible 2.16.19 and 2.21.3 |
| Effective configuration guard | 10/10 PASS | Real chronyd 4.6.1 parser and Ansible; nested dynamic/extra/duplicate/refclock/boot sources rejected, absent and existing managed fragments supported, source upstream untouched, check-mode rejection |
| Original rendered fragments | 2/2 PASS | Exact inventory-derived templates, real chronyd parser |
| Rollback/state directory | 10 expected outcomes confirmed | Three original-defect reproductions plus seven proposal checks; owner-negative stat UID modelled, other directory/link/mode operations real |
| Evidence source binding | 9/9 PASS | Real Git/Bash/sha256sum; host/account/Ansible mocked |

These sets overlap and must not be summed into a count of independent
runtime tests. No managed node, service restart, time adjustment, NTP query,
real SSH outage or DHCP reload was performed. Ansible 2.21.3 runtime tests
remain unverified after the earlier executor LocalRPC startup failure
(rc250); syntax success is not a substitute.

The official chrony 4.6.1 source was built in scratch. Only `chronyd -v`
and `chronyd -p -f` were executed; no daemon was started. Target installed
versions remain to be observed.

Source: https://chrony-project.org/releases/chrony-4.6.1.tar.gz

Source archive SHA256:
`571ff73fbf0ae3097f0604eca2e00b1d8bb2e91affe1a3494785ff21d6199c5c`.

## Source and artifact traceability

The prepared nine-file patch against this base was checked with
`git apply --check`, applied to a clean relevant-source snapshot and compared
to the tested candidate's Git blobs and modes. Its eight code/test files
are unchanged by publication; publication only adds this validation record
and updates the runbook's proposal wording. The wrapper retains mode100755.
The PR description identifies the actual published commit; no synthetic
local snapshot SHA is an operational checkout reference.

Prepared patch: `PR24-Deployment-Hardening-945f3dc.patch`.
Patch SHA256: `3d10c1ec165d13023d3e4ccc079a47389b016d5f4cb9d9a70f92aafe7d3a4b3b`.

Delivered evidence bundle:
`FDS_Ansible_NTP_Deployment_DeepReview_945f3dc_20260918.zip`.
SHA256: `14bce10649ebdf42001cd5a6d6432776b6ab23930ee5c1fc6ede33a090440f61`.
It contains the report, prepared patch, source/apply checks, raw logs and
256 manifest entries. Its GitHub snapshots and patch are historical to that
delivery; use this follow-up PR for the publication state.

Existing repository regression commands:

```bash
python3 tests/ntp_source/test_ntp_source.py --ansible-playbook "$(command -v ansible-playbook)"
python3 tests/ntp_source/test_wrapper.py
```

These commands run the integrated role/wrapper suites, not every separate
targeted experiment in the supplied review bundle. Run them on the tested
engine for comparable results. Do not report a rerun that was not executed.

## Remaining runtime work

Observe all six hosts' actual chrony versions and complete effective config;
resolve competing client sources through reviewed changes. Confirm the
existing decision for control01's own upstream and its current time health,
UDP123 bind/listener, effective client ACL and approved network path.
`chronyc clients` or an active service alone does not prove permission,
response or acceptable offset. Preserve the existing source-before-clients,
serial stop/recovery and 100ms / 60s x6 / five-minute failure/reboot criteria.

The source checks observe before/after state; they do not freeze a checkout
against a concurrent change-and-revert. Use a dedicated checkout and a new
evidence directory for each reviewed source. Preserve legacy unmarked
evidence without inventing SOURCE_HEAD. State-directory checks cover the
declared leaf, not an arbitrary filesystem-ancestor policy.

New code merge requires the existing independent review. Runtime execution
and acceptance remain with the responsible Lead under the current delegation
policy and technical prerequisites; no repeated per-stage Support approval
is added. This record establishes neither CI nor RUNTIME acceptance.
