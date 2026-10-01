# P1-HBR-01 AC-04 Harbor 443 Source Allowlist Remediation

## Current state

AC-04 remains `FAIL_BLOCKER`.

The first implementation attempt used the firewalld public INPUT surface. That
design is rejected because the actual Harbor HTTPS path is Docker-published:

`PREROUTING DNAT :443 -> 172.18.0.11:8443 -> FORWARD -> DOCKER-USER -> DOCKER-FORWARD -> DOCKER ACCEPT`

Therefore INPUT-only rich rules cannot be treated as the AC enforcement point.

At this HEAD:

- `p1-hbr-01-ac04-apply.yml`: hard HOLD, no mutation.
- `p1-hbr-01-ac04-verify.yml`: hard HOLD, cannot emit false PASS.
- `p1-hbr-01-ac04-rollback.yml`: hard HOLD until paired with the future
  FORWARD-path implementation.
- `p1-hbr-01-ac04-forward-discover.yml`: read-only discovery and the only
  Runtime-safe executable in this change phase.
- `p1-hbr-01-ac04-precheck.yml`: read-only INPUT-surface observation only;
  it is supplemental and is not AC-04 enforcement proof.

No AC-04 firewall Runtime mutation has been performed from this branch.

## Approved source contract

HBR Lead final decision:
fds-project-baseline#13 comment 5925930576.

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

The .50 and .102 exceptions are temporary and do not expand the baseline
allowlist.

## Phase 1 — static/syntax check

Run on ansible01 as server01_ansible from the exact reviewed HEAD:

    cd /home/server01_ansible/p1-ans-01
    git fetch origin
    git switch --track origin/feat/p1-hbr-01-ac04-firewall-allowlist
    git status --short
    git log -1 --format='%H %s'

    source ~/.config/ansible/p1-ans-01.env
    export ANSIBLE_PRIVATE_KEY_FILE

    ansible-inventory -i inventory/hbr.yml --graph

    for P in       playbooks/p1-hbr-01-ac04-precheck.yml       playbooks/p1-hbr-01-ac04-forward-discover.yml       playbooks/p1-hbr-01-ac04-apply.yml       playbooks/p1-hbr-01-ac04-verify.yml       playbooks/p1-hbr-01-ac04-rollback.yml
    do
      ansible-playbook -i inventory/hbr.yml --syntax-check "$P" || exit 1
    done

Expected inventory target: harbor01 only.

Syntax PASS does not release Runtime HOLD.

## Phase 2 — read-only FORWARD discovery

This is the next allowed operational action.

    TS="$(date +%Y%m%dT%H%M%S%z)"
    OUT="$HOME/p1-hbr-ac04-forward-discovery-$TS.log"

    ansible-playbook       -i inventory/hbr.yml       playbooks/p1-hbr-01-ac04-forward-discover.yml       | tee "$OUT"

    RC=${PIPESTATUS[0]}
    echo "ANSIBLE_RC=$RC"
    sha256sum "$OUT"
    echo "OUT=$OUT"

Required end marker:

`verdict: FORWARD_DISCOVERY_CAPTURED_REVIEW_REQUIRED`

The discovery is read-only. It collects:

- firewalld runtime/permanent policy inventory;
- `docker-forwarding` policy details;
- active/public zone state;
- firewalld direct rules;
- IPv4 forwarding state;
- FORWARD / DOCKER-USER / DOCKER-FORWARD / DOCKER filter rules and counters;
- Docker NAT rules;
- Docker published-443 container network/port metadata without environment
  variables or credentials;
- nftables firewalld table;
- complete filter/NAT iptables snapshots.

It does not add/delete/reload firewall rules and does not restart Docker,
Harbor, firewalld or any service.

## Phase 3 — enforcement design decision

After the discovery is reviewed, select exactly one enforcement backend.

Priority:

1. firewalld-native policy/rich-rule enforcement if it can demonstrably act on
   the actual DNAT/FORWARD path with source matching and deterministic
   runtime/permanent persistence;
2. otherwise the Docker-supported user filtering hook `DOCKER-USER`.

Never directly manage Docker-owned `DOCKER` or `DOCKER-FORWARD` chains.

The selected backend must define one contract shared by:

- prestate capture;
- apply;
- verify;
- rollback;
- isolated/static contract tests;
- Runtime positive/negative evidence.

The current hard-HOLD apply/verify/rollback files must be replaced only after
this decision.

## Future apply prerequisites

The future FORWARD-path apply must remain blocked until all are true:

1. exact code HEAD independently reviewed by HBR Lead 이하영;
2. control01 (10.1.93.102) remote desktop/browser can actually log in to Harbor
   UI and perform required management access before .26 is blocked;
3. a change window is confirmed not to overlap P1-HA-01 Drain/rebalance or the
   monitoring node-exporter rollout;
4. exact prestate and rollback contract are captured;
5. STATIC/MOCK and required CI checks are complete for the selected backend.

## Required post-apply Runtime evidence

Positive:

- Runner 10.250.10.20;
- Workers 10.1.93.105/.107/.108;
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
- runtime/persistent enforcement state consistency;
- rollback can restore the exact pre-change state.

## Acceptance boundary

`STATIC=PASS`, discovery completion, code merge, or configuration verification
does not make AC-04 PASS.

Required final chain:

`FORWARD_DISCOVERY -> BACKEND_DECISION -> STATIC/MOCK -> INDEPENDENT_REVIEW
-> UI_FALLBACK + CHANGE_WINDOW -> PRESTATE -> APPLY -> CONFIG_VERIFY
-> POSITIVE/NEGATIVE/PULL REGRESSION -> EVIDENCE IMPORT/INDEPENDENT REVIEW
-> HBR LEAD AC-04 DECISION`
