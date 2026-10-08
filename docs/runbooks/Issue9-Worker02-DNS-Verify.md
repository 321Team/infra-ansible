# Issue9: worker02-only DNS verify preparation

CODEX_ASSISTED. Related: [Issue9](https://github.com/321Team/infra-ansible/issues/9),
source PR71 engine selection, evidence PR148 controller CLI/syntax and PR150 MON
verify. Those results do not establish DNS Runtime success.

## Scope and entry point

`scripts/cr-p1-ans-01-01-run.sh verify-worker02` selects a dedicated playbook.
Existing `verify` still targets all Kubernetes nodes and must **not** be used as
a fallback in the worker02 window. The new action never dispatches precheck,
apply, rollback, NTP or Gate0. Engine selection and existing controller/account/key
checks are unchanged. There is no generic host-pattern input.

Before managed-host facts or role execution, a fatal localhost guard checks that
the inventory pattern selects exactly `k8s-worker02`, in both `k8s_workers` and
`k8s_nodes`, at `10.1.93.107` using `svc_ansible`. An absent host, group-name
collision that expands selection, or changed address/account stops execution.
Any inventory group named `k8s-worker02` is also rejected, even when the engine
currently gives the host precedence. The guard is not proof of endpoint identity: reviewed inventory, known_hosts and
the approved key remain prerequisites. Do not bypass it with direct playbook
`--limit`, tags or extra variables. Use the wrapper entry point.

The existing DNS role runs with `cr_dns_phase: verify`: reads resolver and service
state, queries the two approved DNS servers, resolves internal/external names,
and probes the existing API listener. Configuration writes and rescue rollback
commands are gated on `apply`; this action does not enable them. Ansible temporary
files and evidence logs are expected. No key recovery or global engine switch.

## Next field run (not executed by this change)

1. Review this source revision, pin its full SHA in a clean isolated checkout on
   **ansible01 / server01_ansible**, and record the actual checkout path. Confirm
   an exclusive approved window against current Phase 1 work before starting.
2. Confirm unchanged approved worker02 address/account/key/known_hosts and source
   inventory. Use the previously verified candidate core2.21.3 directory; record
   its exact path/version. Keep system RPM/core2.16.19 untouched.
3. From that checkout, with its reviewed config and approved key, a fresh private
   evidence directory and the recorded `FDS_ANSIBLE_ENGINE_DIR` /
   `FDS_ANSIBLE_ENGINE_VERSION=2.21.3`, run once:

   ```bash
   timeout --signal=TERM --kill-after=10s 120s bash scripts/cr-p1-ans-01-01-run.sh verify-worker02
   ```

   Existing prerequisites include `ANSIBLE_PRIVATE_KEY_FILE`, `ANSIBLE_CONFIG`
   pointing to that checkout's config and `CR_EVIDENCE_DIR` pointing to the fresh
   output directory. Record these paths without collecting key content. Capture
   outer exit status, invocation, KST start/end, source SHA/clean status, selected
   engine, inventory/vars hashes, wrapper log and SHA256 manifest. Preserve failed
   logs too. This example is a preparation procedure, not a reserved window.
4. Require rc0, localhost guard PASS, worker02-only recap with changed0 /
   failed0 / unreachable0, DNS assertions and no service regression. These prove
   only this scoped verify run; they do not prove six-node DNS, apply/idempotency,
   rollback or Issue9 acceptance.
5. On guard/authentication/assertion failure, unreachable or timeout: stop, retain
   original logs and investigate. Do not retry automatically, widen scope, run
   apply, rewrite baseline or restore a key. No persistent mutation is intended,
   so no configuration rollback is scheduled. If unexpected mutation is found,
   preserve evidence and use a separately reviewed recovery plan.

## Reproducible isolated tests

Run `python -B -m unittest discover -s tests -p test_ansible_engine_selection.py -v`
on Linux for mocked CLI dispatch/error propagation and unchanged approval gates.
Run `python -B -m unittest discover -s tests -p test_dns_worker02_scope.py -v` with
each pinned Ansible venv's Python (2.16.19 and 2.21.3). The latter copies the real
playbook unchanged but uses only local connections and a stub role in a temporary
directory. It covers empty/missing/ambiguous/wrong targets, positive selection and
role failure. It does not invoke operational DNS tasks, SSH or sudo. CI unit
discovery runs this suite on its first pinned engine; the ordinary syntax matrix
includes the new playbook on both engines. Record separate manual two-engine
results and CI state without equating either to field execution.

## Recorded validation — 2026-10-08 KST

[Original logs and receipt](../change/validation/issue9-dns-worker02/RESULTS.json)
record the final isolated run at **01:08:53–01:09:06 KST** on ansible01 under
server01_ansible. Both pinned engines passed 8 scope tests each; 14 mocked engine
selection/wrapper tests, both playbook syntax checks and the wrapper shell syntax
check passed. All 140 staged source files were compared byte-for-byte by SHA256
with the local source after execution; the receipt pins the relevant executable
files. The manifest protects the collected logs, not a claim of DNS success.

The first fixture run detected that host/group name collision did not necessarily
expand selection on these engines. The final guard rejects the ambiguous name
explicitly; both collision and group-only alias cases pass the negative test.
The initial failed fixture directory is retained on the controller separately.
GitHub CI and independent source review are separate pending stages at publication;
worker02 field execution, apply/rollback and engine transition remain NOT_RUN.
