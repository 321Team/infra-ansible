# control01 fixed public NTP egress review

Status: **CANDIDATE_NOT_APPLIED**. Server address ownership/use policy and
effective network enforcement remain **PENDING**. No firewall is changed by
the renderer or by the local tests.

The requested design uses three distinct fixed public IPv4 upstreams for
`k8s-control01` (`10.1.93.102`). The other five nodes use only control01 for
NTP. Three literal addresses are required in the shared
`cr_ntp_source_upstreams` inventory variable; its empty default deliberately
stops rendering and source migration until the actual service addresses are
selected. Public address syntax alone does not establish a working NTP
service, permission to use it, ownership, or a compatible leap-second policy.
No IP resolved from a rotating public pool is promoted into production by
this code.

| Flow | Requested boundary |
|---|---|
| control01 to public NTP | Source `10.1.93.102/32`, three selected destination `/32` addresses, UDP destination port 123 |
| Public reply | Stateful replies to control01's requests only |
| Other five nodes | Internal NTP to `10.1.93.102/32`; direct public NTP is outside the permitted design |
| Internet-initiated inbound NTP | No permission requested |

chronyd chooses a client request's source port through the operating system
by default. Destination port 123 must not be confused with a fixed client
source port of 123. This request retains that default and records the actual
source port range and post-SNAT address as unconfirmed. See the chrony 4.8
[acquisitionport documentation](https://chrony-project.org/doc/4.8/chrony.conf.html#acquisitionport).

From the exact candidate checkout, after recording selected addresses in the
same vars file consumed by the role:

```bash
python3 tools/render-ntp-egress.py --format json --output ntp-egress-review.json
python3 tools/render-ntp-egress.py --format yaml --output ntp-egress-review.yml
python3 -m unittest discover -s tests/ntp_source -p test_egress_contract.py -v
```

PyYAML is required (also present in the Ansible controller environment).
`--vars-file` can select a review copy. Its SHA256 is embedded in the result;
any separate review copy must agree with the final deployed inventory.
The renderer does not resolve Ansible variable precedence: compare the
precheck's effective upstreams against this request before apply, including
any host-vars or extra-vars overrides. The output records that this effective
variable comparison has not yet been performed.
The renderer rejects an unselected list, duplicates, nonpublic/special-use
addresses, CIDRs, hostnames, embedded options, ambiguous YAML keys, and scope
drift in the six-node mapping. It performs no DNS queries or NTP probes and
never overwrites an existing output file. Tests use offline syntax fixtures,
not proposed production NTP addresses.

The output is review data, not executable firewall configuration and not
evidence of enforcement. A destination set might fit one rule in one backend,
but the required rule count depends on existing effective host firewall,
network firewall, routing/NAT, and any Calico HostEndpoint policy. The current
read-only receipt does not establish those complete policies. An egress allow
alone also cannot prove that broader existing rules do not permit the other
five nodes to contact the Internet directly.

Before the runtime window, reconcile the selected service addresses and their
use/time policies with the network owner, identify the effective path and
actual source after NAT, implement the reviewed backend-specific change,
and verify NTP replies to control01 plus five-client internal reachability.
Retain the separate internal UDP/123 policy and chrony ACL checks. Roll back
only the reviewed change if needed; do not flush rules or replace an entire
firewall policy. Source migration remains a paired main/drop-in change under
the existing exact-HEAD code-review and runtime procedure.

The paired NTP rollback restores the observed original public pool and DHCP
`sourcedir`. Their resulting destinations need not match the three newly
selected public addresses. Restoring chrony files while leaving a new strict
destination policy in place therefore does not guarantee restored clock
synchronisation. The network owner must preserve the previous effective
policy, reply/NAT behavior and supporting evidence, and coordinate recovery
of that reviewed policy change with NTP rollback. The role does not perform
firewall recovery, open extra destinations or remove policies automatically.
