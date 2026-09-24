"""Declarative CR-P1-NTP-01-01 contract over Calico HostEndpoint/GNP objects.

Plan A (2026-09-24): after Gate 2 moved host protection from firewalld to
Calico HostEndpoint + GlobalNetworkPolicy, NTP egress/ingress enforcement is
read from the Calico API instead of a pinned firewalld/iptables hash.

The evaluator is deliberately bounded rather than a general Calico engine:
every policy field that could change UDP/123 matching and is not modelled
here raises ContractStop (fail closed).  Rules that provably cannot match
UDP/123 (another protocol or port set) are skipped without interpretation.

Expected topology comes from reviewed inputs (source host/IP, five client
IPs, two or three approved public upstreams).  Nothing is learned from the
live objects.  A PASS here is a policy-contract PASS only; packet enforcement
is established separately by the kernel structural gate and packet tests.
"""
import ipaddress
import re

NTP_PORT = 123
INTERFACE = "ens160"
SELECTOR_TERM = re.compile(r"""\s*([A-Za-z0-9_./-]{1,253})\s*==\s*(?:"([^"]*)"|'([^']*)')\s*\Z""")
RULE_KEYS = {"action", "protocol", "source", "destination", "metadata", "ipVersion"}
PEER_KEYS = {"nets", "ports"}
POLICY_KEYS = {"order", "selector", "tier", "types", "ingress", "egress", "applyOnForward",
               "preDNAT", "doNotTrack"}
UNSET_ORDER = float("inf")


class ContractStop(ValueError):
    """The observed objects are outside the reviewed, modelled grammar."""


class ContractFail(ValueError):
    """The objects are understood and violate the NTP contract."""


def _items(document, kind):
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        raise ContractStop("Expected a kubectl List for " + kind)
    for item in document["items"]:
        if not isinstance(item, dict) or item.get("kind") != kind or not isinstance(item.get("spec"), dict):
            raise ContractStop("Unexpected object in " + kind + " list")
    return document["items"]


def parse_selector(expression):
    """Return {label: value} for `a == "x" && b == 'y'`; anything else stops."""
    if not isinstance(expression, str) or not expression.strip():
        raise ContractStop("Empty or non-string selector is not modelled")
    result = {}
    for term in expression.split("&&"):
        match = SELECTOR_TERM.fullmatch(term)
        if not match:
            raise ContractStop("Unsupported selector grammar: " + expression)
        key, value = match[1], match[2] if match[2] is not None else match[3]
        if key in result and result[key] != value:
            return None  # Contradictory equalities select nothing.
        result[key] = value
    return result


def selects(expression, labels):
    wanted = parse_selector(expression)
    return wanted is not None and all(labels.get(k) == v for k, v in wanted.items())


def host_endpoint(heps, host, address):
    """Exactly one HEP for the node, bound to ens160 and the inventory IP."""
    own = [item for item in _items(heps, "HostEndpoint") if item["spec"].get("node") == host]
    if len(own) != 1:
        raise ContractFail("%s: expected exactly one HostEndpoint, found %d" % (host, len(own)))
    spec, meta = own[0]["spec"], own[0].get("metadata", {})
    if spec.get("interfaceName") != INTERFACE:
        raise ContractFail("%s: HostEndpoint interfaceName must be %s" % (host, INTERFACE))
    if address not in (spec.get("expectedIPs") or []):
        raise ContractFail("%s: HostEndpoint expectedIPs lacks %s" % (host, address))
    if spec.get("ports") or spec.get("profiles"):
        raise ContractStop("%s: HostEndpoint named ports/profiles are not modelled" % host)
    labels = meta.get("labels") or {}
    if not isinstance(labels, dict):
        raise ContractStop("%s: malformed HostEndpoint labels" % host)
    return {"name": meta.get("name"), "labels": labels}


def _types(spec):
    if "types" in spec:
        if not isinstance(spec["types"], list) or not set(spec["types"]) <= {"Ingress", "Egress"}:
            raise ContractStop("Unsupported policy types")
        return set(spec["types"])
    # Calico default when types is omitted.
    return {"Ingress"} | ({"Egress"} if spec.get("egress") else set())


