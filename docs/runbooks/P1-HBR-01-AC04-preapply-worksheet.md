# P1-HBR-01 AC-04 pre-apply worksheet

Prepared 2026-10-04. Status: NOT_EXECUTED / WINDOW_NOT_CONFIRMED.

## Current verified scope

- Source: badbe29440916ec3ec79da8fc81722c2e6c4e75b.
- Independent code review: hayeounglee APPROVED 2026-10-04 08:59:08 KST; earlier nft-output hypothesis withdrawn.
- CI: Run37111252832 completed/success, checked 2026-10-04.
- Isolated render/verifier: PASS; raw evidence commit31089383e6a43103c1e8ccca8e41e572acb8ac61.
- Source approval is not merge, change-window authorization, production apply or AC-04 acceptance.
- This document-only follow-up is a separate diff. If incorporated into the source branch, use the resulting new HEAD for required CI/PRECHECK/review.

## Execution environment and evidence

Run the existing read-only discovery/precheck from an exact, clean source checkout
on ansible01 as server01_ansible using the established operational Ansible2.16.19
environment and inventory/hbr.yml. Preserve command, rc, stdout/stderr, start/end
time, host/source identity and SHA256 manifest. Do not source shell setup into
the parent terminal; use an isolated child Bash with explicit status handling.
No set -e/-u/pipefail is required. These existing checks do not by themselves
cover every observation below. No extra collection was executed for this worksheet.

## Before apply: record and decide

| Required observation | Decision rule | Current execution |
|---|---|---|
| NICs, IPv4/IPv6 addresses, routes, VIPs and Docker publish/DNAT bindings | All Harbor443 ingress must be covered by reviewed enforcement; an additional path is STOP for scope review, not an implicit exception | NOT_COLLECTED |
| Current actual Harbor clients, including registry-sync and monitoring | Compare with exact approved set and identify unknown consumers before change | NOT_RECONFIRMED |
| Temporary .50/.102 need, owner, removal trigger and tracking in baseline#13 | Lead confirms inclusion/removal plan; no invented expiry | NOT_RECONFIRMED |
| nftables.service state, loaded unit/drop-ins, configuration and competing ruleset loaders | Potential guard removal requires reviewed ordering/policy resolution; collection does not change service state | NOT_COLLECTED |
| control01 UI fallback | Reconfirm access immediately before apply; retain evidence reference | NOT_RECONFIRMED |
| HA drain/rebalance, Harbor recreation and monitoring rollout schedules | Window must not overlap conflicting changes | WINDOW_PENDING |
| Complete sealed prestate and unchanged operational baseline | Existing precheck must PASS; drift is STOP | FRESH_PRECHECK_PENDING |

## Change-window notice draft

This is a draft for the approved window; it has not been sent.

Harbor443 source allowlist change: window/approver/source HEAD and evidence links
must be filled from confirmed records. Non-approved sources will be denied,
including already established TCP443 sessions whose subsequent packets reach
the guard. Intended approved sources are10.250.10.20 and10.1.93.105/.107/.108;
temporary10.1.93.50/.102 remain subject to Lead reconfirmation. Existing clients,
UI fallback and non-conflicting HA/monitoring schedules must be checked before
execution. Guard standalone restart is prohibited because it can propagate to
Docker/Harbor. Failure handling follows the reviewed rescue/rollback procedure.

Do not publish this draft as a scheduled change before the Lead confirms the
window and impact. Do not treat code approval as approval to execute apply.

## After authorized apply

Retain configuration verification plus actual positive probes from approved
sources, negative probes from10.1.93.26 and10.250.10.10, Worker pull/Pod start,
temporary-source paths, and approved persistence testing. Configuration PASS is
not traffic PASS. Review counters and Docker/firewalld non-interference. An
unexpected result stops acceptance; retain prestate/current evidence and use the
reviewed rescue/rollback/reconciliation path. Never fabricate completion markers.

Operational follow-up owner/schedule/failure response for periodic exact guard
verification remains UNASSIGNED here; Lead/operations must record it before
operational handoff. NIC/address assertions and tombstone deletion remain separate
code proposals requiring contract/reference review and new-head validation.
