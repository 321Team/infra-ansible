# Observed chrony main/drop-in migration

Status: **PR #27 approved and merged into the PR #24 working branch; production apply NOT RUN**.
The approval and single-entry workflow are recorded in
[the persistent rollout instructions](CR-P1-NTP-01-01-rollout.md).
Base: PR #24 HEAD `63797f3fcb7cfaa3ec8281b2ec6faa32948d84b3`, tree
`49bd1495d874e82da1a477f599bd43b6005108a0`.

## Why this change is needed

The read-only receipt `ansible-ntp-readonly-evidence.at9v4_pp.tar.gz`
(SHA256 `07579fcc1681af67abcde83fef040a6be88959766082749742523a396320f818`)
contains the six nodes' observations at 2026-09-18 21:14:44–21:15:00 KST.
Its outer manifest has 203 verified entries and its nested role manifest
has four. All six main files have SHA256
`147346c1b876b87dfad3bd436c62bc137c36723137ed5b647cf376a9f54e66aa`.
They contain the original pool and DHCP sourcedir and no active include or
confdir. No managed drop-in or CR state directory exists in this receipt.
Precheck stopped all six hosts with changed=0. This is a layout blocker,
not a failed apply.

The drop-in directory's complete contents were not collected. Therefore the
migration uses one exact include, not a broad confdir or wildcard that
could activate other files:

```text
include /etc/chrony.d/50-cr-p1-ntp-01-01.conf
```

| Role | Main change | Managed fragment |
|---|---|---|
| control01 | Remove the observed pool and sourcedir; append the exact include | Three explicit public NTP servers; allow the five client addresses, each /32 |
| Five clients | Remove the observed pool and sourcedir directives; append the exact include | `server 10.1.93.102 iburst` |

The remaining main bytes, including `makestep 1.0 3`, are retained. No
immediate clock-step command is added, but after restart the existing rule
can step an offset greater than one second during the first three updates.
This is not a guarantee of step-free execution. Removing the client's sourcedir
directive stops chronyd from consuming those hints; it does not edit
NetworkManager profiles or delete DHCP files. The source's upstream is now
part of this proposed change, following the user's request to implement the
Kubernetes owner's public-NTP proposal. It is not inferred from the current
pool's resolved addresses.

## Public upstream design review

The reviewed candidate accepts exactly three distinct public IPv4 literals
in `cr_ntp_source_upstreams`; its default is an empty list. Source planning
and apply stop until endpoints are supplied. No public address or DNS result
has been silently selected for production. The chosen list must be the same
in chronyd and the firewall request. Clients still use control01 only.

