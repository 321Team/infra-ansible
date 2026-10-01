# P1-HBR-01 AC-04 Harbor 443 Source Allowlist Remediation

## Current decision

AC-04 remains `FAIL_BLOCKER` until reviewed Runtime evidence is complete.

Read-only discovery on 2026-10-01 confirmed:

`PREROUTING DNAT :443 -> 172.18.0.11:8443 -> FORWARD -> DOCKER-USER -> DOCKER-FORWARD -> DOCKER ACCEPT`

The firewalld `docker-forwarding` policy is `ANY -> docker`, priority `-1`,
target `ACCEPT`, with no rich rules. Firewalld also has the default generic
DNAT accept behavior. Therefore the previously rejected INPUT-only design is
not the AC enforcement point.

Selected backend: **DOCKER-USER**.

- Primary enforcement: a dedicated `FDS-HBR-AC04` chain reached from the top
  of `DOCKER-USER`.
- Match scope: ingress `ens160`, TCP, conntrack original destination
  `10.1.93.54:443`.
- Approved IPv4 sources return to Docker's normal forwarding path.
- All other packets in that exact Harbor 443 scope are dropped.
- Docker-owned `DOCKER` and `DOCKER-FORWARD` chains are never modified.
- Persistence: root-owned systemd oneshot service bound to the Docker service
  lifecycle. It reapplies the user chain after boot/Docker restart.
- Supplementary hardening: remove generic firewalld INPUT `443/tcp` and add
  the same six source-specific INPUT rich rules. This is not the primary AC
  enforcement point and no `firewall-cmd --reload` is used.

The current source contract is the HBR Lead decision in baseline #13:

| class | source | purpose |
|---|---|---|
| BASELINE_ALLOW | 10.250.10.20 | cicd-runner01 |
| BASELINE_ALLOW | 10.1.93.105 | k8s-worker01 |
| BASELINE_ALLOW | 10.1.93.107 | k8s-worker02 |
| BASELINE_ALLOW | 10.1.93.108 | k8s-worker03 |
| TEMP_EXCEPTION | 10.1.93.50 | edge01 E-K3S pull |
| TEMP_MANAGEMENT_EXCEPTION | 10.1.93.102 | control01 HBR push/scan/API |
| BLOCK probe | 10.1.93.26 | same-L2 unauthorized source |
| MGMT negative | 10.250.10.10 | ansible01 |

The .50 and .102 entries are temporary exceptions, not baseline expansion.

## Safety boundaries

- Do not directly edit `DOCKER`, `DOCKER-FORWARD`, Docker NAT rules, Harbor
  compose files, certificates, credentials, SSH, or Kubernetes resources.
- Do not use `firewall-cmd --reload`.
- Do not use TLS verification bypass.
- A code merge is not Runtime approval.
- A configuration verify is not AC-04 acceptance.
- If current prestate differs from the reviewed discovery, stop and capture a
  new read-only baseline.

## Static and mock checks on ansible01

Use the exact PR HEAD.

    cd /home/server01_ansible/p1-ans-01
    git fetch origin
    git switch --detach <EXACT_PR_HEAD>
    git status --short
    git rev-parse HEAD

    source ~/.config/ansible/p1-ans-01.env
    export ANSIBLE_PRIVATE_KEY_FILE

    ansible-inventory -i inventory/hbr.yml --graph

    for P in       playbooks/p1-hbr-01-ac04-precheck.yml       playbooks/p1-hbr-01-ac04-forward-discover.yml       playbooks/p1-hbr-01-ac04-apply.yml       playbooks/p1-hbr-01-ac04-verify.yml       playbooks/p1-hbr-01-ac04-rollback.yml
    do
      ansible-playbook -i inventory/hbr.yml --syntax-check "$P" || exit 1
    done

    python3 -I -B tools/p1-hbr-01-ac04-contract.py

Render the user-filter template without touching harbor01:

    TMP="$(mktemp -d)"
    ansible localhost -c local       -m ansible.builtin.template       -a "src=templates/p1-hbr-01-ac04-filter.sh.j2 dest=$TMP/filter.sh mode=0700"       -e @inventory/group_vars/hbr.yml

    bash -n "$TMP/filter.sh"
    grep -nE 'DOCKER-USER|ctorigdst|ctorigdstport|FDS-HBR-AC04' "$TMP/filter.sh"
    rm -rf "$TMP"

Required static markers:

