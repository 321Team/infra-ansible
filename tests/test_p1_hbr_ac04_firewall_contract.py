#!/usr/bin/env python3
"""Static contract tests for P1-HBR-01 AC-04 firewall remediation."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VARS = (ROOT / "inventory/group_vars/harbor.yml").read_text()
APPLY = (ROOT / "playbooks/p1-hbr-ac04-firewall-apply.yml").read_text()
ROLLBACK = (ROOT / "playbooks/p1-hbr-ac04-firewall-rollback.yml").read_text()
PRECHECK = (ROOT / "playbooks/p1-hbr-ac04-firewall-precheck.yml").read_text()
VERIFY = (ROOT / "playbooks/p1-hbr-ac04-firewall-verify.yml").read_text()

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

assert "--reload" not in APPLY
assert "--reload" not in ROLLBACK

# Apply must stage source-specific allows before removing the broad generic port.
for permanent in ("--permanent",):
    pass
assert APPLY.index("--add-rich-rule=") < APPLY.index("--remove-port=")

# Rollback must restore broad pre-change reachability before removing the
# source-specific rules introduced by this change.
assert ROLLBACK.index("--add-port=") < ROLLBACK.index("--remove-rich-rule=")

for content in (PRECHECK, APPLY, VERIFY, ROLLBACK):
    assert "hosts: harbor" in content
    assert "ansible_host == '10.1.93.54'" in content or content is ROLLBACK

assert "original-state.json" in APPLY
assert "PRESTATE_SHA256SUMS" in APPLY
assert "PRESTATE_SHA256SUMS" in ROLLBACK
assert "original_state.source_records == p1_hbr_ac04_sources" in ROLLBACK

print("P1-HBR-AC04_FIREWALL_CONTRACT=PASS")
print(f"APPROVED_SOURCE_COUNT={len(actual)}")
print("DENY_PROBE=10.1.93.26/32")
