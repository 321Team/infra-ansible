# Issue 9 local dual-engine conditional check

Source: 8804f27fcd8c105adf7497d9c922fb9df1513472 (main e1c4458 plus existing two-file compatibility change).
Scope: assistant Linux scratch, Python 3.12.14, separate virtual environments using the repository's exact requirements-verification-2.16.19.txt and requirements-verification-2.21.3.txt pins. No SSH, production inventory execution, operating-engine switch or GitHub Actions run.

| Engine | Changed playbook syntax | Conditional fixture |
|---|---|---|
| 2.16.19 | rc0 | rc0 |
| 2.21.3 | rc0 | rc250 before task execution; environment blocked |

Fixture extracts the production final assertion and exercises explicit false (accept), true, missing verdict, missing failed, string false and numeric zero (reject). Expected negative assertions are ignored only inside the test and a following assertion verifies that only explicit false passed. Four async finished inputs (0, 1, false, true) are also checked. The 2.16.19 fixture as a whole succeeded; ignored expected negatives are not production PASS results.

2.21.3 failed initializing LocalManager with 'Local RPC server did not start'. A separate standard Python multiprocessing.connection.Listener() diagnostic returned PermissionError errno1 Operation not permitted. Do not disable isolation or patch Ansible to force a PASS. The 2.21.3 conditional fixture remains NOT_VERIFIED; this startup failure is not evidence that the production conditional is incorrect. Both syntax checks completed without executing production tasks.

Reproduction on an authorized isolated CI worker with the pinned environment:

```bash
/path/to/pinned-venv/bin/ansible-playbook -i localhost, -c local --syntax-check playbooks/p1-sec-01-b2-collect-58.yml
/path/to/pinned-venv/bin/ansible-playbook -i localhost, -c local docs/change/validation/issue-9-conditional-20261004/conditional-fixture.yml
```

Each command must return rc0. Preserve stdout/stderr and rc even on failure; no parent-shell set -e/-u/pipefail is required. The fixture only creates in-memory inventory hosts and assertions; it does not contact those named hosts. Production playbook is syntax-only. No rollback is required for this local fixture.

Next: resolve the existing PR67 regression queue via the reviewed runner process, then open the prepared source PR and run the normal full regression plus this 2.21.3 fixture on the supported isolated runner. Independent review, canary/idempotency/rollback and operating-engine transition remain pending. No AC, due date or owner change.

AI usage: CODEX_ASSISTED.