Three is the selected size within the requested two-to-three range:
[chrony recommends at least three](https://chrony-project.org/faq.html#_what_is_the_minimum_recommended_configuration_for_an_ntp_client),
while [RFC 8633 section 3.2](https://www.rfc-editor.org/rfc/rfc8633.html#section-3.2)
prefers four independent, diverse sources for resilience. Three has less
headroom after one loss; two disagreeing sources cannot establish which is
correct without other information. This limited baseline proposal does not
claim four-source resilience or fix the existing control01 single point of
failure.

Selection must consider public-service permission, service/provider failure
domains, reachability/offset from this network and a compatible leap-second
policy. Do not mix smeared and non-smeared time; see
[Google's explicit warning](https://developers.google.com/time/faq#i_am_using_another_ntp_service_now_can_i_also_use_google_public_ntp)
and [RFC 8633 section 3.7.1](https://www.rfc-editor.org/rfc/rfc8633.html#section-3.7.1).
Three IPs owned by one provider do not prove three independent references.
An IP fixed in configuration is also not a promise that a provider will
retain it forever; changing it needs coordinated chronyd/firewall review.

The firewall contract is control01 `10.1.93.102/32` to the three approved
`/32` destinations, UDP destination port 123, with stateful replies. Do not
pin the request's source port to 123 or open unsolicited Internet ingress.
The number of actual rules depends on the effective egress firewall and HEP
policy; adding an inbound `ntp` service is not an outbound permission. The
five clients receive no direct-public egress in this design. No new relay VM
or service is required, but this is not merely one unqualified firewall rule.

The [2026-09-16 Lead Decision](https://github.com/321Team/fds-project-baseline/issues/10#issuecomment-5697547621)
specified internal UDP/123 and no new external egress. Record acceptance of
this precise policy delta with the endpoint list before runtime. The user
has authorized implementation/review work; that does not prove a firewall
rule already exists or that candidate endpoints have passed host tests.

## Selection and recovery contract

Migration is disabled by default (`cr_ntp_migrate_main: false`). The wrapper
accepts only `CR_NTP_MIGRATE_MAIN=0` or `1`; value `1` passes the boolean
option to every phase, including rollback. It does not grant change approval.
The existing `CR_CHANGE_APPROVED` check and source/evidence binding remain.

Only the observed original or the exact validated migrated layout is
eligible. Main drift, unsafe file types, incompatible saved state and
unmanaged client sources stop execution. Both main and managed fragment
belong to the recovery unit. The original baseline is retained across
successful reruns; automatic failure recovery uses the current invocation's
snapshot. An unchanged run that fails verification must not restore an older
baseline and undo an earlier success.

Run only one controller workflow per target host. The module retains its
state-directory lock for file commit/recovery. The new rollout entry and
standalone wrapper additionally share one controller-wide lock spanning
service restart, runtime verification and finalization.

The paired baseline is `original-ntp-pair.json` in the protected CR state
directory. Schema version 2 binds the change ID, inventory host, source/client
role, both destination paths and the observed original main hash. Each file
record contains existence, base64 content, SHA256, uid/gid/mode and SELinux
context. Additional file ACL/xattrs and inherited default directory ACLs
stop migration for review. Local SELinux snapshot tests do not establish
successful xattr restoration under the target's Enforcing policy.
An existing `original-ntp-dropin.json` belongs to the older one-file contract;
migration preserves it and stops rather than converting it in place.

The candidate pair is parsed using the installed `chronyd -p` before the
live configuration is changed. Installation writes the fragment before the
main include; recovery restores main before the fragment. These are two
file replacements, not one atomic filesystem operation. An interrupted
process or host failure can leave a partial transaction: preserve the
baseline/evidence and use the selected-host recovery procedure. A failed
restore stops the batch; service-active alone is not NTP acceptance.

Check mode predicts differences without changing the live pair, baseline or
service. Temporary candidate validation is not runtime deployment. Local
fixtures and parser tests are documented separately from host acceptance.

## Runtime prerequisites and order

This change does not open a runtime window. Under `docs/REVIEW_POLICY.md`,
new execution code requires an independent review of its own HEAD followed
by the Lead's merge decision. Use the reviewed and merged SHA for runtime.

Before source apply, confirm the selected three endpoints and control01-only
external egress decision, the actual chronyd service configuration path/options,
and the approved effective internal UDP/123 host/network policy. The receipt shows
no NTP listener and `209 Access denied` on control01; `chronyc accheck`
measures ACL permission, not client-to-server packet reachability. Observed
firewalld zones alone do not establish the full nftables/HEP path. No
firewall or Calico policy is applied by this role. The egress generator
produces a review contract, not a backend-specific rule or proof of enforcement.

Use the [single-entry rollout](CR-P1-NTP-01-01-rollout.md) after its exact
HEAD is independently reviewed and merged. It accepts the endpoint list and
existing policy/recovery references once. The workflow performs precheck and
public NTP response diagnosis, applies the source, verifies all five internal
NTP paths, then applies the clients and verifies all six hosts. Both mutation
phases preserve check/diff → apply → zero-change check. Source/path evidence
is checked programmatically before client mutation; phases do not require
repeated approval prompts. Any failed prerequisite stops later mutation.

The individual wrapper actions remain for scoped diagnosis and recovery.
Do not use a hand-written sequence to bypass the consolidated path gates.

Keep migration mode selected for paired rollback, for example:

```bash
CR_NTP_MIGRATE_MAIN=1 CR_CHANGE_APPROVED=CR-P1-NTP-01-01 \
  ./scripts/cr-p1-ntp-01-01-run.sh rollback k8s-worker02
```

Paired rollback restores the original pool and DHCP source as well. The
network owner must retain the pre-change firewall policy and coordinate its
recovery: an allowlist limited to the new fixed addresses may not permit
the original pool's addresses. This role cannot restore firewall state and
does not claim restored synchronisation solely from restored files.

Do not delete a legacy or damaged baseline to bypass validation. Preserve it
for review. No token, private key content or GitHub authentication file
belongs in evidence. The key path above selects the existing verified key;
it does not create, rotate or distribute one.

The separate acceptance criteria remain: offset <=100ms, 60-second samples
six times, sync loss of at least five minutes failing, and resynchronisation
within five minutes after reboot. The previous receipt is a snapshot and
does not satisfy those continuous/reboot tests. They are not established by
a local parser, a mock fixture, a code approval or a merge. In the approved
isolated acceptance stage, also test one public-source loss while two remain,
all-upstream loss and recovery, and attempts by other nodes to reach public
NTP directly. The egress request's proposed restriction is not evidence that
those packets are currently blocked.
