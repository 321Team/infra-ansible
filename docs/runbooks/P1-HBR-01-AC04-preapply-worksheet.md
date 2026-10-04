# P1-HBR-01 AC-04 pre-apply worksheet

Updated after host captures14:15/14:45/15:15 KST, 2026-10-04.
Status: READONLY_CAPTURE_REVIEWED / OPERATIONAL_CONDITIONS_PENDING / APPLY_NOT_EXECUTED / WINDOW_NOT_CONFIRMED.

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
cover every observation below. Additional host collection has now been executed and reviewed. Raw captures
remain separate; this worksheet does not replace them. Do not repeat completed
collection unless drift, missing evidence or an approved verification plan requires it.

- Preapply14:14:55–14:15:26 KST, archive SHA256
  `2a4908f103934e2ed06456c2b2848566a22e0de0c7bf3e38dc8ef0b199051fe2`;
  52 manifest entries verified; discovery27/precheck47/surface3 tasks,
  changed0/failed0/unreachable0; Ansible2.16.19, exact source above.
- Listener/loader14:45:54–14:45:57 KST, archive SHA256
  `dc7a6842f372c04a94ccb2054a8274a5e1233b91051e7233fd53e4331f29f218`;
  32 manifest entries verified;7 command rc0; supplemental ok3/changed0/failed0.
- Source archive SHA256 for both:
  `3e0b3ddd351df28962804e511a2a723cf0b9196f9dfb95400c1bef2aa0b55259`.