def _ports_match(ports):
    if ports is None:
        return True
    if not isinstance(ports, list) or not ports:
        raise ContractStop("Malformed port list")
    for port in ports:
        if isinstance(port, int) and not isinstance(port, bool):
            if port == NTP_PORT:
                return True
        elif isinstance(port, str) and re.fullmatch(r"[0-9]{1,5}:[0-9]{1,5}", port):
            low, high = (int(x) for x in port.split(":"))
            if low <= NTP_PORT <= high:
                return True
        else:
            raise ContractStop("Named or malformed port is not modelled: %r" % (port,))
    return False


def _nets(value):
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ContractStop("Malformed nets list")
    try:
        networks = [ipaddress.ip_network(item, strict=True) for item in value]
    except (TypeError, ValueError) as exc:
        raise ContractStop("Malformed CIDR in nets") from exc
    return [n for n in networks if n.version == 4]


def _covers(networks, address):
    return networks is None or any(ipaddress.ip_address(address) in n for n in networks)


def _udp123_rule(rule, direction, own_ip):
    """Return (action, peer_nets) when the rule can match UDP/123, else None."""
    if not isinstance(rule, dict) or not set(rule) <= RULE_KEYS | {"notProtocol", "icmp", "notICMP", "http"}:
        raise ContractStop("Unsupported rule field")
    protocol = rule.get("protocol")
    if protocol is not None and str(protocol).upper() not in ("UDP", "17"):
        return None  # Cannot match UDP; other fields are irrelevant to NTP.
    if set(rule) - RULE_KEYS:
        raise ContractStop("Rule field that can affect UDP/123 is not modelled")
    if rule.get("ipVersion") not in (None, 4):
        return None
    action = rule.get("action")
    if action not in ("Allow", "Deny", "Log", "Pass"):
        raise ContractStop("Unsupported rule action")
    peer_key, own_key = ("destination", "source") if direction == "egress" else ("source", "destination")
    peer, own = rule.get(peer_key) or {}, rule.get(own_key) or {}
    for side in (peer, own):
        if not isinstance(side, dict) or not set(side) <= PEER_KEYS:
            raise ContractStop("Rule selector/notNets/services match is not modelled")
    # The NTP port is always the destination port; source ports are not modelled.
    dport_side = rule.get("destination") or {}
    sport_side = rule.get("source") or {}
    if "ports" in sport_side:
        raise ContractStop("Source-port matching is not modelled")
    if not _ports_match(dport_side.get("ports")):
        return None
    if not _covers(_nets(own.get("nets")), own_ip):
        return None  # Restricted to another local address; cannot match this host.
    if action == "Pass":
        raise ContractStop("Pass (tier escape) can reach profiles/next tier; not modelled")
    return action, _nets(peer.get("nets"))


def applicable(gnps, labels, direction, own_ip):
    """Ordered (order, name) policies of the default tier selecting the HEP."""
    wanted = "Egress" if direction == "egress" else "Ingress"
    chosen = []
    for item in _items(gnps, "GlobalNetworkPolicy"):
        spec, name = item["spec"], item.get("metadata", {}).get("name")
        if not set(spec) <= POLICY_KEYS:
            raise ContractStop("%s: unsupported policy field %s" % (name, sorted(set(spec) - POLICY_KEYS)))
        if not selects(spec.get("selector"), labels):
            continue
        if spec.get("tier", "default") != "default":
            raise ContractStop("%s: non-default tier is not modelled" % name)
        if wanted not in _types(spec):
            continue
        if spec.get("doNotTrack"):
            raise ContractStop("%s: doNotTrack policy bypasses conntrack; not modelled" % name)
        if spec.get("preDNAT"):
            if direction == "egress":
                raise ContractStop("%s: preDNAT policy with egress is invalid" % name)
            for rule in spec.get("ingress") or []:
                if _udp123_rule(rule, direction, own_ip) is not None:
                    raise ContractStop("%s: preDNAT UDP/123 ingress is not modelled" % name)
            continue
        order = spec.get("order", UNSET_ORDER)
        if isinstance(order, bool) or not isinstance(order, (int, float)):
            raise ContractStop("%s: malformed order" % name)
        chosen.append((order, name, spec.get(direction) or []))
    return sorted(chosen, key=lambda x: (x[0], x[1]))


