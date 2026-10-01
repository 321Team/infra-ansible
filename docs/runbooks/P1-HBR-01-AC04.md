# P1-HBR-01 AC-04 Harbor 443 Source Allowlist Remediation

## Scope and authority

This runbook implements the HBR Lead final source-set decision recorded in
fds-project-baseline#13 comment 5925930576 (2026-10-01 KST).

The change is intentionally limited to harbor01 TCP/443 ingress:

- remove the generic public-zone 443/tcp opening;
- allow only six reviewed IPv4 /32 sources with firewalld rich rules;
- update runtime and permanent state directly without firewalld reload;
- preserve root-owned prestate and a rollback path.

Reviewed source set:

| class | source | purpose |
|---|---|---|
| BASELINE_ALLOW | 10.250.10.20 | cicd-runner01 |
| BASELINE_ALLOW | 10.1.93.105 | k8s-worker01 |
| BASELINE_ALLOW | 10.1.93.107 | k8s-worker02 |
| BASELINE_ALLOW | 10.1.93.108 | k8s-worker03 |
| TEMP_EXCEPTION | 10.1.93.50 | edge01 E-K3S pull |
| TEMP_MANAGEMENT_EXCEPTION | 10.1.93.102 | control01 HBR push/scan/API |

10.1.93.26 is the same-L2 negative target and is not allowed.
127.0.0.1 is host-local and is outside the ingress allowlist.

Temporary exceptions are not baseline expansion.

- .50 expires after edge01 migration and robot$fds-ci cleanup.
- .102 expires after the IF-09 Runner production Push path is active and
  remaining HBR candidate push/scan/manual management work is complete.
- each removal must be recorded in P1-HBR-01 and followed by the same-L2
  negative regression.

This runbook does not change SSH, Cockpit, Harbor credentials, Robot
permissions, certificates, Docker/Podman configuration, or Kubernetes objects.

## Mandatory preconditions

Do not run apply until all conditions are true.

1. The exact code HEAD has independent review by HBR Lead 이하영.
2. Harbor UI login and required management access from control01
   (10.1.93.102) remote desktop/browser have been confirmed. This is the
   explicit prerequisite before 10.1.93.26 is blocked.
3. The change window does not overlap P1-HA-01 Drain/rebalance testing or the
   node-exporter/monitoring image rollout.
4. Run from ansible01 as server01_ansible using the existing approved SSH key.
5. Precheck reports public/ens160, generic runtime and permanent 443/tcp
   present, no existing 443 rich rule, and no https service opening.
6. If /var/lib/fds-change/P1-HBR-01-AC04/original-state.json already exists,
   stop and reconcile the previous change cycle.

## Static checks on ansible01

    cd /home/server01_ansible/p1-ans-01
    git fetch origin
    git switch --track origin/feat/p1-hbr-01-ac04-firewall-allowlist
    git status --short
    git log -1 --format='%H %s'

    source ~/.config/ansible/p1-ans-01.env
    export ANSIBLE_PRIVATE_KEY_FILE

    ansible-inventory -i inventory/hbr.yml --graph

    for P in       playbooks/p1-hbr-01-ac04-precheck.yml       playbooks/p1-hbr-01-ac04-apply.yml       playbooks/p1-hbr-01-ac04-verify.yml       playbooks/p1-hbr-01-ac04-rollback.yml
    do
      ansible-playbook -i inventory/hbr.yml --syntax-check "$P" || exit 1
    done

Expected inventory target: harbor01 only.

## Read-only precheck

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-precheck.yml

Required marker:

    verdict: PRECHECK_PASS_RUNTIME_NOT_CHANGED

Any prestate drift is a STOP. Do not manually change the server to make the
precheck pass.

## Apply

Only inside the approved change window:

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-apply.yml       -e hbr_ac04_change_approved=P1-HBR-01-AC04       -e hbr_ac04_ui_fallback_confirmed=P1-HBR-01-AC04       -e hbr_ac04_change_window_confirmed=P1-HBR-01-AC04

The three explicit values are independent gates. Omitting any gate stops the
play before firewall mutation.

Mutation order:

1. add all permanent source-specific 443 rich rules;
2. add the same runtime rich rules;
3. remove permanent generic 443/tcp;
4. remove runtime generic 443/tcp;
5. validate permanent configuration and re-observe the result.

No firewalld reload is used.

Before the first mutation the playbook saves:

- /var/lib/fds-change/P1-HBR-01-AC04/original-state.json
- /var/lib/fds-change/P1-HBR-01-AC04/original-public.xml

The preserved XML SHA-256 is bound into original-state.json.

If apply fails after mutation starts, a best-effort rescue restores generic
443 first and removes this change's rich rules. The play still fails. Run the
reviewed rollback playbook and verify preserved state before any retry.

## Configuration verify

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-verify.yml

Required result:

- runtime generic 443/tcp absent;
- permanent generic 443/tcp absent;
- runtime 443 rich-rule set equals the six reviewed /32 rules;
- permanent 443 rich-rule set equals the same six rules;
- https service absent;
- effective nftables public allow chain has no unqualified
  tcp dport 443 accept.

This proves configuration only. It is not AC-04 Runtime acceptance.

## Required Runtime regression after apply

Collect one new single-window evidence set after configuration verification.

Positive paths:

- T1 cicd-runner01: route source 10.250.10.20, Harbor 443 succeeds.
- T2 worker01: 10.1.93.105 succeeds.
- T3 worker02: 10.1.93.107 succeeds.
- T4 worker03: 10.1.93.108 succeeds.
- edge01 .50 temporary exception: Harbor pull succeeds.
- control01 .102 temporary management exception: Harbor UI/API and required
  push/scan management path succeed.

Negative paths:

- T5 ansible01 source 10.250.10.10 is denied.
- same-L2 source 10.1.93.26 is denied by harbor01 host firewall.
- packet capture must not show a successful Harbor 443 TCP/TLS session from an
  unapproved source.

Regression checks:

- Worker Harbor pull/Pod start remain healthy.
- edge01 pull remains healthy while the exception is active.
- runtime and permanent firewalld state remain identical after testing.

## Stop and rollback criteria

Rollback if any condition occurs during the approved window:

- an approved source loses required Harbor access;
- .50 or .102 required temporary access fails before expiry;
- .26 can establish a Harbor 443 session;
- unqualified nftables tcp dport 443 accept remains;
- runtime/permanent firewall state diverges;
- Harbor management becomes unavailable through the confirmed .102 fallback;
- apply/verify reports an error whose safety impact cannot be bounded.

Run:

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-rollback.yml       -e hbr_ac04_rollback_confirmed=P1-HBR-01-AC04

Rollback restores generic 443 before removing source-specific rules. It does
not use firewalld reload. It verifies original ports, services and rich rules
were not lost. Original-state files remain for evidence and reconciliation.

## Acceptance boundary

Code merge, precheck PASS, or configuration verify PASS does not make AC-04
PASS.

Required final chain:

REVIEWED_CODE -> APPROVED_CHANGE_WINDOW -> PRESTATE -> APPLY -> CONFIG_VERIFY
-> T1-T5 + .50/.102 positive + .26 same-L2 negative
-> pull/management regression -> evidence import + independent review
-> HBR Lead AC-04 decision

Before apply:
AC04=FAIL_BLOCKER / RUNTIME_CHANGE=NOT_PERFORMED

After successful Runtime evidence but before Lead acceptance:
AC04=FINAL_REVIEW_PENDING
