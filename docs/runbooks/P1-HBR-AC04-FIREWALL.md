# P1-HBR-01 AC-04 Harbor 443 Source Allowlist Runbook

## Scope

Tracked by `fds-project-baseline#13` and `infra-ansible#62`.

The change restricts Docker-published Harbor TCP/443 without modifying
Docker-managed `DOCKER`, `DOCKER-FORWARD`, `DOCKER-USER` chains and
without changing firewalld `StrictForwardPorts`.

Approved source set:

- baseline: `10.250.10.20/32`, `10.1.93.105/32`,
  `10.1.93.107/32`, `10.1.93.108/32`
- temporary edge exception: `10.1.93.50/32`
- temporary management exception: `10.1.93.102/32`
- deny / same-L2 negative probe: `10.1.93.26/32`

## Why the enforcement is not an INPUT rich rule

harbor01 publishes nginx as host `:443 -> 172.18.0.11:8443`. The observed
packet path is:

```text
PREROUTING DNAT
  -> FORWARD
  -> DOCKER-USER
  -> DOCKER-FORWARD
  -> DOCKER
  -> container 8443
```

firewalld currently has `StrictForwardPorts=no`, so its FORWARD chain
generically accepts DNAT traffic before firewalld policies. Restricting only
the public INPUT chain would not enforce the AC on Docker-published traffic.

The remediation therefore installs a dedicated nftables table with a forward
base chain at priority `-1`: after DNAT has established conntrack original
destination metadata, but before Docker's filter priority `0`.

Only traffic that is all of the following is evaluated by the IPv4 allowlist:

- ingress interface `ens160`
- DNAT connection
- original destination `10.1.93.54`
- original TCP destination port `443`

Approved IPv4 sources continue to Docker's own filtering. All other matching
IPv4 traffic is dropped. No IPv6 source is approved, so forwarded DNAT TCP/443
IPv6 traffic arriving on ens160 is dropped.

## Persistence

Files installed by the change:

```text
/etc/nftables/p1-hbr-ac04.nft
/etc/systemd/system/p1-hbr-ac04-firewall.service
```

The service is enabled at boot, ordered after firewalld and before Docker.
The custom nft table remains independent of Docker daemon restarts and does
not modify firewalld's owned nft table.

## Hard gates before apply

All must be true:

1. exact PR HEAD independently approved;
2. Harbor UI **login succeeds** from control01 (.102), not just page display;
3. change window approved and not overlapping Drain, image rollout, push/scan,
   or pull-sensitive work;
4. read-only precheck PASS;
5. reviewed commit checked out with clean working tree.

The playbook requires three explicit approval variables and fails before
mutation if any is absent.

## Static validation on ansible01

```bash
cd /home/server01_ansible/p1-ans-01
git fetch origin
git switch --track origin/fix/p1-hbr-ac04-firewall-allowlist
git status --short
git log -1 --format='%H %s'

python3 tests/test_p1_hbr_ac04_firewall_contract.py

ansible-inventory -i inventory/hosts.yml --graph

for P in \
  playbooks/p1-hbr-ac04-firewall-precheck.yml \
  playbooks/p1-hbr-ac04-firewall-apply.yml \
  playbooks/p1-hbr-ac04-firewall-verify.yml \
  playbooks/p1-hbr-ac04-firewall-rollback.yml
do
    ansible-playbook -i inventory/hosts.yml --syntax-check "$P"
done
```

Required contract output:

```text
P1-HBR-AC04_FIREWALL_CONTRACT=PASS
APPROVED_SOURCE_COUNT=6
ENFORCEMENT=NFT_FORWARD_PRIORITY_MINUS_1
DENY_PROBE=10.1.93.26/32
```

## Read-only precheck

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-precheck.yml
```

Required baseline:

- harbor01 / 10.1.93.54 identity exact;
- firewalld running, public/ens160;
- `StrictForwardPorts=no`;
- Docker FORWARD enters DOCKER-USER before DOCKER-FORWARD;
- Docker TCP/443 DNAT exists;
- generic public 443 exists runtime/permanent;
- managed nft table/config/unit do not already exist;
- candidate nft file passes `nft -c`.

Any mismatch is STOP. Do not normalize the server manually.

## Apply

Only in the approved window:

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-apply.yml \
  -e p1_hbr_ac04_source_set_approved=P1-HBR-AC04-FW-01 \
  -e p1_hbr_ac04_control01_ui_confirmed=P1-HBR-AC04-FW-01 \
  -e p1_hbr_ac04_change_window_approved=P1-HBR-AC04-FW-01
```

Sequence:

1. seal firewalld + Docker prestate and SHA256;
2. install nft guard file and systemd unit;
3. `nft -c` validate;
4. enable/start guard;
5. verify active table/source set/drop rule;
6. remove public generic 443 permanent;
7. remove public generic 443 runtime, with no reload;
8. validate firewalld config;
9. mark `APPLY_PASS_RETEST_REQUIRED`.

Protected state:

```text
/var/lib/p1-hbr-ac04-firewall/
  original-state.json
  firewalld-runtime-before.txt
  firewalld-permanent-before.txt
  iptables-before.txt
  ip6tables-before.txt
  PRESTATE_SHA256SUMS
  APPLIED.json
```

## Configuration verify

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-verify.yml
```

Required:

- generic public 443 absent runtime/permanent;
- managed nft service enabled + active;
- forward guard present at priority -1;
- all six approved IPv4 addresses in the nft set;
- deny rule present;
- `StrictForwardPorts=no` unchanged;
- firewalld config valid.

This is CONFIG verification, not Runtime AC acceptance.

## Runtime acceptance

Use a new reviewed collector run. Preserve original pcap/log bytes and hashes.

| Test | Source | Expected |
|---|---|---|
| T1 | Runner 10.250.10.20 | HTTPS health 200 |
| T2 | worker01 10.1.93.105 | 200 |
| T3 | worker02 10.1.93.107 | 200 |
| T4 | worker03 10.1.93.108 | 200 |
| T5 | ansible01 10.250.10.10 | blocked; Harbor SYN absent |
| T6 | harbor01 | guard + firewalld state exact |
| T7 | edge01 10.1.93.50 | positive + pull regression PASS |
| T8 | control01 10.1.93.102 | positive + HBR admin path PASS |
| T9 | server05 PC 10.1.93.26 | same-L2 443 blocked |

Also verify Worker pull, edge01 pull and monitoring status. TLS verification
must remain enabled; do not use `-k` or equivalent bypasses.

AC-04 remains FAIL/BLOCKER until the post-change collection is imported into
the evidence repository and independently reviewed.

## Rollback

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-rollback.yml \
  -e p1_hbr_ac04_rollback_approved=P1-HBR-AC04-FW-01
```

Rollback order:

1. verify sealed prestate;
2. restore generic 443 permanent/runtime first;
3. stop and disable the managed nft service;
4. remove only this change's nft/unit files;
5. verify custom table absent and original broad 443 restored;
6. retain evidence state with `ROLLED_BACK.json`.

A successful rollback restores the original **noncompliant** state. It is not
an AC-04 PASS.

## Temporary exception expiry

`.50`: remove after edge01 migration + `robot$fds-ci` cleanup.

`.102`: remove after formal IF-09 Runner push path and completion of residual
candidate push/scan/manual administration, then record the removal in
baseline#13 and repeat same-L2 negative testing.

Both removals require separate reviewed changes.
