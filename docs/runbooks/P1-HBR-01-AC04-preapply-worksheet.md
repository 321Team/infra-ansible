# P1-HBR-01 AC-04 pre-apply worksheet

Updated 2026-10-04 against records available at 22:57 KST.
Status: APPLY2_COMPLETED / CONFIG_VERIFY_PASS / TRAFFIC_AND_PERSISTENCE_PENDING / AC04_NOT_PASSED / PR67_DRAFT_HOLD.

## Current post-apply status — 2026-10-04 22:57 KST

This section supersedes current-status statements in the historical sections
below. It records submitted evidence and decisions; it does not grant a new
execution window or retrospectively authorize an earlier action.

| Item | Confirmed record / remaining boundary |
|---|---|
| Applied source | `e1c4458cf95dacca76870d7b9b012f8615f6974a`, merged PR68; use the exact SHA, not moving main |
| Apply / configuration verify | [Evidence PR109](https://github.com/321Team/fds-project-evidence/pull/109), original reviewed HEAD `c8ae9931687ed0e2e66951eec76f83751e0de45b`: apply2 21:32:34–21:33:20 KST, ok162/changed12/failed0; verify 21:34:05, ok67/changed0, CONFIG_PASS_RUNTIME_TRAFFIC_TESTS_PENDING |
| Evidence integrity and integration | [PMO/QA review](https://github.com/321Team/fds-project-evidence/pull/109#pullrequestreview-5406364585): 14 file hashes and collection-to-root registry match. [Independent review](https://github.com/321Team/fds-project-evidence/pull/109#pullrequestreview-5406382674) covers original evidence. PR109 current integration HEAD `ebb782cc0970ebf8df0bee058b9d9ef43558916b` remains Draft pending independent delta reapproval; do not equate hash integrity with Runtime acceptance |
| Authorization chronology | Apply2 preceded the [21:37 conditional GO](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-5979990693). Preserve the deviation and omitted pre-apply records. This worksheet does not retroactively approve them |
| 21:10 PRECHECK limitation | Lead reported a PASS on screen, but the named file is now 37 bytes containing User interrupted execution. Cause is unknown; preserve the anomalous original. Older intact PASS files are historical evidence, not substitute bytes for this run |
| Original XML | Apply2 Preserve original public zone XML task reported ok, not changed. Do not assert it was overwritten. The first-attempt post-copy hash was not captured; that limitation remains |
| Post-apply observations | Runner positive and local health were reported. Browser failure / proxy-log silence alone do not prove firewall DROP; curl -k localhost health is not TLS validation |
| Monitoring | [MON Lead 22:12 observation](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-5980433117): Target23/23 and nodes6/6. This is a single-time post-apply observation, not future restart-window regression credit |
| Current authorization | The earlier 22:00 window has ended. [22:53 PMO/QA decision](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-5980737850) accepts the AC03 execution model and retains read-only precheck GO; actual login/pull/push/Pod tests remain HOLD pending field precheck and a new non-overlap window |
| Roles and acceptance | Execution: hayeounglee; GO/STOP/result acceptance: GWONUK. AC03/AC04 NOT PASSED. PR67 remains Draft under its existing merge HOLD; its merge is not a new Runtime prerequisite |

### Next actions — reuse completed work

1. Preserve the actual state-file bytes/hash and anomalous 37-byte precheck file
   requested in #13. Do not recreate historical records or replace them with a
   later capture. PR109 already contains a state-file observation/hash listing;
   that listing is distinct from the underlying server-file bytes.
2. Consume one field precheck submission and a concrete new non-overlap window
   under the [existing AC03 decision](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-5980737850).
   Existing source review/MOCK/handoff checks need not be repeated without drift.
   AC03 execution source remains `030a4ce14acdab3a58c4767455b7555aaf8ce949`;
   workload SA is the existing `transaction-api-sa` in `fds-app`.
   Do not create credentials/SA/RBAC or change CA settings under read-only GO.
3. After explicit Runtime GO, bind Worker node/control results, final exit codes
   and cleanup to the official Run/digest. Reuse successful approved-source
   traffic as AC04 positive evidence only for the tested path.
4. Complete AC04 controlled negative-source attribution, remaining positive
   paths, approved Docker-restart persistence with monitoring regression, and
   temporary .50/.102 exception disposition/removal tracking. Do not add VM
   reboot or NetworkManager reconnect as a new mandatory gate.
5. Review the remaining results for AC04 acceptance. Unexpected results require
   STOP and evidence-preserving reconciliation/recovery under the reviewed plan.

## Historical retry readiness — 2026-10-04 after 21:31 KST

The following section is retained as the pre-retry record. Its RETRY_NOT_EXECUTED,
new-GO-pending and precheck assumptions are superseded above. In particular,
the prospective XML-overwrite caution below is not a claim that apply2 overwrote
the XML; apply2 reported ok.

This section supersedes the current-status wording in the historical sections
below. The earlier GO was explicitly bound to 09264ae; it is not automatically
transferred to the corrected source.

| Item | Confirmed record / remaining boundary |
|---|---|
| Reviewed fix | [PR68](https://github.com/321Team/infra-ansible/pull/68), exact HEAD `efe82dda8cff8594533d2603e2a0e567e07dded9`, independent code APPROVED |
| Merged retry source candidate | `e1c4458cf95dacca76870d7b9b012f8615f6974a`; GitHub compare from reviewed HEAD reports zero changed files. Pin this commit, not moving main |
| CI | [Run37197754190/Attempt1](https://github.com/321Team/infra-ansible/actions/runs/37197754190), Job111423030828, reviewed HEAD above: success at 21:25:49 KST. Syntax72/72 rc0, both engines2.16.19/2.21.3 and localhost fixtures PASS; artifact upload success |
| Merge/CI chronology | User explicitly requested merge at 20:53 while CI was queued. CI succeeded afterward; do not rewrite this as pre-merge CI success or a separate execution of merge commit e1c4458 |
| Host PRECHECK | [HBR Lead 21:10 report](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-5979797361): e1c4458 HEAD_MATCH, syntax5/5, contract PASS, tests13/13; PRECHECK_PASS_RUNTIME_NOT_CHANGED, ok47/changed0/failed0. Filter/NAT iptables-save rc0 (29/16 lines). This worksheet references the Lead report; it does not claim independent re-execution or raw-file verification |
| CI Runner cleanup | Runner ID50/name ansible-ci-fc36a38ff4d945748b04085c14e9c037 linked to Job; submitted archive hash/outer16 and inner9 manifest entries verified, isolation18/18 PASS, runner/proxy/workspace REMOVED. [21:31 user-submitted admin GET](https://github.com/321Team/infra-ansible/pull/68#pullrequestreview-5406127260): total_count0/runners[] |
| Evidence limits | CI artifact metadata/digest and Job logs checked; artifact ZIP internal file rehash and token-file deletion independently unverified. No production apply or engine transition was performed by the CI session |
| Authorization | New-source GO and a still-valid non-overlap window remain pending. Execution remains hayeounglee; GO/STOP/result acceptance remains GWONUK. No role reassignment |
| Acceptance | Corrected-source apply/verify/traffic/pull/persistence and AC04 acceptance are NOT EXECUTED / NOT PASSED |

### Failed attempt and residual-state disposition

[Lead failure report](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-5979320115):
20:02:28–20:02:44 KST on 09264ae, APPLY_RC2, ok49/changed2/failed1,
undefined hbr_ac04_filter_save. The state directory and original-public.xml
(392 bytes) were created; Lead reported no guard, generic443 retained, no rich
rules, Docker active and Harbor health200. These are reported observations,
not a successful apply or proof of unchanged state at a later time.

The corrected apply checks original-state.json existence, not directory
existence. Therefore the reported directory containing only original-public.xml
does not itself require deletion to retry. The copy task can replace that XML
with the current source XML; it is not an archive of the failed attempt.

Recommended disposition before an authorized retry:
- Preserve the failed-attempt output, residual directory listing and original XML
  bytes/hash in that attempt's evidence before a task can overwrite them.
- Do not delete the directory merely to bypass a gate. If original-state.json,
  a seal, guard files/unit/table or other unexpected state exists, STOP for
  reconciliation rather than remove it to satisfy assertions.
- Reuse the 21:10 PRECHECK record when still applicable; do not demand a duplicate
  full collection solely because this documentation changed. Reconfirm immediate
  ingress/loader/client/UI/non-overlap conditions and investigate actual drift.
- The original 22:00 cutoff is not extended here. If the remaining window cannot
  accommodate verification and failure recovery, defer to a newly confirmed
  non-overlap window. Do not prefill authorization attestations without GO.

This is documentation/readiness follow-up only. PR67 remains Draft with its
existing explicit merge HOLD; its merge is not an added runtime prerequisite.


## Historical merged source and execution decision — 2026-10-04 19:32 KST

PR63 is merged. The operational source is pinned to
`09264ae3880e5c1764e4f3406543e8bb4d664de4`, not a moving main checkout.
[PMO/QA decision](https://github.com/321Team/fds-project-baseline/issues/13#issuecomment-5979057315)
assigns execution to hayeounglee and GO/STOP/result acceptance to GWONUK.
The decision grants conditional GO before 22:00 KST on 2026-10-04 only,
after merged-source PRECHECK and all listed pre-apply conditions pass.
The reviewed f222f1f CI is historical exact-source credit; the merge differs only
in three runner-related files, with AC04 content unchanged. No separate merged
commit CI or successful runtime execution is claimed here.
This documentation PR is not a prerequisite for that execution and does not
change the pinned operational source or authorize an overlapping change window.
PR63 merge HOLD has been resolved; this separate PR67 remains Draft pending
its own disposition. The historical captures below remain bound to badbe294.

## Historical host-capture scope — badbe294

- Source: badbe29440916ec3ec79da8fc81722c2e6c4e75b.
- Independent code review: hayeounglee APPROVED 2026-10-04 08:59:08 KST; earlier nft-output hypothesis withdrawn.
- CI: Run37111252832 completed/success, checked 2026-10-04.
- Isolated render/verifier: PASS; raw evidence commit31089383e6a43103c1e8ccca8e41e572acb8ac61.
- Source approval is not merge, change-window authorization, production apply or AC-04 acceptance.
- This document-only follow-up is a separate diff. If incorporated into the source branch, use the resulting new HEAD for required CI/PRECHECK/review.

## Historical source status — f222f1f

The badbe294 approval and host captures above are historical. Subsequent review
identified B-HBR-01 (rescue/rollback dependency-detach failure handling) and
B-HBR-02 (verifier prestate seal consumption); they do not constitute apply GO.
Both findings were fixed in `f222f1f15c52c74c1800ce1b4040a21e439e19ed`.
[Exact-source code re-review](https://github.com/321Team/infra-ansible/pull/63#pullrequestreview-5404881855)
by hayeounglee APPROVED the fixes; [CI Run37185044833](https://github.com/321Team/infra-ansible/actions/runs/37185044833)
succeeded with 90 unit tests and 72 syntax checks. Runner local cleanup and
user-provided remote absence were verified. This source has no new harbor01
PRECHECK or production apply evidence. That source review did not authorize runtime execution. The later merged-source
conditional decision above governs execution; its PRECHECK and runtime outcomes
have not been supplied to this worksheet. Integrating this documentation changes the source HEAD; bind
required checks and review to that resulting HEAD before apply.

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
  [merged evidence PR105](https://github.com/321Team/fds-project-evidence/pull/105), exact commit
  `dd6ea250da6d69477d2b038abcab13f5743cb246`.
  Independent reviewer supreme33-kr APPROVED this HEAD after B-105-01 archive
  preservation was fixed; PR105 is merged. This is evidence import acceptance only.
  [CI37187267018](https://github.com/321Team/fds-project-evidence/actions/runs/37187267018) passed unit tests
  and evidence layout/exception/registry checks. CI is not independent acceptance.

### Immutable capture review map

| Capture | Original files and manifest | Deployed collector |
|---|---|---|
| Preapply | [raw / SHA256SUMS](https://github.com/321Team/fds-project-evidence/tree/dd6ea250da6d69477d2b038abcab13f5743cb246/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/preapply/raw) | [collector](https://github.com/321Team/fds-project-evidence/tree/dd6ea250da6d69477d2b038abcab13f5743cb246/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/preapply/collector) |
| Listener/loader | [raw / SHA256SUMS](https://github.com/321Team/fds-project-evidence/tree/dd6ea250da6d69477d2b038abcab13f5743cb246/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/path-loader/raw) | [collector](https://github.com/321Team/fds-project-evidence/tree/dd6ea250da6d69477d2b038abcab13f5743cb246/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/path-loader/collector) |
| Saved IPv6 configuration | [raw / SHA256SUMS](https://github.com/321Team/fds-project-evidence/tree/dd6ea250da6d69477d2b038abcab13f5743cb246/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/ipv6-config/raw) | [collector](https://github.com/321Team/fds-project-evidence/tree/dd6ea250da6d69477d2b038abcab13f5743cb246/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/ipv6-config/collector) |

[RECEIPT.json](https://github.com/321Team/fds-project-evidence/blob/dd6ea250da6d69477d2b038abcab13f5743cb246/evidence/P1-HBR-01/infra-ansible-ac04-readonly-20261004/RECEIPT.json)
binds each original attachment ID, received time, archive size/hash and capture
source/times. The merged evidence commit preserves all three original tar.gz
files without recompression in archives/, with SHA256 sidecars and archive index,
as well as 119 extracted original files and 24 collector files. Independent
[re-review](https://github.com/321Team/fds-project-evidence/pull/105#pullrequestreview-5404965662)
confirmed archive-to-raw file sets and bytes; raw and collector bytes are unchanged.
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
