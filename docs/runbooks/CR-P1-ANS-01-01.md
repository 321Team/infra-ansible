# CR-P1-ANS-01-01 Execution Runbook

## Safety boundary

- Run only on `ansible01` as `server01_ansible`.
- Use the reviewed CR branch commit, not an unreviewed working tree.
- Keep `P1-DNS-01 R2` evidence unchanged and reference it only.
- Do not change BIND ACL, routing, SNAT, Pod CIDR, or CoreDNS in this runbook.
- Stop after the first failed node. Do not continue to the next batch.

## 1. Prepare the approved source

```bash
cd /home/server01_ansible/p1-ans-01
git fetch origin
if git show-ref --verify --quiet \
  refs/heads/cr-p1-ans-01-01-dns-resolver; then
  git switch cr-p1-ans-01-01-dns-resolver
else
  git switch --track origin/cr-p1-ans-01-01-dns-resolver
fi
git merge --ff-only origin/cr-p1-ans-01-01-dns-resolver
git status --short
git log -1 --format='%H %s'
git merge-base --is-ancestor \
  98cf3f826ac0805bcc771ad760a15d931c1bd414 HEAD
```

Expected: clean working tree and return code `0` from `merge-base`.

## 2. Load local authentication and perform static checks

```bash
source ~/.config/ansible/p1-ans-01.env
chmod 700 scripts/cr-p1-ans-01-01-run.sh

ansible-inventory -i inventory/hosts.yml --graph
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-ans-01-01-precheck.yml
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-ans-01-01-apply-control-plane.yml
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-ans-01-01-apply-workers.yml
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-ans-01-01-verify.yml
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-ans-01-01-rollback.yml \
  -e cr_dns_rollback_host=k8s-control02
```

## 3. Precheck all six nodes

```bash
scripts/cr-p1-ans-01-01-run.sh precheck
```

Required result: all nodes reachable; both direct DNS queries, external name
resolution, API listener, NetworkManager profile detection, and service-state
capture pass. Resolver drift is expected on nodes not yet changed.

## 4. Apply the remaining control-plane batch

```bash
export CR_CHANGE_APPROVED=CR-P1-ANS-01-01
scripts/cr-p1-ans-01-01-run.sh control-plane
unset CR_CHANGE_APPROVED
```

Required result:

- Order: `k8s-control02`, then `k8s-control03`.
- Each first apply reaches the desired state.
- The immediate second run ends with `changed=0`, `failed=0`,
  `unreachable=0` for both hosts.
- Any failure triggers per-node automatic resolver restoration and stops the
  serial batch.

## 5. Apply the worker batch after control-plane approval

```bash
export CR_CHANGE_APPROVED=CR-P1-ANS-01-01
scripts/cr-p1-ans-01-01-run.sh workers
unset CR_CHANGE_APPROVED
```

Required result: worker order is inventory order, all three nodes pass, and the
immediate second run is idempotent.

## 6. Verify all six nodes

```bash
scripts/cr-p1-ans-01-01-run.sh verify
```

Required result: `.52` then `.53`, `search fds.internal`, FQDN and short-name
resolution to `.109`, external resolution, 12 direct DNS queries, API listener,
and no kubelet/containerd state regression all pass.

## 7. Roll back one failed node when required

```bash
export CR_CHANGE_APPROVED=CR-P1-ANS-01-01
scripts/cr-p1-ans-01-01-run.sh rollback k8s-control02
unset CR_CHANGE_APPROVED
```

Replace the example host with exactly one failed Kubernetes node. The rollback
uses the root-owned state captured on the first apply and verifies the restored
NetworkManager values, external resolution, and API listener. Compare internal
name-resolution behavior with that node's precheck because a public pre-change
resolver may not resolve `fds.internal` by design.

## 8. Finalize evidence

```bash
scripts/cr-p1-ans-01-01-run.sh finalize
```

Confirm both files exist and validate successfully:

```bash
test -s docs/evidence/CR-P1-ANS-01-01/EVIDENCE_INDEX.md
sha256sum --check \
  docs/evidence/CR-P1-ANS-01-01/SHA256SUMS
```

Link this CR evidence from the `P1-DNS-01` description. Do not rebuild or
modify the existing `P1-DNS-01 R2` ZIP.
