# P1-K8S-01 kubelet serving TLS — 6-node source and rollout

Status: **Phase 1 source candidate. Runtime execution is separately approved.**

Related:
- 321Team/infra-kubernetes#47
- infra-kubernetes#31 — worker03 canary source and independent review
- infra-ansible#55 — initial six-node source merge
- baseline #10/#14/#17/#19

## 1. Intended state

All six kubeadm nodes retain the approved kubelet authentication/authorization
controls and add exactly:

    serverTLSBootstrap: true

The managed local file is /var/lib/kubelet/config.yaml.

Required security controls remain:
- authentication.anonymous.enabled=false;
- authentication.webhook.enabled=true;
- authentication.x509.clientCAFile=/etc/kubernetes/pki/ca.crt;
- authorization.mode=Webhook;
- no serving-TLS CLI override (--tls-cert-file, --tls-private-key-file,
  --rotate-server-certificates) and no alternate --config-dir;
- effective --config=/var/lib/kubelet/config.yaml.

This repository does **not** enable automatic blanket approval of
kubernetes.io/kubelet-serving CSRs. Serving CSR identity, request bytes, SANs
and usages remain a manual security review.

## 2. Authorization and safety boundary

The normal playbooks/site.yml does not include this change. An ordinary OS
baseline rerun therefore cannot restart kubelet or create an unattended serving
CSR through this rollout.

GitHub review/change records are the authorization source of truth. Variables
such as *_approval_ref, *_confirmed, and *_reviewer_ready are **operator
interlocks and traceability fields only**. They are not secrets, capabilities,
or an authentication mechanism. A playbook invocation is allowed only after the
referenced external approval exists and the operator is authorized to perform
that stage.

