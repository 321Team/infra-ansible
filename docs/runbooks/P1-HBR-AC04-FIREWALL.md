# P1-HBR-01 AC-04 Harbor 443 Source Allowlist Runbook

## Status and scope

This runbook implements the code-first remediation tracked by
`fds-project-baseline#13` and `infra-ansible#62`.

It changes only harbor01 host-firewall access to TCP/443. It does not change
Harbor credentials, TLS certificates, Docker/Compose configuration, SSH,
Cockpit, Kubernetes manifests, or mgmt-gw policies.

The final source set approved by the HBR Lead is:

- baseline: `10.250.10.20/32`, `10.1.93.105/32`,
  `10.1.93.107/32`, `10.1.93.108/32`
- temporary edge exception: `10.1.93.50/32`
- temporary management exception: `10.1.93.102/32`
- deny / same-L2 negative probe: `10.1.93.26/32`

The two temporary exceptions do not expand the baseline. Their expiry
conditions remain recorded in baseline#13.

## Hard gates before apply

Do not run apply until all are true:

1. The exact PR HEAD has independent review approval.
2. control01 (.102) remote browser can log in to Harbor UI, so blocking .26
   does not remove the only management path.
3. The change window is explicitly scheduled not to overlap Kubernetes Drain,
   node-exporter rollout, candidate push/scan, or other pull-sensitive work.
4. Precheck passes against `harbor01 / 10.1.93.54`.
5. The working tree is the reviewed commit and is clean.

The playbook independently requires three approval variables. Missing any one
fails before the first mutation.

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

Required:

```text
P1-HBR-AC04_FIREWALL_CONTRACT=PASS
APPROVED_SOURCE_COUNT=6
```

All four Ansible syntax checks must return rc0.

## Read-only precheck

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-precheck.yml
```

Required pre-change baseline:

- hostname = harbor01
- inventory address = 10.1.93.54
- firewalld running
- public is the active/default zone on ens160
- generic 443/tcp exists in runtime and permanent config
- no prior `original-state.json`
- deny source .26 is not in the approved source list

If any item differs, stop. Do not normalize the server manually.

## Apply

Run only in the approved window and only after control01 UI fallback has been
confirmed.

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-apply.yml \
  -e p1_hbr_ac04_source_set_approved=P1-HBR-AC04-FW-01 \
  -e p1_hbr_ac04_control01_ui_confirmed=P1-HBR-AC04-FW-01 \
  -e p1_hbr_ac04_change_window_approved=P1-HBR-AC04-FW-01
```

The apply sequence is intentionally fail-safe:

1. capture and hash prestate,
2. add all six permanent rich rules,
3. add all six runtime rich rules,
4. verify every rich rule exists in both states,
5. remove generic 443/tcp from permanent,
6. remove generic 443/tcp from runtime,
7. verify generic 443 is absent and `firewall-cmd --check-config` passes.

It never calls `firewall-cmd --reload`.

Protected server-side state:

```text
/var/lib/p1-hbr-ac04-firewall/
  original-state.json
  runtime-zone-before.txt
  permanent-zone-before.txt
  PRESTATE_SHA256SUMS
  APPLIED.json
```

Do not delete or overwrite this directory during the change cycle.

## Configuration verification

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-verify.yml
```

Required:

- generic 443 absent runtime/permanent
- six source-specific rich rules present runtime/permanent
- .26 not explicitly allowed
- permanent config check passes

This is configuration verification only. It does not prove runtime AC-04.

## Runtime acceptance after apply

Re-run the reviewed AC-04 collector with a new collection ID and preserve the
original pcap/log bytes.

Required matrix:

| Test | Source | Expected |
|---|---|---|
| T1 | cicd-runner01 10.250.10.20 | HTTPS health 200 |
| T2 | worker01 10.1.93.105 | HTTPS health 200 |
| T3 | worker02 10.1.93.107 | HTTPS health 200 |
| T4 | worker03 10.1.93.108 | HTTPS health 200 |
| T5 | ansible01 10.250.10.10 | timeout / Harbor pcap absent |
| T6 | harbor01 | runtime/permanent allowlist exact |
| T7 | edge01 10.1.93.50 | approved temporary positive |
| T8 | control01 10.1.93.102 | approved temporary positive |
| T9 | server05 PC 10.1.93.26 | same-L2 network deny |

Also verify Worker pull, edge01 pull, and monitoring Pod health/regression.
Do not use `-k` or any TLS verification bypass.

AC-04 remains FAIL/BLOCKER until the post-change collection is imported into
the evidence repository and independently reviewed.

## Rollback

Rollback requires a separate explicit token:

```bash
ansible-playbook \
  -i inventory/hosts.yml \
  playbooks/p1-hbr-ac04-firewall-rollback.yml \
  -e p1_hbr_ac04_rollback_approved=P1-HBR-AC04-FW-01
```

Rollback order is intentionally outage-safe:

1. verify sealed prestate hashes,
2. restore original generic 443 runtime/permanent,
3. remove only rich rules this change introduced,
4. verify original rich rules remain,
5. write `ROLLED_BACK.json`.

No reload is used.

After rollback, repeat the minimum Harbor health checks and record that AC-04
has returned to the original noncompliant state. A successful rollback is not
an AC-04 PASS.

## Temporary-exception removal

`.50` removal requires edge01 migration + `robot$fds-ci` cleanup.
`.102` removal requires formal IF-09 Runner push path + completion of residual
candidate push/scan/manual Harbor administration, followed by baseline#13
recording and same-L2 negative retest.

Those removals are separate reviewed changes. Do not silently edit the source
list on a live host.