def evaluate(gnps, labels, direction, own_ip, approved_peers):
    """Check UDP/123 for one HEP and direction; return the matched rule trail."""
    approved = {str(ipaddress.IPv4Address(ip)) for ip in approved_peers}
    policies = applicable(gnps, labels, direction, own_ip)
    if not policies:
        raise ContractFail("No %s policy selects the HostEndpoint; traffic is not restricted" % direction)
    trail = []
    for _order, name, rules in policies:
        for index, rule in enumerate(rules):
            matched = _udp123_rule(rule, direction, own_ip)
            if matched is not None and matched[0] != "Log":
                trail.append({"policy": name, "rule": index, "action": matched[0],
                              "nets": None if matched[1] is None else [str(n) for n in matched[1]]})
    for entry in trail:
        if entry["action"] != "Allow":
            continue
        nets = entry["nets"]
        if nets is None or any(ipaddress.ip_network(n).prefixlen != 32 or n.split("/")[0] not in approved
                               for n in nets):
            raise ContractFail("%s rule %s/%d allows UDP/123 beyond the approved peers: %s"
                               % (direction, entry["policy"], entry["rule"], nets))
    verdicts = {}
    for peer in sorted(approved):
        first = next((e for e in trail if e["nets"] is None or
                      any(ipaddress.ip_address(peer) in ipaddress.ip_network(n) for n in e["nets"])), None)
        verdicts[peer] = first["action"] if first else "Deny(end-of-tier)"
        if verdicts[peer] != "Allow":
            raise ContractFail("Approved %s UDP/123 peer %s is not allowed" % (direction, peer))
    return {"direction": direction, "rules": trail, "approved_verdicts": verdicts,
            "unapproved_verdict": "Deny (no Allow rule reaches a non-approved peer)"}


def felix(configs, host):
    """Failsafe ports must not carry UDP/123; eBPF/nftables dataplanes stop."""
    result = {}
    for item in _items(configs, "FelixConfiguration"):
        name = item.get("metadata", {}).get("name")
        if name not in ("default", "node." + host):
            continue
        spec = item["spec"]
        if spec.get("bpfEnabled") or str(spec.get("nftablesMode", "Disabled")) not in ("Disabled", "Auto"):
            raise ContractStop("%s: eBPF/nftables dataplane is outside the kernel gate" % name)
        for key in ("failsafeOutboundHostPorts", "failsafeInboundHostPorts"):
            value = spec.get(key)
            if value is None:
                result[name + "." + key] = "UNSET(Calico default)"
                continue
            if not isinstance(value, list):
                raise ContractStop("Malformed " + key)
            for port in value:
                if not isinstance(port, dict):
                    raise ContractStop("Malformed failsafe entry")
                if str(port.get("protocol", "tcp")).lower() == "udp" and port.get("port") == NTP_PORT:
                    raise ContractFail("%s.%s opens UDP/123 outside policy" % (name, key))
            result[name + "." + key] = value
    if "default.failsafeOutboundHostPorts" not in result:
        raise ContractStop("FelixConfiguration default is missing")
    return result


def validate(heps, gnps, felixconfigs, hosts, source_host, upstreams):
    """Evaluate all six hosts. `hosts` maps inventory name -> IPv4."""
    source_ip = hosts[source_host]
    clients = sorted(ip for host, ip in hosts.items() if host != source_host)
    report = {}
    for host, address in sorted(hosts.items()):
        endpoint = host_endpoint(heps, host, address)
        egress_peers = upstreams if host == source_host else [source_ip]
        entry = {"host_endpoint": endpoint, "felix": felix(felixconfigs, host),
                 "egress": evaluate(gnps, endpoint["labels"], "egress", address, egress_peers)}
        if host == source_host:
            entry["ingress"] = evaluate(gnps, endpoint["labels"], "ingress", address, clients)
        report[host] = entry
    return report