- Review index: https://github.com/321Team/infra-ansible/issues/62.
  Original text files and deployed collectors are preserved in
  [evidence Draft PR105](https://github.com/321Team/fds-project-evidence/pull/105), exact commit
  `979ae50a59c3a79e8d989a7cb943320e34057877`.
  Draft/open/unmerged at this update; independent evidence review PENDING.
  [CI37183878567](https://github.com/321Team/fds-project-evidence/actions/runs/37183878567) passed unit tests
  and evidence layout/exception/registry checks. CI is not independent acceptance.

### Immutable capture review map

| Capture | Original files and manifest | Deployed collector |
|---|---|---|
| Preapply | [raw / SHA256SUMS](https://github.com/321Team/fds-project-evidence/tree/979ae50a59c3a79e8d989a7cb943320e34057877/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/preapply/raw) | [collector](https://github.com/321Team/fds-project-evidence/tree/979ae50a59c3a79e8d989a7cb943320e34057877/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/preapply/collector) |
| Listener/loader | [raw / SHA256SUMS](https://github.com/321Team/fds-project-evidence/tree/979ae50a59c3a79e8d989a7cb943320e34057877/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/path-loader/raw) | [collector](https://github.com/321Team/fds-project-evidence/tree/979ae50a59c3a79e8d989a7cb943320e34057877/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/path-loader/collector) |
| Saved IPv6 configuration | [raw / SHA256SUMS](https://github.com/321Team/fds-project-evidence/tree/979ae50a59c3a79e8d989a7cb943320e34057877/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/ipv6-config/raw) | [collector](https://github.com/321Team/fds-project-evidence/tree/979ae50a59c3a79e8d989a7cb943320e34057877/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/ipv6-config/collector) |

[RECEIPT.json](https://github.com/321Team/fds-project-evidence/blob/979ae50a59c3a79e8d989a7cb943320e34057877/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/RECEIPT.json)
binds each original attachment ID, received time, archive size/hash and capture
source/times. Original archives remain user attachments; this Git commit preserves
119 extracted original files and 24 collector files without altering their bytes.
Raw manifests cover 116 entries; collector manifests cover 21 entries.
Collector independent code review remains NOT PERFORMED (Pre-check); PR63 source
code approval does not cover these separate collectors. Evidence import review,
document review, operational authorization and AC04 acceptance are separate gates.

## Before apply: record and decide

| Required observation | Decision rule | Current execution |
|---|---|---|
| NICs, IPv4/IPv6 addresses, routes, VIPs and Docker publish/DNAT bindings | All Harbor443 ingress must be covered by reviewed enforcement; an additional path is STOP for scope review, not an implicit exception | CAPTURED_REVIEWED; operational decision pending |
| Current actual Harbor clients, including registry-sync and monitoring | Compare with exact approved set and identify unknown consumers before change | NOT_RECONFIRMED |
| Temporary .50/.102 need, owner, removal trigger and tracking in baseline#13 | Lead confirms inclusion/removal plan; no invented expiry | NOT_RECONFIRMED |
| nftables.service state, loaded unit/drop-ins, configuration and competing ruleset loaders | Potential guard removal requires reviewed ordering/policy resolution; collection does not change service state | CAPTURED_REVIEWED; operational decision pending |
| control01 UI fallback | Reconfirm access immediately before apply; retain evidence reference | NOT_RECONFIRMED |
| HA drain/rebalance, Harbor recreation and monitoring rollout schedules | Window must not overlap conflicting changes | WINDOW_PENDING |
| Complete sealed prestate and unchanged operational baseline | Existing precheck must PASS; drift is STOP | PRECHECK_PASS at14:15; apply-time drift check and sealed prestate pending |

## Captured path and loader findings

- Physical ingress ens160, IPv4 10.1.93.54/24; current IPv4 host443 DNAT
  ->172.18.0.11:8443. Additional external NIC/VIP not observed in this snapshot.
- Docker publishes443 on0.0.0.0 and::. Both listeners are docker-proxy;
  IPv6 listener PID3519867 maps::443 ->172.18.0.11:8443.
- ens160 disable_ipv6=1, no IPv6 address; all/default disable_ipv6=0.
  Bridge/veth link-local addresses remain; no external/default IPv6 route observed.
  Reboot/reconnect persistence of ens160 IPv6 disable is NOT_VERIFIED.
- Exact guard covers forward + DNAT traffic. Protection of local INPUT/userland
  proxy is not established. Current external IPv6 disable is a separate condition,
  not IPv6 firewall PASS or a tested bypass.
- nftables.service disabled/inactive/dead; no drop-in, WantedBy or triggers.
  sysconfig main.nft include is commented. main.nft has flush ruleset but its
  current active service inclusion is not observed.
- Service ExecReload and ExecStop contain flush ruleset. Explicit invocation can
  affect guard and managed tables; maintenance/recovery must be reviewed.
  Global custom loader audit was not performed.
- ss443 connections0 is not full client/conntrack inventory.
  Docker daemon.json absence does not establish daemon CLI/default values.

Technical interpretation references:
https://docs.docker.com/engine/network/port-publishing/
https://wiki.nftables.org/wiki-nftables/index.php/Netfilter_hooks

## Saved IPv6 configuration evidence —15:15 KST

- Capture15:15:46–15:15:50 KST; archive SHA256
  `4bdd667209f7ecfc22a84bd76ed05177f1a0ad2cb167f9d75adee20d12382caf`;
  32 manifest entries and deployed collector SHA verified;7 command rc0;
  supplemental ok3/changed0/failed0/unreachable0; exact source unchanged.
- Active ens160 NM connection UUID:
  `3094c330-0b11-4463-9409-29c11bca6fcb`.
  Effective query: interface ens160, autoconnect yes, ipv6.method disabled.
- One matching file-backed profile:
  `/etc/NetworkManager/system-connections/fds-harbor01.nmconnection`;
  SHA256 `110883e9363a878da5962e32fb5631a36cdddb675f8014a39f2c3d79ff68c0bf`.
  Saved UUID/interface/ipv6.method match the active connection. Saved
  autoconnect is not explicitly present in selected file fields; the effective
  query says yes. Do not rewrite the saved file to insert that value.
- NetworkManager active/running/enabled. systemd-sysctl active/exited;
  loader ExecStart observed, no drop-in.
- Selected all/default/ens160 disable_ipv6 directives were absent in captured
  regular sysctl files. The99-sysctl.conf link is recorded as../sysctl.conf;
  the separately captured/etc/sysctl.conf contains no selected disable directive.
  This is not a complete custom/wildcard sysctl or profile-loader precedence audit.
- Verdict: SAVED_IPV6_DISABLED_CONFIGURATION_CONFIRMED_SCOPE.
  Actual reboot/reconnect persistence remains NOT_TESTED, not PASS.
  No additional read-only recollection is required by this result alone.
  Post-change/persistence testing belongs to the approved window and plan.

## Lead/operations decision record — unapproved worksheet

Recommended path: retain the existing Phase1 IPv4 ingress baseline and review
the ens160 IPv6-disabled constraint, now backed by a saved matching profile,
before using the reviewed source.
This is not an accepted exception or lowered AC. If persistence cannot be
demonstrated or IPv6 support is required, prepare a separate INPUT/proxy
enforcement design and new-head validation/review.

| Required decision | Concrete record required | Status |
|---|---|---|
| IPv4-only ingress / IPv6-disabled constraint | Lead disposition, exact scope, persistence configuration/evidence; no invented exception | PENDING |
| Reboot/reconnect and future address changes | Saved NM disabled profile confirmed; interface/VIP/IPv6 change STOP condition pending; additional reboot/reconnect testing only if included in an approved plan | CONFIG_CONFIRMED / RUNTIME_NOT_TESTED |
| Ruleset loader maintenance | Reload/stop/main.nft load coordination, reviewed recovery and post-maintenance exact guard/managed-table checks | PENDING |
| Clients and temporary sources | .20/.105/.107/.108 actual use; .50/.102 need, owner, removal trigger and baseline13 reference | NOT_RECONFIRMED |
| UI fallback | Fresh control01 access evidence immediately before apply | NOT_RECONFIRMED |
| Change window / impact | KST start/end, approver, HA/monitoring/recreation non-conflict, existing unapproved sessions DROP notice | NOT_CONFIRMED |
| Guard operational handoff | Periodic verify owner/schedule/failure response; no automatic timer deployment implied | PENDING |
| Draft/merge HOLD and runtime authorization | Lead disposition, exact source/act/window approval; attestations only after confirmed underlying facts | HOLD |
| AC04 acceptance | Post-apply positive/negative/pull/persistence evidence and Lead acceptance | NOT_EXECUTED |

Leave unknown decision values unset. Do not populate apply attestation constants
until their underlying approval, UI fallback and window facts are confirmed.
This worksheet does not authorize production apply.

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

## Persistence scope — existing acceptance criteria

The exact source runbook section9 requires guard/dependency and positive/negative
verification before/after an approved Docker restart. That required persistence
scope is retained. VM reboot or NetworkManager reconnect is not added as a new
mandatory acceptance gate by this worksheet. Saved IPv6-disabled configuration
is confirmed; actual reboot/reconnect remains NOT_TESTED and may be included in
a separately approved plan if Lead considers it necessary.

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
