# CR-P1-MON-01-01 Execution Runbook

## Safety boundary

- Run only on `ansible01` as `server01_ansible`.
- Use the reviewed CR branch commit, not an unreviewed working tree.
- The target host in `inventory/hosts.yml` (`egress_proxy` group) must be
  filled in and reviewed before running `apply`. `precheck` against an empty
  group is a safe no-op; `apply`, `verify`, and `rollback` instead fail
  loudly (`NOT RUN`) against an empty group so an empty-group exit code 0 is
  never mistaken for real evidence.
- Every phase, including `precheck`, first confirms `firewalld` is actually
  running on the target before touching squid — the run fails immediately if
  it is not, rather than after squid has already been installed/configured.
- Do not change Alertmanager's `podSelector`, Secret management, or the
  `monitoring-api` NetworkPolicy in this runbook — that is
  [Issue B (fds-project-baseline#75)](https://github.com/321Team/fds-project-baseline/issues/75).
- Stop after the first failed host. Do not continue to the next batch.

## 1. Prepare the approved source

```bash
cd /home/server01_ansible/p1-ans-01
git fetch origin
git switch --track origin/cr-p1-mon-01-01-egress-proxy
git status --short
git log -1 --format='%H %s'
```

Expected: clean working tree.

## 2. Load local authentication and perform static checks

```bash
source ~/.config/ansible/p1-ans-01.env
chmod 700 scripts/cr-p1-mon-01-01-run.sh

ansible-inventory -i inventory/hosts.yml --graph
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-mon-01-01-precheck.yml
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-mon-01-01-apply.yml
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-mon-01-01-verify.yml
ansible-playbook -i inventory/hosts.yml --syntax-check \
  playbooks/cr-p1-mon-01-01-rollback.yml
```

## 3. Precheck the target host

```bash
scripts/cr-p1-mon-01-01-run.sh precheck
```

Required result: host reachable, squid pre-existing state captured
(`rpm -q squid`, `/etc/squid/squid.conf`, `squid.service`), kubelet state
captured for later regression comparison.

## 4. Apply the egress proxy

```bash
export CR_CHANGE_APPROVED=CR-P1-MON-01-01
export CR_PROXY_CLIENTS_CONFIRMED=CR-P1-MON-01-01
scripts/cr-p1-mon-01-01-run.sh apply
unset CR_CHANGE_APPROVED CR_PROXY_CLIENTS_CONFIRMED
```

`CR_PROXY_CLIENTS_CONFIRMED` is a second, separate attestation from
`CR_CHANGE_APPROVED`: only set it once `cr_mon_proxy_allowed_clients` in
`inventory/group_vars/all.yml` has been verified against a real precheck
measurement of the Alertmanager egress source for the target host, not left
at its STALE DEFAULT. The role refuses to run `apply` without it.

Required result:

- squid is installed, configured with the `discord.com`-only allowlist, and
  active.
- The firewalld rich rule opens `cr_mon_proxy_port` only for
  `cr_mon_proxy_allowed_clients`.
- The runner itself fails the `apply` subcommand if the immediate second
  (idempotency) run's PLAY RECAP is not `changed=0`, `failed=0`,
  `unreachable=0` — this is enforced automatically, not just something to
  eyeball in the log.
- kubelet state on the target host is unchanged from precheck (this role
  must not affect cluster membership if the target is still an active
  k8s_nodes member).

## 5. Verify

```bash
scripts/cr-p1-mon-01-01-run.sh verify
```

Required result: squid loaded+active, an HTTPS request to `discord.com`
through the proxy succeeds, an HTTPS `CONNECT` to `cr_mon_denied_probe_domain`
(`example.com` by default) through the proxy is denied with a `403` at the
CONNECT layer itself (checked via curl's `%{http_connect}` write-out
variable, which captures the proxy's own response to the CONNECT request
and is distinct from `%{http_code}`, the final origin response after a
tunnel is established), and kubelet state has not regressed against the
baseline captured at the first apply.

NOTE: the exact HTTP status Squid returns for a denied `CONNECT` depends on
the installed Squid version and default `deny_info` page. Confirm the actual
denied-probe status code against the real host during the first `verify` run
and adjust `roles/egress_proxy/tasks/verify.yml` if it differs from `403`.

## 6. Roll back when required

```bash
export CR_CHANGE_APPROVED=CR-P1-MON-01-01
scripts/cr-p1-mon-01-01-run.sh rollback
unset CR_CHANGE_APPROVED
```

Uses the root-owned state captured on the first apply
(`{{ cr_mon_state_dir }}/original-state.json` and
`original-squid.conf`). If squid was not present before this change, it is
stopped and disabled. If it was present, its original configuration, file
ownership/mode, and exact pre-change active/enabled state are restored
(a squid that was originally stopped or disabled is left stopped/disabled,
not started); if it was originally active, the restored config is also
explicitly `reload`ed, since re-asserting the `started` state on an
already-running service is a no-op and would otherwise leave the old
config live in the running process. Only the firewalld rich rules this
change actually introduced are removed — rules that already existed in the
baseline captured at the first apply are left untouched — and both the
`--permanent` and the live runtime rule set are updated directly, without
ever calling `firewall-cmd --reload`, so no other rule (ours or anyone
else's) is transiently dropped.

Recovery state is retained after rollback. A later apply with changed inputs
will still be refused: rollback alone does not create a fresh baseline.
After verified restoration, preserve the JSON, original backup and execution
evidence together in an approved archive before beginning a new change cycle.
Do not delete or overwrite a partial baseline or an orphan original backup;
first reconcile it against independent pre-change evidence. A missing original
rule list is not an empty rule list and must stop both apply and rollback.

Rollback invalidates `active-config.sha1` before its first service/configuration
change and leaves it absent. An interrupted rollback therefore cannot leave a
managed-config success marker that suppresses a later reload. The next apply
records the marker only after its own start/reload succeeds. Original firewall
rules must still be present before the play reports `ROLLED_BACK`.

Local recovery regression (in an isolated checkout with no operational keys):

```bash
/PATH/TO/venv/bin/python -B tests/run-egress-recovery.py \
  --ansible-bin /PATH/TO/venv/bin --output /NEW/OUTSIDE/CHECKOUT/egress-results
```

Run separately with pinned 2.16.19 and 2.21.3 environments. This exercises the
real inventory CLI and extracted assert/copy/file tasks on localhost; the
interruption case models the process state. It does not validate Squid,
firewalld, Alertmanager source addresses, or operational rollback acceptance.
Schema version/hash binding, verify input binding, native input typing,
named systemd properties, complete service/config restoration checks and
candidate-vs-live diff remain separate hardening items from this focused
post-merge recovery fix. Code tests do not release the operational HOLD.

## 7. Finalize evidence

```bash
scripts/cr-p1-mon-01-01-run.sh finalize
```

```bash
test -s docs/evidence/CR-P1-MON-01-01/EVIDENCE_INDEX.md
(cd docs/evidence/CR-P1-MON-01-01 && sha256sum --check SHA256SUMS)
```

`SHA256SUMS` records paths relative to the evidence directory itself
(`./20260101T000000+0900_1234_apply.txt`, where `1234` is the runner
process's PID — included so two invocations of the same subcommand within
the same second never write to the same file — ...); running the check
from the repo root instead of `cd`-ing in first resolves those paths
against the wrong directory and fails with "No such file or directory"
even though nothing is actually wrong.

## 8. Hand off to Issue B

Record the proxy's fixed IP and `cr_mon_proxy_port` and pass them to
[Issue B (fds-project-baseline#75)](https://github.com/321Team/fds-project-baseline/issues/75)
for the `monitoring-api` NetworkPolicy `ipBlock`/port. This runbook does not
modify NetworkPolicy or Alertmanager Secrets.
