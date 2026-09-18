# CR-P1-NTP-01-01 — Internal single-source NTP (control01)

2026-09-18 draft, unapplied. K8S 6/6 join reported complete by the K8S owner
(하영), but this change has not been reviewed or run yet.

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

Firewall side is already merged in `infra-kubernetes` PR #7
([`01-bootstrap-allow.yaml`](https://github.com/321Team/infra-kubernetes/blob/p1-k8s-01/p1-sec-01-revision/manifests/calico/01-bootstrap-allow.yaml)):
UDP/123 both directions between the 5 client nodes and control01. This CR
only needs chronyd itself to actually listen/request across that path.

## What this CR does NOT do

control01's own upstream (where control01 gets time from) is **out of
scope** here and deliberately left untouched by `roles/ntp_source`. That
value is still `PENDING_REVIEW` per the `infra-kubernetes` PR #7 review
thread ([Deep Review 6276ade](https://github.com/321Team/infra-kubernetes/pull/7#issuecomment-5708114417),
[GWONUK reply](https://github.com/321Team/infra-kubernetes/pull/7)) —
someone proposed `ansible01` as upstream but it was pulled back out for not
having its own Lead Decision. Do not add it to `chrony-source-allow.conf.j2`
until that's separately approved and tracked here.

## Known precheck blocker — verify before running `precheck`

`docs/change/ICR-D-NET-01-01/NTP_DECISION_PROPOSAL.md` (infra-kubernetes,
2026-09-10) recorded that all 6 nodes' `/etc/chrony.conf` used
`pool 2.centos.pool.ntp.org` plus a DHCP-fed `sourcedir /run/chrony-dhcp`.
`roles/ntp_source` only adds a drop-in file under `/etc/chrony.d/`; it does
not edit the main config. If that `pool` line or the DHCP sourcedir is still
present on the client nodes, the role's own precheck assertion
("Stop on unhandled competing sources for client nodes") will fail closed
rather than silently ending up with two active sources. Confirm the current
`/etc/chrony.conf` on all 6 nodes (this may have changed since 2026-09-10)
and, if the pool/DHCP source is still active, get that disablement reviewed
and folded into this CR before `apply`.

## Run order

1. `precheck` — all 6 nodes, read-only. Surfaces the blocker above if it's
   still present.
2. `source` — **control01 only**, adds the `allow` drop-in. Must run before
   step 3: the other 5 nodes will be refused until control01 allows them.
3. `clients` — the other 5 nodes, replaces their active source with
   `server 10.1.93.102 iburst`, one host at a time (`serial: 1`), automatic
   rollback of that host's drop-in on restart/validation failure.
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
by this proposal; this is not evidence of a production apply or an independent
approval of the proposal.

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

## Not covered by this CR / still needed before real apply

- Independent review of `roles/ntp_source` and this doc (same pattern as
  SEC-06/PR #7 — no self-approval).
- Confirming the precheck blocker above against live hosts.
- control01's own upstream, as its own separately tracked/approved item.
- The 60s x 6 continuous-measurement and 5-minute failure/reboot-resync
  criteria are procedural checks to run around `verify`, not something the
  single `chronyc tracking` snapshot in this role's `verify.yml` proves by
  itself — the run wrapper's per-step evidence files give you repeatable
  snapshots but someone still has to space them out and read the reboot
  case manually.
