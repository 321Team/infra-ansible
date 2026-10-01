#!/usr/bin/env python3
"""Static contract tests for P1-HBR-01 AC-04 firewall remediation."""

from pathlib import Path
import subprocess
import re

ROOT = Path(__file__).resolve().parents[1]
VARS = (ROOT / "inventory/group_vars/harbor.yml").read_text()
NFT = (ROOT / "templates/p1-hbr-ac04.nft.j2").read_text()
UNIT = (ROOT / "files/p1-hbr-ac04-firewall.service").read_text()
PRECHECK = (ROOT / "playbooks/p1-hbr-ac04-firewall-precheck.yml").read_text()
APPLY = (ROOT / "playbooks/p1-hbr-ac04-firewall-apply.yml").read_text()
VERIFY = (ROOT / "playbooks/p1-hbr-ac04-firewall-verify.yml").read_text()
ROLLBACK = (ROOT / "playbooks/p1-hbr-ac04-firewall-rollback.yml").read_text()

EXPECTED = {
    "10.250.10.20/32": "baseline",
    "10.1.93.105/32": "baseline",
    "10.1.93.107/32": "baseline",
    "10.1.93.108/32": "baseline",
    "10.1.93.50/32": "temporary-edge",
    "10.1.93.102/32": "temporary-management",
}

records = re.findall(
    r"- address:\s+([^\s]+)\s+classification:\s+([^\s]+)",
    VARS,
)
actual = dict(records)
assert actual == EXPECTED, (actual, EXPECTED)
assert "p1_hbr_ac04_deny_probe_source: 10.1.93.26/32" in VARS
assert "10.1.93.26/32" not in actual

for token in (
    "p1_hbr_ac04_source_set_approved",
    "p1_hbr_ac04_control01_ui_confirmed",
    "p1_hbr_ac04_change_window_approved",
):
    assert token in APPLY, token

# Enforcement must be a dedicated nftables table before Docker's filter hook.
for token in (
    "table inet p1_hbr_ac04",
    "hook forward priority -1",
    "ct status dnat",
    "ct original ip daddr 10.1.93.54",
    "ct original proto-dst",
    "ip saddr @allowed_v4",
    "counter drop",
):
    assert token in NFT, token

# Docker 443 DNAT detection must not depend on iptables option ordering.

# Execute the Docker 443 DNAT detector against representative iptables output.
awk_program = (
    '$1 == "-A" && $2 == "DOCKER" && '
    '$0 ~ /(^| )-p tcp( |$)/ && '
    '$0 ~ /(^| )--dport 443( |$)/ && '
    '$0 ~ /(^| )-j DNAT( |$)/ && '
    '$0 ~ /(^| )--to-destination [^ ]*:8443( |$)/ '
    '{ print; found=1 } '
    'END { exit(found ? 0 : 1) }'
)

positive_rule = (
    "-A DOCKER ! -i br-test -p tcp -m tcp "
    "--dport 443 -j DNAT "
    "--to-destination 172.18.0.11:8443\n"
)

negative_rule = (
    "-A DOCKER ! -i br-test -p tcp -m tcp "
    "--dport 80 -j DNAT "
    "--to-destination 172.18.0.11:8080\n"
)

positive = subprocess.run(
    ["awk", awk_program],
    input=positive_rule,
    text=True,
    capture_output=True,
)

assert positive.returncode == 0, positive.stderr
assert "--dport 443" in positive.stdout

negative = subprocess.run(
    ["awk", awk_program],
    input=negative_rule,
    text=True,
    capture_output=True,
)

assert negative.returncode != 0

assert "--dport 443 .* -j DNAT --to-destination" not in PRECHECK

# No approved IPv6 source exists, so forwarded published 443 IPv6 is denied.
assert "meta nfproto ipv6" in NFT
assert "deny IPv6" in NFT

# Persistence is ordered before Docker at boot and after firewalld.
assert "Before=docker.service" in UNIT
assert "After=firewalld.service" in UNIT
assert "ExecStart=/usr/sbin/nft -f /etc/nftables/p1-hbr-ac04.nft" in UNIT
assert "WantedBy=multi-user.target" in UNIT

# The global Docker/firewalld integration mode must not be changed.
for content in (APPLY, ROLLBACK):
    assert "StrictForwardPorts=yes" not in content
    assert "firewall-cmd --reload" not in content
    assert "DOCKER-FORWARD" not in content
    assert "DOCKER-USER -I" not in content
    assert "iptables -I" not in content

# Apply must activate and verify the guard before removing broad generic 443.
assert APPLY.index("state: started") < APPLY.index("--remove-port=")
assert APPLY.index("Read active managed nft table") < APPLY.index("--remove-port=")

# Rollback restores broad pre-change reachability before removing the guard.
assert ROLLBACK.index("--add-port=") < ROLLBACK.index("state: stopped")

for content in (PRECHECK, APPLY, VERIFY, ROLLBACK):
    assert "hosts: harbor" in content
    assert "ansible_host == '10.1.93.54'" in content

assert "nft, -c, -f, -" in PRECHECK
assert "PRESTATE_SHA256SUMS" in APPLY
assert "PRESTATE_SHA256SUMS" in ROLLBACK
assert "original_state.source_records == p1_hbr_ac04_sources" in ROLLBACK
assert "PRESTATE_SHA256SUMS" in VERIFY
assert "iptables_before_rules" in VERIFY
assert "iptables_after_rules" in VERIFY
assert "ip6tables_before_rules" in VERIFY
assert "ip6tables_after_rules" in VERIFY
assert "Docker-managed iptables rules are unchanged" in VERIFY
assert "sealed_prestate" in PRECHECK
assert "sealed_prestate_before" in APPLY
assert "state_dir" in PRECHECK
assert "state_dir_before" in APPLY
assert "prestate_timestamp.stdout" in APPLY
assert "applied_timestamp.stdout" in APPLY
assert "rollback_timestamp.stdout" in ROLLBACK
assert "'captured_at': ansible_date_time.iso8601" not in APPLY
assert "'applied_at': ansible_date_time.iso8601" not in APPLY
assert "'rolled_back_at': ansible_date_time.iso8601" not in ROLLBACK

print("P1-HBR-AC04_FIREWALL_CONTRACT=PASS")
print(f"APPROVED_SOURCE_COUNT={len(actual)}")
print("ENFORCEMENT=NFT_FORWARD_PRIORITY_MINUS_1")
print("DENY_PROBE=10.1.93.26/32")