Each mutating stage requires a concrete GitHub issue comment or pull-request
review URL (#issuecomment-... or #pullrequestreview-...) plus an explicit
boolean confirmation. The URL is persisted/reported as evidence where
applicable; the playbook does not attempt to authenticate GitHub itself.

The rollout stages are:

1. p1-k8s-01-kubelet-serving-tls-precheck.yml — read only, all six nodes.
2. ...-apply-one.yml — config bytes only, exactly one selected node, **no restart**.
3. ...-restart-one.yml — exactly one selected node; requires a named ready
   reviewer, captures the pre-restart CSR set, restarts one kubelet, then
   requires exactly one new Pending serving CSR for that node.
4. ...-verify.yml — read only, all six nodes after issued certificates exist.

Rollback is ...-rollback-one.yml. It requires a separate external rollback
approval reference, rollback confirmation, restart confirmation, the selected
node/attempt, and the current config SHA-256. It also binds the current config
to that attempt's saved after.sha256 before restoration.

Never delete kubelet PKI files with a wildcard. Never enable anonymous kubelet
access, skip CA verification, or grant cluster-admin to make a scrape pass.

## 3. Execution location and prerequisites

Run from ansible01:

    cd /home/server01_ansible/p1-ans-01
    source "$HOME/.config/ansible/p1-ans-01.env"
    export ANSIBLE_CONFIG=/home/server01_ansible/p1-ans-01/ansible.cfg
    INV=/home/server01_ansible/p1-ans-01/inventory/hosts.yml

Expected inventory nodes:
k8s-control01/02/03, k8s-worker01/02/03.

Before each mutation:
- cluster must be 6/6 Ready;
- existing SSH recovery path must work;
- no concurrent kubeadm upgrade/rejoin;
- the exact external approval URL for that stage must already exist;
- the CSR reviewer must have control01 admin access before restart;
- preserve command output, RC, target, timestamp and source commit SHA.

## 4. Read-only precheck

    ansible-playbook -i "$INV" playbooks/p1-k8s-01-kubelet-serving-tls-precheck.yml

STOP on inventory/hostname mismatch, a missing/stopped kubelet, wrong effective
config path, any serving-TLS CLI override, missing config, authn/authz drift, or
a duplicate top-level serverTLSBootstrap.

Kubelet absence is a structured STOP condition; the CLI check does not emit a
Python traceback or dump the full kubelet argv.

**Current Phase 1 reconciliation rule:** if a node already has exactly
serverTLSBootstrap: true, its serving certificate validates against the cluster
CA with the expected InternalIP/hostname SANs, the effective CLI remains
approved, and authn/authz remains approved, do not re-run apply/restart merely
to reproduce the 2026-09-26 operation. Record live/source equivalence and use
the read-only verification path. Mutation is only for an actual drifted node.

## 5. Stage one node without restart

Use a unique attempt ID and the exact external apply approval record.

    NODE=k8s-worker01
    ATTEMPT=KTLSP1_20260927_01
    APPLY_APPROVAL='https://github.com/321Team/<repo>/issues/<n>#issuecomment-<id>'

    ansible-playbook -i "$INV" \
      playbooks/p1-k8s-01-kubelet-serving-tls-apply-one.yml \
      -e "p1_kubelet_tls_target=$NODE" \
      -e "p1_kubelet_tls_attempt_id=$ATTEMPT" \
      -e "p1_kubelet_tls_apply_approval_ref=$APPLY_APPROVAL" \
      -e "p1_kubelet_tls_apply_confirmed=true"

Immediately before mutation, apply revalidates the effective kubelet CLI and
authn/authz controls. It stores the exact pre-change config under
/var/lib/fds-change/P1-K8S-01-KUBELET-TLS/<attempt>/<node>/, records the
external approval reference, verifies the preserved bytes, changes only the
top-level field, and writes after.sha256. It does not restart kubelet.

## 6. Restart and manually review one serving CSR

Restart is a separate approval boundary. Name the reviewer who is actively
watching the CSR queue.

    RESTART_APPROVAL='https://github.com/321Team/<repo>/issues/<n>#issuecomment-<id>'
    CSR_REVIEWER='<github-login>'

    ansible-playbook -i "$INV" \
      playbooks/p1-k8s-01-kubelet-serving-tls-restart-one.yml \
      -e "p1_kubelet_tls_target=$NODE" \
      -e "p1_kubelet_tls_attempt_id=$ATTEMPT" \
      -e "p1_kubelet_tls_restart_approval_ref=$RESTART_APPROVAL" \
      -e "p1_kubelet_tls_restart_confirmed=true" \
      -e "p1_kubelet_tls_csr_reviewer=$CSR_REVIEWER" \
      -e "p1_kubelet_tls_csr_reviewer_ready=true"

Before restart the playbook:
- revalidates the effective CLI and authn/authz controls;
- requires the current config SHA to match this attempt's after.sha256;
- captures the current CSR names from k8s-control01.

After restart it waits for **exactly one new Pending**
kubernetes.io/kubelet-serving CSR whose username is
system:node:<selected-node>. The playbook does not approve it. It reports the
new CSR name/UID/resourceVersion and hands it to the named reviewer.

The reviewer must then independently verify:
- signerName=kubernetes.io/kubelet-serving;
- username system:node:<node>, group contains system:nodes;
- request subject CN=system:node:<node>, O=system:nodes;
- SAN contains the measured InternalIP and hostname and no unexpected wildcard,
  URI, e-mail or unrelated address;
- usages contain server auth and only the expected signing/key-encipherment
  usages.

Preserve CSR name, UID, resourceVersion and SHA-256 of decoded spec.request.
Immediately before approval, re-read the object and require all reviewed values
to match. kubectl certificate approve <exact-name> has no atomic
resourceVersion precondition, so the re-read/approval race limitation remains
part of the evidence.

Do not approve all Pending CSRs and do not stage all six nodes for later review.

## 7. Verification

After issued certificates exist:

    ansible-playbook -i "$INV" playbooks/p1-k8s-01-kubelet-serving-tls-verify.yml

This verifies on all six nodes:
- the approved effective kubelet config path and absence of TLS CLI overrides;
- anonymous=false, webhook authentication, cluster client CA and Webhook authorization;
- exactly one serverTLSBootstrap: true field;
- kubelet active;
- serving certificate chain against /etc/kubernetes/pki/ca.crt;
- InternalIP SAN;
- hostname SAN.

Additionally collect from control01:
- /api/v1/nodes/<node>/proxy/configz for all six as an independent live
  authn/authz cross-check;
- Prometheus kubelet and kubelet-cadvisor targets in two distinct post-change
  scrape rounds;
- 6/6 Node Ready and existing SSH/API/etcd regression paths.

A certificate/file SHA match is integrity evidence, not an AC PASS by itself.

## 8. Rollback

Rollback is also a separate approval boundary. Compute the current
/var/lib/kubelet/config.yaml SHA-256 immediately before execution.

    ROLLBACK_APPROVAL='https://github.com/321Team/<repo>/issues/<n>#issuecomment-<id>'

    ansible-playbook -i "$INV" \
      playbooks/p1-k8s-01-kubelet-serving-tls-rollback-one.yml \
      -e "p1_kubelet_tls_target=$NODE" \
      -e "p1_kubelet_tls_attempt_id=$ATTEMPT" \
      -e "p1_kubelet_tls_rollback_approval_ref=$ROLLBACK_APPROVAL" \
      -e "p1_kubelet_tls_rollback_confirmed=true" \
      -e "p1_kubelet_tls_rollback_restart_confirmed=true" \
      -e "p1_kubelet_tls_current_sha256=<64hex>"

Before overwriting, rollback requires both:
1. current bytes still match the operator-observed SHA; and
2. current bytes still match this attempt's saved after.sha256.

Any unrelated post-staging config change therefore STOPs rollback instead of
being overwritten. The exact preserved pre-change config and metadata are then
restored and the selected kubelet is restarted only because the separate
restart confirmation was supplied. No serving certificates or CSR objects are
deleted.

## 9. CI and contract coverage

The kubelet serving TLS contract test remains at
tests/kubelet_serving_tls/test_contract.py, and the package now includes
__init__.py so the standard CI command

    python -m unittest discover -s tests -p 'test_*.py'

actually discovers and executes it.

The test parses the Ansible YAML and asserts the actual gate expressions,
include boundaries, staged-SHA rollback binding, authn/authz checks, pending-CSR
observation and mutation/restart boundaries. CI also syntax-checks the remote
playbooks on both pinned Ansible engines.

These are source/localhost checks only. They do not constitute operational
apply, kubelet restart, CSR approval, or six-node Runtime acceptance.

## 10. Completion boundary

Source review/merge is not Runtime completion. Phase 1 completion requires:
- exact-head independent review;
- six-node live/source mapping;
- serving CSR/certificate evidence;
- two Prometheus post-change rounds;
- authn/authz and management-path regression;
- evidence repository preservation.
