# P1-HBR-01 AC-04 Harbor 443 Source Allowlist Remediation

## 1. Current decision

AC-04 remains `FAIL_BLOCKER` until Runtime evidence and HBR Lead acceptance are complete.

2026-10-01 read-only discovery confirmed the Harbor HTTPS path:

`PREROUTING DNAT :443 -> 172.18.0.11:8443 -> FORWARD -> DOCKER-USER -> DOCKER-FORWARD -> DOCKER ACCEPT`

The same capture showed firewalld `docker-forwarding` as
`ANY -> docker / target ACCEPT`, and firewalld accepts DNAT traffic before
policy evaluation. Global `StrictForwardPorts=yes` would broaden the change
to every Docker-published port, so it is not selected for this Harbor-only AC.

Selected backend:

- dedicated nftables table: `inet p1_hbr_ac04`;
- base chain: `forward_guard`;
- hook: `forward`;
- priority: `-1`;
- after DNAT, before Docker filter priority 0;
- ingress scope: `ens160`;
- original IPv4 destination: `10.1.93.54`;
- original TCP destination port: `443`;
- approved IPv4 sources continue to later Docker/firewalld evaluation;
- other IPv4 Harbor-443 forwarded traffic is dropped;
- no IPv6 source is approved, so DNAT TCP/443 IPv6 ingress on `ens160` is dropped.

Docker/firewalld-managed tables and chains are not modified.

## 2. Approved source contract

HBR Lead decision in baseline #13:

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

## 3. Safety boundaries

- Never edit Docker-owned `DOCKER`, `DOCKER-FORWARD`, Docker NAT rules.
- Never edit firewalld-owned nft tables directly.
- Do not enable global `StrictForwardPorts` for this change.
- Do not call `firewall-cmd --reload`.
- Do not use TLS verification bypass.
- Code merge is not Runtime approval.
- Configuration verify is not AC-04 acceptance.
- Any prestate drift is a STOP and requires new read-only evidence.
- The two historical DOCKER-USER templates are hard-disabled tombstones and
  are not execution inputs.

## 4. Static and mock validation

Run on ansible01 as `server01_ansible` from the exact PR HEAD.

```bash
cd "$HOME/p1-ans-01"
git fetch origin
git switch --detach <EXACT_PR_HEAD>
git status --short
git rev-parse HEAD

source "$HOME/.config/ansible/p1-ans-01.env"
export ANSIBLE_PRIVATE_KEY_FILE

ansible-inventory -i inventory/hbr.yml --graph

for P in   playbooks/p1-hbr-01-ac04-precheck.yml   playbooks/p1-hbr-01-ac04-forward-discover.yml   playbooks/p1-hbr-01-ac04-apply.yml   playbooks/p1-hbr-01-ac04-verify.yml   playbooks/p1-hbr-01-ac04-rollback.yml
do
  ansible-playbook -i inventory/hbr.yml --syntax-check "$P"
  RC=$?
  echo "SYNTAX_RC=$RC PLAYBOOK=$P"
  if [ "$RC" -ne 0 ]; then
    echo "STOP=SYNTAX_FAILED"
    break
  fi
done

python3 -I -B tools/p1-hbr-01-ac04-contract.py
CONTRACT_RC=$?
echo "CONTRACT_RC=$CONTRACT_RC"
```

Render the nft source locally, without touching harbor01:

```bash
TMP="$(mktemp -d)"

ansible localhost   -c local   -m ansible.builtin.template   -a "src=templates/p1-hbr-01-ac04.nft.j2 dest=$TMP/p1-hbr-ac04.nft mode=0600"   -e @inventory/group_vars/hbr.yml

RENDER_RC=$?
echo "RENDER_RC=$RENDER_RC"

sudo nft -c -f "$TMP/p1-hbr-ac04.nft"
NFT_CHECK_RC=$?
echo "NFT_CHECK_RC=$NFT_CHECK_RC"

cat "$TMP/p1-hbr-ac04.nft"
rm -rf "$TMP"
```

`nft -c` checks syntax/semantics only. It does not apply the ruleset.

Required markers:

- all syntax rc=0;
- `P1_HBR_AC04_STATIC_CONTRACT=PASS`;
- `CONTRACT_RC=0`;
- `RENDER_RC=0`;
- `NFT_CHECK_RC=0`.

## 5. Read-only precheck

After static/mock validation and before any Runtime approval:

```bash
ansible-playbook   -i inventory/hbr.yml   playbooks/p1-hbr-01-ac04-precheck.yml
```

Required marker:

`PRECHECK_PASS_RUNTIME_NOT_CHANGED`

Precheck requires the reviewed baseline to remain unchanged:

- Docker/firewalld active;
- IPv4 forwarding enabled;
- FORWARD begins with DOCKER-USER then DOCKER-FORWARD;
- DOCKER-USER still empty;
- exactly one Docker host-443 DNAT to container 8443;
- custom nft guard absent;
- managed nft file/unit/state absent;
- Docker does not yet require the guard;
- public runtime/permanent generic 443/tcp still present;
- no 443 rich rules.

