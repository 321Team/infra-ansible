"""Structural check that Felix programmed the ens160 HostEndpoint egress path.

This does not interpret Calico rule semantics (the policy contract does that
from the Calico API).  It proves only the kernel wiring that the contract
relies on, and exposes DROP counters of the HostEndpoint egress chain tree so
negative packet tests can attribute a drop to Calico policy:

  filter OUTPUT (first rule) -> cali-OUTPUT -> cali-to-host-endpoint
      -> [-o ens160 dispatch] -> exactly one cali-th-* chain -> DROP present

Input is `iptables-save -c` (IPv4).  Unsupported syntax stops.  Only the
filter path (`! --ctstate DNAT`) is checked: host-originated chronyd UDP is not
DNAT.  The mangle POSTROUTING copy for DNAT connections is out of scope.
"""
import hashlib
import json
import re
import shlex

INTERFACE = "ens160"
MAX_BYTES = 8 * 1024 * 1024
COUNTER = re.compile(r"\[([0-9]+):([0-9]+)\] (-A .*)\Z")
LEGACY_CHAIN = "FDS_NTP_0101"


class KernelStop(ValueError):
    pass


def _target(row):
    found = [i for i, word in enumerate(row) if word in ("-j", "-g")]
    if len(found) > 1 or (found and found[0] + 1 >= len(row)):
        raise KernelStop("Ambiguous chain transfer")
    return row[found[0] + 1] if found else None


def parse(text):
    if not isinstance(text, str) or "\x00" in text or len(text.encode()) > MAX_BYTES:
        raise KernelStop("Invalid or oversized iptables-save evidence")
    tables, current = {}, None
    for raw in text.splitlines():
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("*"):
            if current is not None or raw[1:] in tables:
                raise KernelStop("Nested or duplicate table")
            current = tables[raw[1:]] = {"policies": {}, "rules": {}}
        elif raw == "COMMIT":
            if current is None:
                raise KernelStop("Unexpected COMMIT")
            current = None
        elif current is None:
            raise KernelStop("Content outside a table")
        elif raw.startswith(":"):
            parts = raw[1:].split()
            if len(parts) != 3:
                raise KernelStop("Unsupported chain declaration")
            current["policies"][parts[0]] = parts[1]
            current["rules"].setdefault(parts[0], [])
        else:
            match = COUNTER.fullmatch(raw)
            if not match:
                raise KernelStop("Rules must carry iptables-save -c counters")
            try:
                row = tuple(shlex.split(match[3]))
            except ValueError as exc:
                raise KernelStop("Malformed rule tokens") from exc
            if len(row) < 2 or row[1] not in current["rules"]:
                raise KernelStop("Rule for undeclared chain")
            current["rules"][row[1]].append({"packets": int(match[1]), "row": row})
    if current is not None or "filter" not in tables:
        raise KernelStop("Incomplete iptables-save evidence")
    return tables


def _out_iface_matches(row):
    if "-o" not in row:
        return None
    value = row[row.index("-o") + 1]
    if value.startswith("!"):
        raise KernelStop("Negated interface dispatch is not modelled")
    return value == INTERFACE or (value.endswith("+") and INTERFACE.startswith(value[:-1]))


def _reachable(table, root):
    seen, stack = [], [root]
    while stack:
        chain = stack.pop()
        if chain in seen:
            continue
        if chain not in table["rules"]:
            raise KernelStop("Missing chain " + chain)
        seen.append(chain)
        for rule in table["rules"][chain]:
            target = _target(rule["row"])
            if target in table["rules"]:
                stack.append(target)
    return seen


def host_endpoint_chain(tables):
    """Return the single cali-th-* chain reached for ens160 egress."""
    table = tables["filter"]
    output = table["rules"].get("OUTPUT", [])
    if not output or _target(output[0]["row"]) != "cali-OUTPUT":
        raise KernelStop("filter OUTPUT does not start with cali-OUTPUT")
    if not any(_target(r["row"]) == "cali-to-host-endpoint" for r in table["rules"].get("cali-OUTPUT", [])):
        raise KernelStop("cali-OUTPUT does not dispatch to cali-to-host-endpoint")
    found, stack, seen = set(), ["cali-to-host-endpoint"], set()
    while stack:
        chain = stack.pop()
        if chain in seen:
            continue
        seen.add(chain)
        if chain not in table["rules"]:
            raise KernelStop("Missing dispatch chain " + chain)
        for rule in table["rules"][chain]:
            target = _target(rule["row"])
            if target is None or target not in table["rules"]:
                continue
            if _out_iface_matches(rule["row"]) is False:
                continue
            if target.startswith("cali-th-"):
                found.add(target)
            elif target.startswith("cali-to-host-endpoint") or target.startswith("cali-to-hep"):
                stack.append(target)
    if len(found) != 1:
        raise KernelStop("Expected exactly one cali-th-* chain for %s, found %s" % (INTERFACE, sorted(found)))
    chain = found.pop()
    # The conntrack INVALID drop does not enforce policy; require a drop that
    # is not conditioned on connection state (Felix end-of-tier/no-profile).
    if not any(_target(r["row"]) == "DROP" and "--ctstate" not in r["row"] for r in table["rules"][chain]):
        raise KernelStop(chain + " has no end-of-tier DROP rule; HostEndpoint not enforced")
    return chain


def raw_untracked(tables):
    """doNotTrack policies render into raw; any ens160 rule there stops."""
    raw = tables.get("raw", {"rules": {}})
    rows = raw["rules"].get("cali-to-host-endpoint", [])
    hits = [" ".join(r["row"]) for r in rows if _out_iface_matches(r["row"]) is not False]
    if hits:
        raise KernelStop("Untracked (raw) host-endpoint rules for ens160 are not modelled")
    return len(rows)


def drop_packets(tables, chain):
    table = tables["filter"]
    return sum(rule["packets"] for name in _reachable(table, chain)
               for rule in table["rules"][name] if _target(rule["row"]) == "DROP")


def structure(text):
    tables = parse(text)
    chain = host_endpoint_chain(tables)
    table = tables["filter"]
    tree = _reachable(table, chain)
    projection = {name: [" ".join(r["row"]) for r in table["rules"][name]] for name in sorted(tree)}
    return {"host_endpoint_chain": chain,
            "chain_tree": sorted(tree),
            "raw_host_endpoint_rules": raw_untracked(tables),
            "cali_output_rules": [" ".join(r["row"]) for r in table["rules"]["cali-OUTPUT"]],
            "legacy_ntp_chain_present": LEGACY_CHAIN in table["rules"],
            "drop_packets": drop_packets(tables, chain),
            # Counter-free digest for start/end drift comparison within one run.
            "structure_sha256": hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()}
