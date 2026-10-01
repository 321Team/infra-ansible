#!/usr/bin/env python3
"""Static contract gate for P1-HBR-01 AC-04 firewall remediation."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SOURCES = {
    "10.250.10.20",
    "10.1.93.105",
    "10.1.93.107",
    "10.1.93.108",
    "10.1.93.50",
    "10.1.93.102",
}

def require(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

vars_text = read("inventory/group_vars/hbr.yml")
script = read("templates/p1-hbr-01-ac04-filter.sh.j2")
unit = read("templates/p1-hbr-01-ac04-filter.service.j2")
apply = read("playbooks/p1-hbr-01-ac04-apply.yml")
verify = read("playbooks/p1-hbr-01-ac04-verify.yml")
rollback = read("playbooks/p1-hbr-01-ac04-rollback.yml")
precheck = read("playbooks/p1-hbr-01-ac04-precheck.yml")

require("hbr_ac04_backend: docker-user" in vars_text, "backend is not docker-user")
sources = set(re.findall(r"^\s+- address: ([0-9.]+)$", vars_text, re.M))
require(sources == EXPECTED_SOURCES, f"source set drift: {sorted(sources)}")
require("hbr_ac04_denied_same_l2_source: 10.1.93.26" in vars_text, "same-L2 negative drift")
require("hbr_ac04_mgmt_negative_source: 10.250.10.10" in vars_text, "mgmt negative drift")

require("DOCKER-USER" in script, "DOCKER-USER missing from filter template")
require("--ctorigdst" in script and "--ctorigdstport" in script,
        "conntrack original-destination match missing")
require("-I DOCKER-USER 1" in script, "managed jump is not inserted before Docker rules")
require("-j RETURN" in script, "approved-source RETURN rule missing")
require('-A "$CHAIN" -j DROP' in script, "default Harbor drop missing")
require("DOCKER-FORWARD" not in script, "template must not mutate DOCKER-FORWARD")
require(re.search(r"\bDOCKER\b", script.replace("DOCKER-USER", "")) is None,
        "template must not mutate Docker-owned DOCKER chain")

for token in ("After=docker.service firewalld.service", "Requires=docker.service",
              "PartOf=docker.service", "WantedBy=docker.service", "RemainAfterExit=yes"):
    require(token in unit, f"systemd persistence contract missing: {token}")

for gate in ("hbr_ac04_change_approved", "hbr_ac04_ui_fallback_confirmed",
             "hbr_ac04_change_window_confirmed"):
    require(gate in apply, f"apply gate missing: {gate}")

require("firewall-cmd --reload" not in apply, "firewalld reload is prohibited")
require("--remove-port={{ hbr_ac04_generic_port }}" in apply,
        "supplementary generic INPUT 443 removal missing")
require("hbr_ac04_filter_service" in apply, "persistence service not applied")
require("hbr_ac04_filter_script" in verify and "verify" in verify,
        "DOCKER-USER verifier missing")
require("CONFIG_PASS_RUNTIME_TRAFFIC_TESTS_PENDING" in verify,
        "verify must not claim AC acceptance")
require("Restore generic 443 before removing allow rules" in rollback,
        "rollback outage-safe order marker missing")
require("hbr_ac04_original.schema == 2" in rollback,
        "rollback state schema binding missing")
require("PRECHECK_PASS_RUNTIME_NOT_CHANGED" in precheck,
        "precheck boundary marker missing")

for text, label in ((apply, "apply"), (verify, "verify"), (rollback, "rollback")):
    require("DOCKER-FORWARD" not in text, f"{label} must not modify Docker-owned DOCKER-FORWARD")
    require("iptables -A DOCKER" not in text and "iptables -I DOCKER" not in text,
            f"{label} must not modify Docker-owned DOCKER chain")

print("P1_HBR_AC04_STATIC_CONTRACT=PASS")
