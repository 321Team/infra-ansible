# P1-K8S-01 kubelet serving TLS — 6-node source and rollout

Status: **Phase 1 source candidate. Runtime execution is separately approved.**

Related:
- `321Team/infra-kubernetes#47`
- `infra-kubernetes#31` — worker03 canary source and independent review
- baseline #10/#14/#17/#19

## 1. Intended state

All six kubeadm nodes retain their existing kubelet authentication/authorization settings and add exactly:

```yaml
serverTLSBootstrap: true
```

The managed local file is `/var/lib/kubelet/config.yaml`.

This repository does **not** enable automatic blanket approval of
`kubernetes.io/kubelet-serving` CSRs. Serving CSR identity, request bytes,
SANs and usages remain a manual security review.

## 2. Safety boundary

The normal `playbooks/site.yml` does not include this change. This prevents an
ordinary OS-baseline rerun from restarting kubelet or creating an unattended
serving CSR.

The rollout is split into four explicit stages:

1. `p1-k8s-01-kubelet-serving-tls-precheck.yml` — read only, all six nodes.
2. `...-apply-one.yml` — config bytes only, exactly one selected node, **no restart**.
3. `...-restart-one.yml` — exactly one selected node, only when the CSR reviewer is ready.
4. `...-verify.yml` — read only, all six nodes after issued certificates exist.

Rollback is `...-rollback-one.yml` and requires the selected node, attempt ID,
rollback approval token and the observed current config SHA-256.

Never delete kubelet PKI files with a wildcard. Never enable anonymous kubelet
access, skip CA verification or grant cluster-admin to make a scrape pass.

## 3. Execution location and prerequisites

Run from ansible01:

```bash
cd /home/server01_ansible/p1-ans-01
source "$HOME/.config/ansible/p1-ans-01.env"
export ANSIBLE_CONFIG=/home/server01_ansible/p1-ans-01/ansible.cfg
INV=/home/server01_ansible/p1-ans-01/inventory/hosts.yml
```

Expected inventory nodes:
`k8s-control01/02/03`, `k8s-worker01/02/03`.

Before each mutation:
- cluster must be 6/6 Ready;
- existing SSH recovery path must work;
- no concurrent kubeadm upgrade/rejoin;
- the CSR reviewer must have control01 admin access before restart;
- preserve command output, RC, target, timestamp and source commit SHA.

## 4. Read-only precheck

```bash
ansible-playbook -i "$INV" playbooks/p1-k8s-01-kubelet-serving-tls-precheck.yml
```

STOP on inventory/hostname mismatch, missing config, duplicate top-level
`serverTLSBootstrap`, a conflicting `--config-dir`/serving-TLS CLI override,
or inactive kubelet.

**Current Phase 1 reconciliation rule:** if a node already has exactly
`serverTLSBootstrap: true`, its serving certificate already validates against
the cluster CA with the expected InternalIP/hostname SANs, and kubelet
authn/authz remains approved, do not re-run apply/restart just to reproduce the
2026-09-26 operation. Record live/source equivalence and use the read-only
verification path. Mutation is only for an actual drifted node.

## 5. Stage one node without restart

Use a unique attempt ID for the change window.

```bash
NODE=k8s-worker01
ATTEMPT=KTLSP1_20260927_01

ansible-playbook -i "$INV" \
  playbooks/p1-k8s-01-kubelet-serving-tls-apply-one.yml \
  -e "p1_kubelet_tls_target=$NODE" \
  -e "p1_kubelet_tls_attempt_id=$ATTEMPT" \
  -e "p1_kubelet_tls_apply_approved=P1-K8S-01-KUBELET-TLS"
```

This stores the exact pre-change config under
`/var/lib/fds-change/P1-K8S-01-KUBELET-TLS/<attempt>/<node>/`, verifies its
SHA-256 and changes only the top-level field. It does not restart kubelet.

## 6. Restart and manually review one serving CSR

Record the pre-existing CSR list first on control01. Then restart the same node
only after a reviewer is ready:

```bash
ansible-playbook -i "$INV" \
  playbooks/p1-k8s-01-kubelet-serving-tls-restart-one.yml \
  -e "p1_kubelet_tls_target=$NODE" \
  -e "p1_kubelet_tls_attempt_id=$ATTEMPT" \
  -e "p1_kubelet_tls_restart_approved=P1-K8S-01-KUBELET-TLS" \
  -e "p1_kubelet_tls_csr_reviewer_ready=true"
```

On control01, identify the **new** Pending CSR for that one node. Do not approve
all Pending CSRs.

Required checks before approval:
- `signerName=kubernetes.io/kubelet-serving`;
- username `system:node:<node>`, group contains `system:nodes`;
- request subject is `CN=system:node:<node>, O=system:nodes`;
- SAN contains the node's measured InternalIP and hostname and no unexpected
  wildcard, URI, e-mail or unrelated address;
- usages contain server auth and only the expected signing/key-encipherment
  usages.

Preserve CSR name, UID, resourceVersion and SHA-256 of decoded `spec.request`.
Immediately before approval, re-read the object and require all four values to
match the reviewed object. `kubectl certificate approve <exact-name>` has no
atomic resourceVersion precondition, so this re-read/approval race limitation
must be recorded in the evidence.

After approval require `Approved,Issued`, validate the issued certificate and
then continue to the next node. Do not stage all six and approve later.

## 7. Verification

After all six are complete:

```bash
ansible-playbook -i "$INV" playbooks/p1-k8s-01-kubelet-serving-tls-verify.yml
```

This verifies:
- one exact `serverTLSBootstrap: true` field;
- kubelet active;
- serving certificate chain against `/etc/kubernetes/pki/ca.crt`;
- InternalIP SAN;
- hostname SAN.

Additionally collect from control01:
- `/api/v1/nodes/<node>/proxy/configz` for all six and confirm
  `anonymous=false`, webhook authentication and Webhook authorization remain;
- Prometheus `kubelet` and `kubelet-cadvisor` targets in two distinct
  post-change scrape rounds;
- 6/6 Node Ready and existing SSH/API/etcd regression paths.

A certificate/file SHA match is integrity evidence, not an AC PASS by itself.

## 8. Rollback

Before rollback, compute the current `/var/lib/kubelet/config.yaml` SHA-256 and
pass it as `p1_kubelet_tls_current_sha256`. If the file changed after the
rollback decision, the playbook stops instead of overwriting unrelated work.

```bash
ansible-playbook -i "$INV" \
  playbooks/p1-k8s-01-kubelet-serving-tls-rollback-one.yml \
  -e "p1_kubelet_tls_target=$NODE" \
  -e "p1_kubelet_tls_attempt_id=$ATTEMPT" \
  -e "p1_kubelet_tls_rollback_approved=P1-K8S-01-KUBELET-TLS" \
  -e "p1_kubelet_tls_current_sha256=<64hex>"
```

Rollback restores the exact preserved config with metadata and restarts only
the selected kubelet. It does not delete serving certificates or CSR objects.

## 9. Completion boundary

Source review/merge is not Runtime completion. Phase 1 completion requires:
- exact-head independent review;
- six-node live/source mapping;
- serving CSR/certificate evidence;
- two Prometheus post-change rounds;
- authn/authz and management-path regression;
- evidence repository preservation.