## 6. Runtime apply prerequisites

Do not run apply until all are true.

1. exact apply HEAD has independent review by HBR Lead 이하영;
2. control01 10.1.93.102 remote-desktop/browser Harbor UI login and required
   management access are confirmed;
3. change window does not overlap P1-HA-01 Drain/rebalance or monitoring
   rollout;
4. STATIC/MOCK and required CI are complete;
5. read-only precheck passes on the same operational baseline.

Apply requires three independent attestations:

```bash
ansible-playbook   -i inventory/hbr.yml   playbooks/p1-hbr-01-ac04-apply.yml   -e hbr_ac04_change_approved=P1-HBR-01-AC04   -e hbr_ac04_ui_fallback_confirmed=P1-HBR-01-AC04   -e hbr_ac04_change_window_confirmed=P1-HBR-01-AC04
```

## 7. Apply sequence

Before mutation, the play preserves under
`/var/lib/fds-change/P1-HBR-01-AC04`:

- original public-zone XML + SHA256 binding;
- iptables filter source;
- iptables NAT source;
- full nft ruleset;
- schema-3 `original-state.json` containing Docker/firewalld/nft baseline and
  approved source contract.

Mutation order:

1. render managed nft source;
2. `nft -c -f` validation;
3. install fail-closed systemd guard unit;
4. enable it as `RequiredBy=docker.service`;
5. start and verify the guard;
6. verify `After=firewalld.service`, `Before=docker.service`, and Docker
   `Requires` the guard;
7. only then remove permanent generic INPUT 443;
8. remove runtime generic INPUT 443;
9. validate firewalld and reverify nft/Docker non-interference.

No INPUT rich rule is added in the final design.

On apply failure, rescue restores generic INPUT 443 first, disables/removes the
guard and fails the play. Preserved prestate remains for reviewed rollback.

## 8. Configuration verify

```bash
ansible-playbook   -i inventory/hbr.yml   playbooks/p1-hbr-01-ac04-verify.yml
```

Required marker:

`CONFIG_PASS_RUNTIME_TRAFFIC_TESTS_PENDING`

Verify checks:

- exact six-member IPv4 set;
- forward hook priority -1;
- approved IPv4 allow rule;
- unapproved IPv4 drop rule;
- IPv6 DNAT TCP/443 drop rule;
- guard enabled/active and required by Docker;
- generic INPUT 443 absent runtime/permanent;
- Docker-owned FORWARD/DOCKER-USER/DOCKER-FORWARD/DOCKER/NAT rules unchanged
  from schema-3 prestate.

## 9. Required Runtime acceptance evidence

Positive:

- Runner 10.250.10.20;
- workers 10.1.93.105/.107/.108;
- edge01 10.1.93.50 while temporary exception remains;
- control01 10.1.93.102 while temporary management exception remains.

Negative:

- ansible01 source 10.250.10.10;
- same-L2 source 10.1.93.26;
- IPv6 published Harbor 443 connection from an unapproved source, if an
  approved IPv6-capable probe path is available.

Regression:

- Worker Harbor pull/Pod start;
- edge01 pull;
- control01 UI/API/push/scan management path;
- guard counters/rules remain exact;
- Docker-managed rules remain unchanged.

Persistence:

- approved maintenance-window Docker restart must not create an unguarded
  publish window;
- guard must remain active and the Docker required dependency must remain
  effective before/after restart;
- post-restart positive/negative probes are required.

## 10. Rollback

```bash
ansible-playbook   -i inventory/hbr.yml   playbooks/p1-hbr-01-ac04-rollback.yml   -e hbr_ac04_rollback_confirmed=P1-HBR-01-AC04
```

Rollback order is outage-safe:

1. restore permanent generic INPUT 443;
2. restore runtime generic INPUT 443;
3. validate firewalld;
4. stop/disable guard;
5. destroy only `inet p1_hbr_ac04`;
6. remove managed unit/nft source;
7. reload systemd metadata;
8. verify Docker/firewalld surface equals captured prestate.

Original evidence is retained.

## 11. Acceptance boundary

Required chain:

`DISCOVERY -> BACKEND_DECISION(NFTABLES_GUARD)
-> STATIC/MOCK -> INDEPENDENT_REVIEW
-> UI_FALLBACK + CHANGE_WINDOW
-> PRECHECK/PRESTATE -> APPLY -> CONFIG_VERIFY
-> POSITIVE/NEGATIVE/PULL/PERSISTENCE REGRESSION
-> EVIDENCE IMPORT/INDEPENDENT REVIEW
-> HBR LEAD AC-04 DECISION`

Until complete:

`AC04=FAIL_BLOCKER / RUNTIME_CHANGE=NOT_PERFORMED`
