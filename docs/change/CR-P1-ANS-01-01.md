# CR-P1-ANS-01-01 Change Record

## GitHub remote baseline gate

| Item | Verified value | Result |
|---|---|---|
| GitHub App installation account | `321Team` Organization | PASS |
| Selected repository | `321Team/infra-ansible` | PASS |
| Visibility | Private | PASS |
| Default branch | `main` | PASS |
| `main` HEAD | `98cf3f826ac0805bcc771ad760a15d931c1bd414` | PASS |
| Commit tree | `3b41c71bd5c7f85db1d901d1f2eae8d427338e1c` | PASS |
| Blob count at baseline commit | 13 | PASS |
| Repository Rulesets API | GitHub Free Private 제한으로 HTTP 403 | EXPECTED |
| Ruleset compensating-control approval | `EXC-CR-P1-ANS-01-01-01` | APPROVED |

Verification date: 2026-09-04

The Rulesets API returned `Upgrade to GitHub Pro or make this repository
public to enable this feature.` The repository remains Private. Until a plan
supporting Private Repository rulesets is adopted, the approved compensating
controls are a CR-named branch, pull request review, an immutable reviewed
commit SHA, no direct operational push to `main`, and ticket evidence.

## Implementation scope

- Preserve the closed `P1-ANS-01` ticket and implement the resolver transition
  under this Change Request.
- Use dns01 `10.1.93.52`, then dns02 `10.1.93.53`.
- Set the search domain to `fds.internal` and ignore automatic DNS.
- Apply the remaining control-plane nodes before the worker batch.
- Verify all six Kubernetes nodes, including the previously configured
  `k8s-control01`.
- Preserve one original resolver state record per changed node for rollback.
- Stop the serial batch and restore pre-change values if apply or reapply fails.
- Keep raw execution evidence outside Git tracking under
  `docs/evidence/CR-P1-ANS-01-01/`.

## Current status

| Gate | Status |
|---|---|
| GitHub App and remote baseline | PASS |
| Ruleset exception traceability | RECORDED |
| Ansible implementation and runbook | PREPARED |
| Control-plane batch execution | PENDING ON `ansible01` |
| Worker batch execution | PENDING AFTER CONTROL-PLANE PASS |
| Six-node final verification | PENDING |
| Evidence index and SHA-256 | PENDING |
| Support review by 이하영 | PENDING |
| Final approval by 이권욱 | PENDING |

This record does not mark the infrastructure change as complete. Completion
requires every Acceptance Criterion in the approved CR document and the
reviewer/approver record.