`P1_HBR_AC04_STATIC_CONTRACT=PASS`

and all Ansible syntax checks / `bash -n` return rc0.

## Read-only precheck

After static review, but before any change approval:

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-precheck.yml

Required marker:

`verdict: PRECHECK_PASS_RUNTIME_NOT_CHANGED`

It requires the discovered baseline to still be true, including:

- Docker active, IPv4 forwarding enabled;
- FORWARD begins with `DOCKER-USER` then `DOCKER-FORWARD`;
- DOCKER-USER empty;
- `FDS-HBR-AC04` absent;
- exactly one Docker DNAT for host TCP/443 to container TCP/8443;
- conntrack original-destination matching available;
- managed script/unit/state absent;
- public runtime/permanent generic `443/tcp` present;
- no existing source-specific INPUT 443 rich rules.

Any drift is a STOP.

## Runtime apply prerequisites

Do not run apply until all are true.

1. Exact apply HEAD has independent code review by HBR Lead 이하영.
2. control01 (10.1.93.102) remote desktop/browser Harbor UI login and required
   management access are actually confirmed.
3. Change window does not overlap P1-HA-01 Drain/rebalance or monitoring image
   rollout.
4. Static/mock checks pass.
5. Read-only precheck passes on the same operational baseline.

Apply requires three explicit attestations:

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-apply.yml       -e hbr_ac04_change_approved=P1-HBR-01-AC04       -e hbr_ac04_ui_fallback_confirmed=P1-HBR-01-AC04       -e hbr_ac04_change_window_confirmed=P1-HBR-01-AC04

Before mutation the play preserves a root-owned state record, the permanent
public-zone XML and filter/NAT table sources under:

`/var/lib/fds-change/P1-HBR-01-AC04`

Mutation order:

1. render and shell-validate the managed filter;
2. install/enable/start its Docker-lifecycle systemd service;
3. verify the DOCKER-USER jump and dedicated chain;
4. add permanent/runtime INPUT source rich rules;
5. remove permanent/runtime generic INPUT 443;
6. run `firewall-cmd --check-config`;
7. re-observe and assert the complete configuration.

If a mutation fails, the rescue path restores generic INPUT 443 first, removes
the supplementary rich rules, disables the service, removes the managed
DOCKER-USER rules and fails the play. Preserved prestate is retained.

## Configuration verify

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-verify.yml

Required marker:

`verdict: CONFIG_PASS_RUNTIME_TRAFFIC_TESTS_PENDING`

This verifies configuration/persistence only.

## Required Runtime acceptance evidence

Positive:

- Runner 10.250.10.20;
- Worker01/02/03 10.1.93.105/.107/.108;
- edge01 10.1.93.50 while temporary exception is active;
- control01 10.1.93.102 while temporary management exception is active.

Negative:

- ansible01 source 10.250.10.10;
- same-L2 source 10.1.93.26;
- no successful Harbor TCP/TLS session from an unapproved source.

Regression:

- Worker Harbor pull/Pod start;
- edge01 pull;
- control01 management path;
- DOCKER-USER rule/persistence state remains exact;
- public runtime/permanent INPUT state remains exact.

Also test the persistence contract in an approved maintenance window:

- Docker restart must re-establish exactly one managed DOCKER-USER jump and the
  exact dedicated-chain rules before AC-04 can be considered durable.
- This restart test is a Runtime change and is not implied by code review.

## Rollback

When required:

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-rollback.yml       -e hbr_ac04_rollback_confirmed=P1-HBR-01-AC04

Rollback restores generic INPUT 443 before removing the allowlist, disables the
managed lifecycle service, removes only the managed chain/jump, and checks the
captured pre-change FORWARD/DOCKER-USER/public-zone surface.

The original state directory remains for evidence and reconciliation.

## Acceptance boundary

Required final chain:

`DISCOVERY -> BACKEND_DECISION(DOCKER-USER) -> STATIC/MOCK
-> INDEPENDENT REVIEW -> UI_FALLBACK + CHANGE_WINDOW
-> PRECHECK/PRESTATE -> APPLY -> CONFIG_VERIFY
-> POSITIVE/NEGATIVE/PULL + PERSISTENCE REGRESSION
-> EVIDENCE IMPORT/INDEPENDENT REVIEW -> HBR LEAD AC-04 DECISION`

Until that chain completes:

`AC04=FAIL_BLOCKER / RUNTIME_CHANGE=NOT_PERFORMED`
