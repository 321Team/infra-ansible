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
| Ansible implementation and runbook | PASS |
| Control-plane batch execution | PASS — `k8s-control02`, `k8s-control03` |
| Worker batch execution | PASS — `k8s-worker01` through `k8s-worker03` |
| Six-node final verification | PASS — validated at `12412cd6beae7039d` |
| Evidence index and SHA-256 | PASS — refinalized 2026-09-04 |
| `OBS-CR-P1-ANS-01-01-01` | RESOLVED AND REVALIDATED |
| Support review by 이하영 | PENDING |
| Final approval by 이권욱 | PENDING |
| Pull request merge to `main` | PENDING |

## Execution and evidence results

| Item | Verified value | Result |
|---|---|---|
| Reviewed execution commit | `3ebb8fc80d097a347ac5ad6e39a4bf10c631bd14` | PASS |
| Check Mode correction commit | `12412cd6beae7039de74be16258b8fb20c5d64b2` | PASS |
| Corrected commit tree | `3e41df12845cc79b6f6154554e4d11ec42200508` | PASS |
| Control-plane apply | 2/2 nodes, `changed=4`, `failed=0` | PASS |
| Control-plane idempotency | 2/2 nodes, `changed=0`, `failed=0` | PASS |
| Worker apply | 3/3 nodes, `changed=4`, `failed=0` | PASS |
| Worker idempotency | 3/3 nodes, `changed=0`, `failed=0` | PASS |
| Corrected Check Mode | 5/5 nodes, API checks executed, `changed=0` | PASS |
| Six-node revalidation | 6/6 nodes, `changed=0`, `failed=0` | PASS |
| Approved DNS direct queries | 12/12 | PASS |
| Kubernetes API Listener | Before 6/6 and after 6/6 | PASS |
| External resolution | 6/6 | PASS |
| kubelet/containerd regression | None on 6/6 nodes | PASS |

### Final evidence integrity

| Evidence | SHA-256 |
|---|---|
| `EVIDENCE_INDEX.md` | `6f5568d805a5d7f43130d2fdca2ba631358f4f8be23e1f7d0799ae8243c7db1e` |
| `SHA256SUMS` | `05de9ba6b22d36ef8fc67bdf3dd8c6629c3e334fbb61620a265a46acdbfd4115` |
| `20260904T180632+0900_verify_all_nodes.txt` | `18cbda0fc7d91ebf58c89c230dccabaf9ad8239305856da03067210582194e83` |
| `20260904T182705+0900_integrity_check.txt` | `35a320650312e343764a5d7eecfe70c42bafcf43c8043a422d920030a20dee14` |
| Evidence refinalization record | `db7da7eae13c1b07e6b073003a23229e76f3a86f6903a66ac9a2cf522f84395d` |

The evidence index identifies implementation commit
`12412cd6beae7039de74be16258b8fb20c5d64b2`. Raw execution logs and the
checksum manifest remain outside Git tracking and are retained locally on
`ansible01`.

## Review observations

| ID | Finding | Correction | Verification | Status |
|---|---|---|---|---|
| `OBS-CR-P1-ANS-01-01-01` | `ansible.builtin.wait_for` API checks were skipped under Check Mode while the summary still reported PASS. | Added `check_mode: false` to the read-only API Listener checks before and after the resolver run. | Both API checks executed on 5/5 Check Mode targets; the corrected six-node verification passed at commit `12412cd6beae7039de74be16258b8fb20c5d64b2`. | RESOLVED AND REVALIDATED |

## Precheck execution history

| Date | Event | Result |
|---|---|---|
| 2026-09-04 | Initial six-node Precheck | FAIL — dns02 `10.1.93.53` timeout on 6/6 nodes; `changed=0` |
| 2026-09-04 | Root cause confirmation | dns02 VM was powered off |
| 2026-09-04 | dns02 restart and repeated Precheck | Functional checks PASS — direct DNS 12/12, external resolution 6/6, API Listener 6/6, service regression none, `changed=0` |
| 2026-09-04 | Pre-apply log review | False-positive drift detected for `ipv4.ignore-auto-dns=yes` because Ansible normalized `yes` to Boolean `true` |
| 2026-09-04 | Automation correction | Boolean-safe drift and post-state comparisons added; corrected-commit Precheck rerun required before Control Plane apply |
| 2026-09-04 | Control-plane batch | Apply and idempotency PASS on `k8s-control02` and `k8s-control03` |
| 2026-09-04 | Worker batch | Apply and idempotency PASS on all three worker nodes |
| 2026-09-04 | Check Mode API correction | `OBS-CR-P1-ANS-01-01-01` resolved and revalidated at commit `12412cd6beae7039de74be16258b8fb20c5d64b2` |
| 2026-09-04 | Final six-node verification and evidence refinalization | PASS |

Technical execution and local evidence collection are complete. This record
does not mark the Change Request as closed. Closure requires support review by
이하영, final approval by 이권욱, and pull request review and merge to `main`.
