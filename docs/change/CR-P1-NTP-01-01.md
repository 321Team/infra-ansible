# CR-P1-NTP-01-01 — Internal single-source NTP (control01)

Current correction (2026-09-19 KST): PR #28 was approved on exact HEAD
`f7940d7fd29850e45f4197ea7ab97d74b35021aa` and merged into this working
branch as `a51a7de0e7e7cebaa46bef318ab46808ceb2b835`. The next code change
supports two or three upstreams and rejects providers unsupported by the
iburst workflow; it requires its own review. See the [field runbook](CR-P1-NTP-01-01-field-runbook.md)
and [correction validation](CR-P1-NTP-01-01-two-source-validation.md).
Production apply remains NOT RUN. The following dated records retain their
original scope.

2026-09-18 status: the observed-layout migration in PR #27 was approved on
exact HEAD `52e9a7450aca411e44be221b99840aeb372bacb3` and merged into the
PR #24 working branch as `e5446288c1c646f41c9ec9c890bf85e7509503ec`.
Production apply remains NOT RUN. The field receipt at 21:14:44–21:15:00 KST
identified the original layout blocker on all six nodes (changed=0).
See [field migration](CR-P1-NTP-01-01-field-migration.md) for the paired fix and
[the persistent single-entry instructions](CR-P1-NTP-01-01-rollout.md) for
diagnosis, conditional apply, verification and evidence collection. The new
execution code needs its own exact-HEAD review; PR #27's approval does not
automatically approve it. Missing endpoint/network inputs still stop apply.
The 2026-09-19 KST [upstream selection and correction contract](CR-P1-NTP-01-01-upstream-selection.md)
records the initial three-provider candidates and the unresolved NIST request-rate contract.
The [network/recovery contract](CR-P1-NTP-01-01-network-recovery.md) defines the
scoped egress amendment and field evidence. These are planning records;
runtime inputs remain unpopulated and no provider compatibility PASS is claimed.
K8S 6/6 join was reported complete by the K8S owner (하영); this document
update does not independently verify the current cluster or deploy NTP.
The R1–R7 remediation in [PR #25](https://github.com/321Team/infra-ansible/pull/25)
was [approved by hayeounglee](https://github.com/321Team/infra-ansible/pull/25#pullrequestreview-5246933227)
at 19:46:01 KST on exact HEAD `ca987b8a879418173a50d0cf7753063ebbb4a201`
and merged into this PR's candidate branch at 20:01:28 KST as
`73da49bf1f35c5891a59390b87df0e4d2a7dc3a4`. Both commits have tree
`f9475d664286e43e3bda1262aad83020b53407dc`. This is not a main merge or
runtime apply. The original review and later remediation remain separate records.

## Decision basis

Lead Decision, [fds-project-baseline#10](https://github.com/321Team/fds-project-baseline/issues/10#issuecomment-5697547621)
(2026-09-16): `NTP_SINGLE_SOURCE_CONFIRMED(control01) / RELAY_REJECTED_OUT_OF_SCOPE`.

| Input | Value |
|---|---|
| NTP source | `k8s-control01` (10.1.93.102), single internal source |
| Path | Internal UDP/123 only, no new external egress |
| Offset AC | <=100ms |
| Measurement | 60s interval x 6 |
| Failure | sync lost >=5min -> FAIL |
| Reboot | resync within 5min |

The dns01/dns02 relay proposal ([fds-project-baseline#14](https://github.com/321Team/fds-project-baseline/issues/14#issuecomment-5697384866))
was rejected — out of Baseline AC scope, not on technical grounds.

**Firewall prerequisite correction (2026-09-18):** the earlier claim that
`infra-kubernetes` PR #7 was already merged was incorrect. The deployment
review observed [PR #7](https://github.com/321Team/infra-kubernetes/pull/7)
as Open / merged=false at HEAD `7a840cf013be61e5891c4848f8732d4358208423`.
A proposed manifest, or a code merge alone, does not prove an active UDP/123
path. Before this CR's runtime apply, establish the current effective
firewalld/HEP policy and the approved client-to-control01 UDP/123 path.
Do not require the whole SEC PR rollout as a new blanket prerequisite:
use the actual approved host-protection state. This CR manages chronyd
only and does not apply HEP/GNP or modify firewall rules.

## Original scope and later upstream proposal

In the original drop-in-only mode, control01's own upstream (where control01
gets time from) was **out of scope** and remains untouched. That
value is still `PENDING_REVIEW` per the `infra-kubernetes` PR #7 review
thread ([Deep Review 6276ade](https://github.com/321Team/infra-kubernetes/pull/7#issuecomment-5708114417),
[GWONUK reply](https://github.com/321Team/infra-kubernetes/pull/7)) —
someone proposed `ansible01` as upstream but it was pulled back out for not
having its own Lead Decision. Do not add it to `chrony-source-allow.conf.j2`
until that's separately approved and tracked here.

The user's later request adopts the Kubernetes owner's proposal for review:
control01 alone uses a fixed set of public NTP endpoints. The new opt-in
migration supports two or three explicit supported public IPv4 addresses and removes
the original pool/DHCP source on control01 as well as the clients. This is a
proposed amendment to the earlier **no new external egress** decision, not
evidence that the older decision already allowed it. The address list is
empty by default and source migration fails closed until it is populated.
See the [migration contract](CR-P1-NTP-01-01-field-migration.md) and
[egress review](CR-P1-NTP-01-01-egress-review.md).

## Known precheck blocker — verify before running `precheck`

`docs/change/ICR-D-NET-01-01/NTP_DECISION_PROPOSAL.md` (infra-kubernetes,
2026-09-10) recorded that all 6 nodes' `/etc/chrony.conf` used
`pool 2.centos.pool.ntp.org` plus a DHCP-fed `sourcedir /run/chrony-dhcp`.
The default, drop-in-only mode only adds a file under `/etc/chrony.d/`; it
does not edit the main config. If that `pool` line or the DHCP sourcedir is still
present on the client nodes, the role's own precheck assertion
("Stop on unhandled competing sources for client nodes") will fail closed
rather than silently ending up with two active sources. Confirm the current
`/etc/chrony.conf` on all 6 nodes (this may have changed since 2026-09-10)
and, if the pool/DHCP source is still active, get that disablement reviewed
and folded into this CR before `apply`. The 2026-09-18 field receipt now
confirms both directives and the missing include on all six hosts. Do not
remove them manually to pass this guard. The candidate paired migration
preserves and recovers main plus drop-in together.

## Run order

For the observed main-file layout, use the single-entry workflow linked above.
The following individual actions document the legacy interface and remain
available for scoped diagnosis/recovery in an approved runtime window.
They default to the existing drop-in-only mode. For the newly observed
layout, use the explicitly selected migration procedure linked above after
review and resolution of the recorded upstream/path prerequisites.

1. `precheck` — all 6 nodes, read-only. Surfaces the blocker above if it's
   still present.
2. `source` — **control01 only**, adds the `allow` drop-in. Must run before
   step 3: the other 5 nodes will be refused until control01 allows them.
3. `clients` — the other 5 nodes, replaces their active source with
   `server 10.1.93.102 iburst`, one host at a time (`serial: 1`), automatic
  rollback of that host's managed configuration on restart/validation failure
  (drop-in only in the default mode; the pair in migration mode).
4. `verify` — all 6 nodes. Asserts Leap=Normal, current system correction
   and last offset <=100ms, and exactly
   one configured/selected source (control01) on each client.

```bash
./scripts/cr-p1-ntp-01-01-run.sh precheck
CR_CHANGE_APPROVED=CR-P1-NTP-01-01 ./scripts/cr-p1-ntp-01-01-run.sh source
CR_CHANGE_APPROVED=CR-P1-NTP-01-01 ./scripts/cr-p1-ntp-01-01-run.sh clients
./scripts/cr-p1-ntp-01-01-run.sh verify
./scripts/cr-p1-ntp-01-01-run.sh finalize
```

Rollback one node: `CR_CHANGE_APPROVED=CR-P1-NTP-01-01 ./scripts/cr-p1-ntp-01-01-run.sh rollback k8s-worker02`.

## PR #24 review remediation

The seven findings on `e9b628af2923d2dc1346923295fa8361f752b8f9` are addressed
by the integrated PR #25 remediation. Its independent approval is linked
above; neither the code review nor its branch merge proves a production apply.

| Review finding | Code change | Regression coverage |
|---|---|---|
| R1 backup expression fails at runtime | One valid Jinja dictionary, JSON serialization after capture | Real copy/slurp for absent and existing drop-ins |
| R2 invalid include detection | Active `confdir DIR` or `include DIR/*.conf`, bound to the managed directory; comments excluded | Both layouts, case/space, four comment forms, competing directives |
| R3 check-mode checks unapplied runtime | Template predicts diff in check mode; runtime validation only after real apply | Drift dry-run leaves files, baseline and service unchanged |
| R4 restart races synchronisation | `chronyc waitsync 30 0.1 0 10` (at 100ms AC), task timeout 300s, then strict verify | Modelled delayed convergence, exhausted wait, restart and restore failures |
| R5 current correction omitted | Parse System time and Last offset, reject malformed/missing/duplicate/non-finite values; both <=100ms | Boundary, 500ms correction, malformed values, wrong/multiple sources |
| R6 rerun always changes | Stable templates; second wrapper pass is check/diff plus explicit zero-change assertion | Second real apply changed=0, drift rejected by idempotency check |
| R7 wrapper not executable | Git executable bit 100755 | Shell syntax and mode check |

The source-row parser also excludes chronyc's `====` separator, includes
unresolved sources via `sources -a`, and escapes the expected IP before
comparison. A passing include check is deliberately
limited to the two supported main-config layouts; nested/multiple-directory
layouts need review, and the main config is never rewritten by this role.
Active client `server`, `pool`, `peer`, and `sourcedir` directives are blockers.

Automatic rescue restores the **current invocation's** drop-in snapshot,
including uid/gid/mode, only when that invocation changed the drop-in.
An unchanged apply that fails runtime verification stops without rolling back
an earlier successful change. Explicit manual CR rollback uses the immutable
`original-ntp-dropin.json` baseline. Both paths validate schema, CR, host,
role and destination before restoring. Existing legacy/mismatched baselines
are preserved and rejected; do not delete/recreate one to bypass validation.
Symlink and multiply linked drop-ins are rejected. A failed restore stops
the batch and requires operator recovery; service-active after restoration
alone does not prove NTP convergence or AC acceptance.

Local regression command (in an environment with ansible-core and PyYAML):

```bash
python3 tests/ntp_source/test_ntp_source.py --ansible-playbook "$(command -v ansible-playbook)"
python3 tests/ntp_source/test_wrapper.py
```

The fixture executes real Ansible control flow and temporary-file modules.
Host commands, service changes, and the chronyd parser are modelled. It is
LOCAL/MOCK coverage, not CI or RUNTIME acceptance. Validate installed chrony
configuration parsing, real convergence latency, SELinux/permissions, and
UDP/123 reachability on the approved target stage. The bounded apply wait
does not establish the separate reboot or 60s x 6 continuous-measurement AC.
The local validation record is [review-fix-validation](CR-P1-NTP-01-01-review-fix-validation.md).

## Deployment deep-review follow-up (review candidate)

The deployment review of candidate `ca987b8a879418173a50d0cf7753063ebbb4a201`
found four additional gaps, still present in base
`945f3dcbf01e6be6f0d8d8369b826faa4a7f4f72`. This follow-up candidate does not
change the earlier approval record or establish runtime acceptance.
See [targeted validation and limitations](CR-P1-NTP-01-01-deep-review-validation.md).

- Before mutation, parse the entire effective chrony config and the existing
  managed fragment. Clients reject dynamic sourcedir entries and time sources
  outside the fragment, including nested include/confdir entries. A managed
  old source remains replaceable. This default mode does not rewrite the
  main config. The later opt-in field migration changes only the observed
  main layout and preserves the source-node upstream directives.
- Manual rollback selects the requested host before fact gathering or other
  remote operations, so another node's failure cannot block that recovery.
- Validate the rollback directory itself before chmod/chown or baseline read;
  reject symlinks and another owner's directory. Baseline reads require 0700.
- Capture SOURCE_HEAD when starting evidence, reject mixed-source appends and
  dirty tracked files, and keep that recorded HEAD when finalizing from a
  later checkout. Source changes observed during a run invalidate its binding.

Use a dedicated checkout without concurrent edits and a fresh evidence
directory for this candidate. For example, set the following once in the
controller shell before the existing run order, then retain that path for
all actions from the same source:

```bash
umask 077
export CR_EVIDENCE_DIR="$(mktemp -d "$HOME/CR-P1-NTP-01-01-evidence.XXXXXXXX")"
```

Existing evidence without SOURCE_HEAD is preserved and rejected for reuse;
do not add a guessed marker or delete old logs to bypass the guard. A new
source uses a new directory. The wrapper checks tracked changes; it does not
freeze the checkout or authenticate human approval. Runtime still uses the
reviewed source/engine and existing execution decision.

Before real apply, collect the six nodes' installed chrony versions and full
effective configs. Confirm control01's approved current upstream and health,
server socket/bind/ACL, then validate the approved five-client NTP path after
source configuration. A service-active or UDP socket observation alone is
not an NTP response/offset test. Keep the existing 60s x 6 and 5-minute
loss/reboot criteria as separate runtime acceptance checks.

## Not covered by this CR / still needed before real apply

- Confirm the integrated PR #24 disposition and merge scope. PR #25's
  independent approval is already recorded; do not request it again for
  unchanged code. Runtime decisions follow the current
  [Lead delegation policy](https://github.com/321Team/fds-project-baseline/blob/main/governance/REVIEW_AUTHORITY_POLICY.md),
  while code-change merge review remains required.
- Review and merge the paired migration for the blocker now confirmed by
  the 2026-09-18 field receipt; obtain a fresh read-only check before runtime.
- control01's own upstream, as its own separately tracked/approved item.
- The 60s x 6 continuous-measurement and 5-minute failure/reboot-resync
  criteria are procedural checks to run around `verify`, not something the
  single `chronyc tracking` snapshot in this role's `verify.yml` proves by
  itself — the run wrapper's per-step evidence files give you repeatable
  snapshots but someone still has to space them out and read the reboot
  case manually.
