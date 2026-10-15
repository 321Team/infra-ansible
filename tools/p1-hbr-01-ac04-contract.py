#!/usr/bin/env python3
"""Static contract gate for P1-HBR-01 AC-04 nftables remediation."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SOURCES = {
    "10.250.10.20",
    "10.1.93.105",
    "10.1.93.107",
    "10.1.93.108",
    "10.1.93.102",
}

def require(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

vars_text = read("inventory/group_vars/hbr.yml")
nft = read("templates/p1-hbr-01-ac04.nft.j2")
unit = read("templates/p1-hbr-01-ac04-guard.service.j2")
precheck = read("playbooks/p1-hbr-01-ac04-precheck.yml")
apply = read("playbooks/p1-hbr-01-ac04-apply.yml")
verify = read("playbooks/p1-hbr-01-ac04-verify.yml")
rollback = read("playbooks/p1-hbr-01-ac04-rollback.yml")
nft_verify = read("playbooks/tasks/p1-hbr-01-ac04-nft-verify.yml")
nft_fixture_test = read("tests/test_p1_hbr_ac04_nft_fixture.py")
nft_fixture = read("tests/fixtures/p1_hbr_ac04/nftables-v1.1.5-list.txt")

require("hbr_ac04_backend: nftables-guard" in vars_text, "backend is not nftables-guard")
require("hbr_ac04_nft_family: inet" in vars_text, "nft family drift")
require("hbr_ac04_nft_table: p1_hbr_ac04" in vars_text, "nft table drift")
require("hbr_ac04_nft_chain: forward_guard" in vars_text, "nft chain drift")
require("hbr_ac04_nft_priority: -1" in vars_text, "nft priority drift")
require('  - "1.1.5"' in vars_text, "fixture-validated nftables version missing")

sources = set(re.findall(r"^\s+- address: ([0-9.]+)$", vars_text, re.M))
require(sources == EXPECTED_SOURCES, f"source set drift: {sorted(sources)}")
require("hbr_ac04_denied_same_l2_source: 10.1.93.26" in vars_text, "same-L2 negative drift")
require("hbr_ac04_mgmt_negative_source: 10.250.10.10" in vars_text, "mgmt negative drift")

for token in (
    "destroy table {{ hbr_ac04_nft_family }} {{ hbr_ac04_nft_table }}",
    "type filter hook forward priority {{ hbr_ac04_nft_priority }}; policy accept;",
    'iifname "{{ hbr_ac04_interface }}"',
    "ct status dnat",
    "ct original ip daddr {{ hbr_ac04_host_ip }}",
    "ct original protocol tcp",
    "ct original proto-dst {{ hbr_ac04_port }}",
    "ip saddr @approved_v4",
    "P1-HBR-01-AC04 approved IPv4",
    "P1-HBR-01-AC04 deny unapproved IPv4",
    "meta nfproto ipv6",
    "P1-HBR-01-AC04 deny IPv6 published 443",
):
    require(token in nft, f"nft guard contract missing: {token}")

require(nft.count('comment "P1-HBR-01-AC04') == 3, "nft guard must have exactly 3 managed rules")
require("DOCKER-USER" not in nft and "DOCKER-FORWARD" not in nft,
        "nft template must not touch Docker-managed chains")
require("table inet firewalld" not in nft, "nft template must not touch firewalld managed table")

for token in (
    "After=firewalld.service",
    "Before=docker.service",
    "RequiredBy=docker.service",
    "RemainAfterExit=yes",
):
    require(token in unit, f"fail-closed systemd contract missing: {token}")
# firewalld ordering must not introduce lifecycle propagation into Docker.
for directive in ("Requires", "Requisite", "BindsTo", "PartOf", "Wants", "Upholds"):
    require(not re.search(r"^" + directive + r"=.*\bfirewalld[.]service\b", unit, re.M),
            "guard must only order after firewalld, not couple its lifecycle: " + directive)
require("After=docker.service" not in unit, "guard must not start after Docker")
require("WantedBy=docker.service" not in unit, "guard must be a required dependency, not only wanted")
require("ExecStop=" not in unit, "service stop must not remove the fail-closed guard")

for gate in (
    "hbr_ac04_change_approved",
    "hbr_ac04_ui_fallback_confirmed",
    "hbr_ac04_change_window_confirmed",
):
    require(gate in apply, f"apply gate missing: {gate}")

require("schema: 3" in apply, "apply prestate schema must be 3")
require("nft-ruleset-before.txt" in apply, "nft prestate source not preserved")
require("PRESTATE_SHA256SUMS" in apply, "prestate SHA256 seal missing from apply")
require(apply.find("PRESTATE_SHA256SUMS") < apply.find("Render dedicated nft guard"), "prestate must be sealed before guard rendering")
require("PRESTATE_SHA256SUMS" in rollback, "rollback does not verify prestate SHA256 seal")
require("nft -c" not in apply or "hbr_ac04_nft_file" in apply, "nft check must target managed source")
require("hbr_ac04_guard_service" in apply, "guard service not applied")
require("Assert fail-closed boot ordering before INPUT hardening" in apply,
        "boot-order verification missing")
require(apply.find("Start nft guard") < apply.find("Remove permanent generic INPUT 443"),
        "guard must start before generic 443 removal")
require("firewall-cmd --reload" not in apply, "firewalld reload is prohibited")
require("--add-rich-rule" not in apply, "latest design must not add INPUT rich rules")
require("DOCKER-USER source allowlist" not in apply, "stale DOCKER-USER apply text remains")
require("CONFIG_PASS_RUNTIME_TRAFFIC_TESTS_PENDING" in verify,
        "verify must stop short of Runtime acceptance")
require("hbr_ac04_original.schema == 3" in verify,
        "verify state binding must use schema 3")
require("hbr_ac04_original.schema == 3" in rollback,
        "rollback state binding must use schema 3")
require(rollback.find("Restore permanent generic INPUT 443") < rollback.find("Disable Docker guard dependency before stopping guard"),
        "rollback must restore generic 443 before removing guard")
require("nft_guard=REMOVED" in rollback, "rollback result marker missing")
require("PRECHECK_PASS_RUNTIME_NOT_CHANGED" in precheck, "precheck boundary marker missing")
require("hbr_ac04_nft_version is version('1.0.6', '>=')" in precheck,
        "precheck must require nftables >=1.0.6")
require("hbr_ac04_nft_version is version('1.0.6', '>=')" in apply,
        "apply must re-check nftables >=1.0.6")
require("hbr_ac04_rollback_nft_version is version('1.0.6', '>=')" in rollback,
        "rollback must require nftables >=1.0.6")

require("hbr_ac04_nft_version in hbr_ac04_nft_supported_versions" in precheck,
        "precheck must require fixture-validated nftables version")
require("hbr_ac04_nft_version in hbr_ac04_nft_supported_versions" in apply,
        "apply must require fixture-validated nftables version")
require("hbr_ac04_nft_version in hbr_ac04_nft_supported_versions" in nft_verify,
        "live verifier must require fixture-validated nftables version")

apply_disable = apply.find("Rescue - disable Docker guard dependency before stopping guard")
apply_reload = apply.find("Rescue - reload dependency graph after disabling guard")
apply_stop = apply.find("Rescue - stop nft guard after dependency detach")
require(-1 not in (apply_disable, apply_reload, apply_stop)
        and apply_disable < apply_reload < apply_stop,
        "apply rescue must disable -> daemon-reload -> stop guard")

for token in (
    "Rescue - require Docker active after dependency detach",
    "Rescue - verify guard is no longer active",
    "Rescue - require safe service state before nft table removal",
):
    require(token in apply, f"apply rescue safety assertion missing: {token}")

require("Check managed guard unit before service operations" in rollback,
        "rollback must inspect unit existence before service operations")
require(rollback.count("when: hbr_ac04_rollback_guard_unit.stat.exists") == 2,
        "rollback disable and stop must tolerate a not-yet-created unit")

rollback_disable = rollback.find("Disable Docker guard dependency before stopping guard")
rollback_reload = rollback.find("Reload dependency graph after disabling guard")
rollback_stop = rollback.find("Stop nft guard after dependency detach")
require(-1 not in (rollback_disable, rollback_reload, rollback_stop)
        and rollback_disable < rollback_reload < rollback_stop,
        "rollback must disable -> daemon-reload -> stop guard")

for token in (
    "P1-HBR-01-AC04 approved IPv4",
    "P1-HBR-01-AC04 deny unapproved IPv4",
    "P1-HBR-01-AC04 deny IPv6 published 443",
):
    require(token in nft_verify, f"live nft verifier missing: {token}")

for token in (
    "hbr_ac04_nft_table_set_count",
    "hbr_ac04_nft_table_chain_count",
    "hbr_ac04_nft_chain_meta_lines",
    "hbr_ac04_nft_rule_lines_normalized",
    "hbr_ac04_nft_expected_rules_normalized",
    "Extra objects or rules, rule reordering, expression drift",
):
    require(token in nft_verify, f"exact live nft verifier missing: {token}")

require("hbr_ac04_nft_rule_lines_normalized | length == 3" in nft_verify,
        "live nft verifier must require exactly three rules")
require("hbr_ac04_nft_table_set_count | int == 1" in nft_verify,
        "live nft verifier must reject extra managed sets")
require("hbr_ac04_nft_table_chain_count | int == 1" in nft_verify,
        "live nft verifier must reject extra managed chains")
require("== hbr_ac04_nft_expected_rules_normalized" in nft_verify,
        "live nft verifier must compare ordered canonical rules exactly")
require("counter packets [0-9]+ bytes [0-9]+" in nft_verify,
        "live nft verifier must normalize volatile counters")

for token in ("ct status 0x20", "ct protocol 6", "meta nfproto 10"):
    require(token in nft_verify, f"nftables 1.1.5 canonical token missing: {token}")

expected_block = nft_verify.split("hbr_ac04_nft_expected_rules:", 1)[1].split(
    "- name: Normalize reviewed rule contract", 1
)[0]
for stale in ("ct status dnat", "ct original protocol tcp", "meta nfproto ipv4"):
    require(stale not in expected_block, f"pre-list nft alias remains in expected rules: {stale}")

for token in (
    "nftables v1.1.5 (Commodore Bullmoose #6)",
    "LOAD_RC=0",
    "TABLE_RC=0",
    "CHAIN_RC=0",
    'iifname "ens160" ct status 0x20',
    "meta nfproto 10",
):
    require(token in nft_fixture, f"same-version nft fixture missing: {token}")

require("P1HbrAc04NftFixtureTest" in nft_fixture_test,
        "fixture-backed nft verifier unittest missing")
require("EXPECTED_RULES" in nft_fixture_test and "normalize_rule" in nft_fixture_test,
        "fixture unittest does not exercise canonical rule normalization")

old_script = read("templates/p1-hbr-01-ac04-filter.sh.j2")
old_unit = read("templates/p1-hbr-01-ac04-filter.service.j2")
require("REJECTED_BACKEND" in old_script and "exit 64" in old_script,
        "rejected DOCKER-USER script is not hard-disabled")
require("REJECTED_BACKEND" in old_unit and "ExecStart=/usr/bin/false" in old_unit,
        "rejected DOCKER-USER unit is not hard-disabled")

for text, label in ((precheck, "precheck"), (apply, "apply"), (verify, "verify"), (rollback, "rollback")):
    require("hbr_ac04_filter_script" not in text, f"stale filter-script variable remains in {label}")
    require("hbr_ac04_filter_service" not in text, f"stale DOCKER-USER service variable remains in {label}")
    require("hbr_ac04_chain" not in text, f"stale DOCKER-USER chain variable remains in {label}")

# Bind failure recovery and integrity gates to task structure, not comments.
import yaml
for source, key in ((apply, 'rescue'), (rollback, 'block')):
    task_list = yaml.safe_load(source)[-1]['tasks']
    recovery = next(t[key] for t in task_list if key in t)
    stop = next(i for i,t in enumerate(recovery)
                if t.get('ansible.builtin.systemd_service', {}).get('state') == 'stopped')
    detach = next(i for i,t in enumerate(recovery)
                  if 'require confirmed dependency detach' in t['name'])
    query = next(i for i,t in enumerate(recovery)
                 if '--property=Requires' in t.get('ansible.builtin.command', {}).get('argv', []))
    require(query < detach < stop, 'confirmed dependency detach must precede stop')
    for t in recovery[:stop]:
        if 'ansible.builtin.systemd_service' in t or t is recovery[query]:
            require('failed_when' not in t and not t.get('ignore_errors'),
                    'dependency detach/query failures must stop recovery')
verification = yaml.safe_load(verify)[-1]['tasks']
seal = next(i for i,t in enumerate(verification)
            if t.get('ansible.builtin.command', {}).get('argv') ==
            ['sha256sum', '--check', '--strict', 'PRESTATE_SHA256SUMS'])
read_state = next(i for i,t in enumerate(verification) if 'ansible.builtin.slurp' in t)
require(seal < read_state, 'prestate seal must be checked before state consumption')
require('failed_when' not in verification[seal] and not verification[seal].get('ignore_errors'),
        'prestate hash failure must stop verification')

print("P1_HBR_AC04_STATIC_CONTRACT=PASS")

