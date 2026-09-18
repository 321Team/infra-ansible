#!/usr/bin/env python3
"""Offline tests only; fixture addresses are not proposed NTP services."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'tools/render-ntp-egress.py'
SPEC = importlib.util.spec_from_file_location('ntp_egress', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# Offline fixtures only; three addresses from TWO providers, never contacted.
FIXTURE_UPSTREAMS = ['162.159.200.1', '162.159.200.123', '194.58.200.20']


class EgressContractTests(unittest.TestCase):
    def setUp(self):
        self.variables = {
            'cr_ntp_change_id': 'CR-P1-NTP-01-01',
            'cr_ntp_source_host': 'k8s-control01',
            'cr_ntp_source_ip': '10.1.93.102',
            'cr_ntp_client_ips': list(MODULE.CLIENT_IPS),
            'cr_ntp_source_upstreams': list(FIXTURE_UPSTREAMS),
        }

    def contract(self, variables=None):
        return MODULE.build_contract(variables or self.variables, 'f' * 64)

    def test_narrow_contract_retains_pending_review(self):
        result = self.contract()
        public = result['public_ntp_egress']
        self.assertEqual(result['status'], 'CANDIDATE_NOT_APPLIED')
        self.assertEqual(result['addresses_owner_policy_status'], 'PENDING')
        self.assertEqual(result['enforcement_status'], 'NOT_PERFORMED')
        self.assertFalse(result['input']['effective_ansible_vars_verified'])
        self.assertEqual(public['source_before_snat'], '10.1.93.102/32')
        self.assertEqual(public['destination_cidrs'],
                         [address + '/32' for address in FIXTURE_UPSTREAMS])
        self.assertEqual(public['protocol'], 'udp')
        self.assertEqual(public['destination_port'], 123)
        self.assertIsNone(public['source_port']['fixed_port'])
        self.assertEqual(public['source_port']['selection'], 'OS_SELECTED_EPHEMERAL')
        self.assertEqual(public['return_traffic'], 'STATEFUL_REPLIES_ONLY')
        self.assertFalse(public['unsolicited_inbound_permitted'])
        self.assertNotIn('0.0.0.0/0', json.dumps(result))
        self.assertFalse(result['five_client_policy']['direct_public_ntp_permitted_by_design'])
        self.assertFalse(result['five_client_policy']['effective_enforcement_verified'])
        self.assertEqual(result['implementation_review']['required_rule_count'], 'UNDETERMINED')
        self.assertFalse(result['implementation_review']['applies_firewall_configuration'])

    def test_unselected_or_wrong_count_is_rejected(self):
        for value in (None, [], {}, '8.8.8.8', FIXTURE_UPSTREAMS[:1], FIXTURE_UPSTREAMS + [FIXTURE_UPSTREAMS[0]]):
            with self.subTest(value=value), self.assertRaises(MODULE.ContractError):
                MODULE.public_upstreams(value)

    def test_two_and_three_known_addresses_accepted(self):
        for values in (FIXTURE_UPSTREAMS[:2], FIXTURE_UPSTREAMS[::2], FIXTURE_UPSTREAMS):
            with self.subTest(values=values):
                self.assertEqual(MODULE.public_upstreams(values), values)
                candidate = dict(self.variables, cr_ntp_source_upstreams=values)
                contract = self.contract(candidate)
                self.assertEqual(contract['public_ntp_egress']['destination_cidrs'],
                                 [ip + '/32' for ip in values])

    def test_unsupported_providers_rejected_before_output_mutation(self):
        for address in ('8.8.8.8', '132.163.96.1', '129.6.15.28'):
            with self.subTest(address=address), tempfile.TemporaryDirectory() as temp:
                path, output = Path(temp) / 'vars.yml', Path(temp) / 'review.json'
                value = dict(self.variables, cr_ntp_source_upstreams=[FIXTURE_UPSTREAMS[0], address])
                path.write_text(yaml.safe_dump(value))
                before = path.read_bytes()
                process = subprocess.run([sys.executable, str(SCRIPT), '--vars-file', str(path),
                                          '--output', str(output)], capture_output=True,
                                         text=True, timeout=10)
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertFalse(output.exists())
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(process.stdout, '')

    def test_unsafe_or_ambiguous_destinations_are_rejected(self):
        invalid = ['0.0.0.0', '0.0.0.0/0', '10.0.0.1', '172.16.0.1',
                   '192.168.1.1', '127.0.0.1', '169.254.1.1', '100.64.0.1',
                   '224.0.0.1', '240.0.0.1', '255.255.255.255', '192.0.2.1',
                   '198.51.100.1', '203.0.113.1', '198.18.0.1', '192.0.0.8',
                   '192.88.99.1', '::1', '2606:4700:4700::1111', 'ntp.example.org',
                   '1.1.1.1/32', '1.1.1.1 iburst', ' 1.1.1.1', '1.1.1.1\n',
                   '001.001.001.001', 134744072, True, None]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(MODULE.ContractError):
                MODULE.public_upstreams([FIXTURE_UPSTREAMS[0], value, FIXTURE_UPSTREAMS[2]])

    def test_duplicate_destinations_are_rejected(self):
        with self.assertRaisesRegex(MODULE.ContractError, 'distinct'):
            MODULE.public_upstreams([FIXTURE_UPSTREAMS[0], FIXTURE_UPSTREAMS[0]])

    def test_inventory_scope_drift_is_rejected(self):
        changes = [('cr_ntp_change_id', 'OTHER'),
                   ('cr_ntp_source_host', 'k8s-control02'),
                   ('cr_ntp_source_ip', '10.1.93.103'),
                   ('cr_ntp_client_ips', list(MODULE.CLIENT_IPS[:-1])),
                   ('cr_ntp_client_ips', list(MODULE.CLIENT_IPS) + ['10.1.93.200']),
                   ('cr_ntp_client_ips', list(MODULE.CLIENT_IPS[:-1]) + [MODULE.CLIENT_IPS[0]]),
                   ('cr_ntp_client_ips', [False] * 5)]
        for name, value in changes:
            candidate = copy.deepcopy(self.variables)
            candidate[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(MODULE.ContractError):
                self.contract(candidate)

    def test_duplicate_yaml_and_nonmapping_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'vars.yml'
            for content in ('cr_ntp_source_upstreams: []\ncr_ntp_source_upstreams: []\n',
                            '[1, 2, 3]\n', 'null\n'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(MODULE.ContractError):
                    MODULE.load_vars(path)

    def test_cli_json_yaml_match_inventory_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'vars.yml'
            path.write_text(yaml.safe_dump(self.variables))
            before = path.read_bytes()
            results = []
            for format_name in ('json', 'yaml'):
                process = subprocess.run([sys.executable, str(SCRIPT), '--vars-file',
                                          str(path), '--format', format_name],
                                         capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, '')
                results.append(yaml.safe_load(process.stdout))
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0]['input']['vars_sha256'], hashlib.sha256(before).hexdigest())
            self.assertEqual(path.read_bytes(), before)

    def test_cli_rejection_creates_no_output_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path, output = Path(temp) / 'vars.yml', Path(temp) / 'review.json'
            self.variables['cr_ntp_source_upstreams'] = []
            path.write_text(yaml.safe_dump(self.variables))
            before = path.read_bytes()
            process = subprocess.run([sys.executable, str(SCRIPT), '--vars-file', str(path),
                                      '--output', str(output)], capture_output=True,
                                     text=True, timeout=10)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(process.stdout, '')
            self.assertTrue(process.stderr.strip())
            self.assertFalse(output.exists())
            self.assertEqual(path.read_bytes(), before)

    def test_cli_never_overwrites_prior_review(self):
        with tempfile.TemporaryDirectory() as temp:
            path, output = Path(temp) / 'vars.yml', Path(temp) / 'review.json'
            path.write_text(yaml.safe_dump(self.variables))
            output.write_text('previous evidence\n')
            process = subprocess.run([sys.executable, str(SCRIPT), '--vars-file', str(path),
                                      '--output', str(output)], capture_output=True,
                                     text=True, timeout=10)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(output.read_text(), 'previous evidence\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
