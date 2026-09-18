"""Shared technical constraints for the existing chrony iburst workflow.

Catalog membership is NOT service-policy approval or permission to send NTP
requests. The controller still requires source/network/recovery references;
the deployed path must satisfy those records and the runtime gates.
"""
import ipaddress


# This is deliberately a closed catalog. Providers needing a different poll or
# burst policy (including NIST/NICT), unverified replacement addresses, and
# arbitrary global IPs cannot reach the unchanged iburst implementation.
UPSTREAM_CATALOG = {
    "162.159.200.1": {"operator": "Cloudflare", "chrony_options": "iburst"},
    "162.159.200.123": {"operator": "Cloudflare", "chrony_options": "iburst"},
    "194.58.200.20": {"operator": "Netnod", "chrony_options": "iburst"},
}

# Keep global-unicast validation stable across Python ipaddress releases.
SPECIAL_IPV4 = tuple(ipaddress.IPv4Network(value) for value in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
))


def literal_ipv4(value):
    if not isinstance(value, str):
        raise ValueError("Each upstream must be a literal IPv4 string")
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Upstreams must be IPv4 literals, not DNS names, CIDRs, or chrony options") from exc
    if str(address) != value:
        raise ValueError("Upstream must use canonical literal IPv4 notation")
    return address


def validate_public_target(value):
    address = literal_ipv4(value)
    if (not address.is_global or address.is_multicast or address.is_reserved
            or any(address in network for network in SPECIAL_IPV4)):
        raise ValueError("Upstreams must be canonical unicast public IPv4 addresses outside special-purpose ranges")
    if value not in UPSTREAM_CATALOG:
        raise ValueError("Unsupported iburst upstream: %s; provider timing and use policy require separate review" % value)
    return value


def validate_public_upstreams(value):
    if not isinstance(value, list) or not 2 <= len(value) <= 3:
        raise ValueError("Source migration requires two or three distinct supported public IPv4 upstreams")
    validated = [validate_public_target(item) for item in value]
    if len(set(validated)) != len(validated):
        raise ValueError("The two or three public upstream addresses must be distinct")
    return validated


def validate_probe_target(value):
    literal_ipv4(value)
    # Local packet tests inject a runner that substitutes loopback only after
    # this validation; production targets stay in the reviewed closed set.
    if value == "10.1.93.102":
        return value
    return validate_public_target(value)
