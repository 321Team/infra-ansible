"""Independent LOCAL/MOCK checks for the bounded post-egress verifier.

The retained pdv_sd3n firewall output is real field evidence. All process,
network, identity and time progression used below are local fixtures; passing
these tests is not evidence that the follow-up ran on any target host.
"""
import argparse
import contextlib
import copy
import datetime
import hashlib
import importlib.util
import io
import json
import os
import py_compile
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from test_onepass_kernel_layout import ReplayFirewall


ROOT = Path(__file__).resolve().parents[2]
FIELD = json.loads((Path(__file__).parent /
                    'fixtures/onepass_post_egress_pdv_sd3n.json').read_text())


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REMOTE = load_module('post_egress_remote_tests', ROOT / 'tools/ntp-post-egress-remote.py')
CONTROLLER = load_module('post_egress_controller_tests', ROOT / 'tools/ntp-post-egress.py')
BASE_SOURCE = (ROOT / 'tools/ntp-onepass-remote.py').read_text()
BASE = REMOTE.load_base(BASE_SOURCE)
START = '2026-09-21T13:00:00+09:00'
END = '2026-09-21T14:00:00+09:00'
NOW = datetime.datetime.fromisoformat('2026-09-21T13:05:00+09:00')


def remote_request(action='preflight', host='k8s-control01', expected=None):
    return {'schema_version': 1, 'action': action, 'host': host,
            'prior_run_id': REMOTE.PRIOR_RUN_ID,
            'followup_run_id': 'ntp-post-egress-' + 'a' * 32,
            'window_start': START, 'window_end': END,
            'expected_preservation': expected}


class NoLiveActions(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.process = self.stack.enter_context(patch.object(
            subprocess, 'Popen', side_effect=AssertionError('Live process forbidden')))
        self.packet = self.stack.enter_context(patch.object(
            socket, 'socket', side_effect=AssertionError('Live socket forbidden')))

    def tearDown(self):
        self.process.assert_not_called()
        self.packet.assert_not_called()


class PreservationNormalizationTests(NoLiveActions):
    def test_committed_field_baseline_matches_every_host_and_kernel_family(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/post_egress_baseline.json').read_text())
        self.assertEqual(set(fixture['hosts']), set(BASE.HOSTS))
        for host, value in fixture['hosts'].items():
            with self.subTest(host=host):
                self.assertEqual(value['baseline'], REMOTE.BASELINE[host])
                for label, command, normalizer in [('iptables', 'iptables-save', REMOTE.normalize_iptables),
                        ('ip6tables', 'ip6tables-save', REMOTE.normalize_iptables),
                        ('nft', 'nft-ruleset', REMOTE.normalize_nft)]:
                    self.assertEqual(REMOTE.digest(normalizer(value['commands'][command]).encode()),
                                     REMOTE.BASELINE[host]['kernel'][label])

    def test_all_six_field_rules_ignore_only_comments_and_counters(self):
        for host, value in FIELD['hosts'].items():
            for name in ('iptables-save', 'ip6tables-save'):
                raw = value['commands'][name]
                counters = re.sub(r'\[[0-9]+:[0-9]+\]', '[887:999999]', raw)
                counters = re.sub(r'(?m)^#.*$', '# later observation', counters)
                with self.subTest(host=host, family=name):
                    self.assertEqual(REMOTE.normalize_iptables(raw),
                                     REMOTE.normalize_iptables(counters))

    def test_preservation_does_not_erase_security_relevant_filter_drift(self):
        original = FIELD['hosts']['k8s-control01']['commands']['iptables-save']
        changes = [
            ('--ctstate NEW', '--ctstate NEW,ESTABLISHED'),
            ('-d 162.159.200.1/32', '-d 162.159.200.0/24'),
            ('-A FDS_NTP_0101 -j DROP', '-A FDS_NTP_0101 -j ACCEPT'),
            ('-A OUTPUT -j KUBE-FIREWALL', '-A OUTPUT -j ACCEPT'),
            ('--ctstate RELATED,ESTABLISHED,DNAT', '--ctstate ESTABLISHED'),
            (':OUTPUT ACCEPT', ':OUTPUT DROP'),
        ]
        baseline = REMOTE.normalize_iptables(original)
        for old, new in changes:
            self.assertIn(old, original)
            with self.subTest(change=(old, new)):
                self.assertNotEqual(baseline, REMOTE.normalize_iptables(original.replace(old, new)))

    def test_unreviewed_nonfilter_rule_is_refused(self):
        original = FIELD['hosts']['k8s-control01']['commands']['iptables-save']
        for table in ('mangle', 'nat', 'raw', 'security'):
            raw = original + '\n*' + table + '\n:OUTPUT ACCEPT [0:0]\n-A OUTPUT -j ACCEPT\nCOMMIT\n'
            with self.subTest(table=table), self.assertRaises(ValueError):
                REMOTE.normalize_iptables(raw)

    def test_nft_only_counter_values_are_ignored(self):
        raw = ('table inet firewalld {\n chain filter_OUTPUT {\n'
               '  type filter hook output priority filter + 10; policy accept;\n'
               '  ip daddr 192.0.2.123 udp dport 123 counter packets 9 bytes 684 drop\n'
               ' }\n}\n')
        baseline = REMOTE.normalize_nft(raw)
        self.assertEqual(baseline, REMOTE.normalize_nft(raw.replace('packets 9 bytes 684',
                                                                  'packets 102 bytes 7752')))
        for old, new in [('drop', 'accept'), ('123 counter', '124 counter'),
                         ('priority filter + 10', 'priority filter - 10'),
                         ('192.0.2.123', '0.0.0.0/0')]:
            with self.subTest(change=(old, new)):
                self.assertNotEqual(baseline, REMOTE.normalize_nft(raw.replace(old, new)))


class RequestBoundaryTests(NoLiveActions):
    def test_only_the_exact_approved_remote_source_loads(self):
        self.assertEqual(REMOTE.digest(BASE_SOURCE.encode()), REMOTE.BASE_SHA256)
        for source in (BASE_SOURCE + '\n', BASE_SOURCE.replace('NEW', 'ESTABLISHED', 1), None):
            with self.subTest(source_type=type(source).__name__), self.assertRaises(ValueError):
                REMOTE.load_base(source)

    def test_window_is_timezone_bound_new_and_end_exclusive(self):
        REMOTE.validate_window(START, END, now=NOW)
        REMOTE.validate_window(START, END, now=datetime.datetime.fromisoformat(START))
        cases = [(START, END, datetime.datetime.fromisoformat(END)),
                 (START, END, NOW - datetime.timedelta(hours=1)),
                 (END, START, NOW),
                 ('2026-09-21T13:00:00', '2026-09-21T14:00:00', NOW),
                 ('2026-09-21T10:35:00+09:00', '2026-09-21T11:35:00+09:00', NOW)]
        for start, end, observed in cases:
            with self.subTest(start=start, end=end, observed=observed), self.assertRaises(ValueError):
                REMOTE.validate_window(start, end, now=observed)

    def test_request_rejects_mutating_actions_and_scope_expansion(self):
        with patch.object(REMOTE, 'validate_window'):
            REMOTE.validate_request(remote_request())
            for action in ('snapshot', 'ingress', 'egress', 'rollback_ingress',
                           'rollback_egress', 'apply', 'restart', 'reload'):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    REMOTE.validate_request(remote_request(action))
            for key, value in [('host', 'db01'), ('prior_run_id', 'ntp-onepass-other'),
                               ('followup_run_id', REMOTE.PRIOR_RUN_ID),
                               ('schema_version', True), ('command', 'reload')]:
                bad = remote_request()
                bad[key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    REMOTE.validate_request(bad)

    def test_only_preflight_can_establish_preservation(self):
        with patch.object(REMOTE, 'validate_window'):
            for action in ('verify', 'sample', 'finalize'):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    REMOTE.validate_request(remote_request(action))
            with self.assertRaises(ValueError):
                REMOTE.validate_request(remote_request(expected={}))


class ReadOnlyJournalTests(NoLiveActions):
    def fixture(self):
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        base = Path(directory) / 'journal'
        base.mkdir(mode=0o700)
        (base / '.lock').write_bytes(b'')
        (base / '.lock').chmod(0o600)
        run = base / REMOTE.PRIOR_RUN_ID
        run.mkdir(mode=0o700)
        path = run / 'state.json'
        state = {'schema_version': 1, 'host': 'k8s-control01', 'run_id': REMOTE.PRIOR_RUN_ID,
                 'snapshot': {'status': 'COMPLETE'},
                 'operations': [{'state': 'ADDED', 'group': 'egress',
                                 'object': {'kind': 'chain', 'family': 'ipv4',
                                            'chain': 'FDS_NTP_0101', 'permanent': False}}]}
        raw = json.dumps(state).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        expected = {'journal_sha256': REMOTE.digest(raw),
                    'journal_canonical_sha256': REMOTE.digest(json.dumps(
                        state, sort_keys=True, separators=(',', ':')).encode())}
        self.stack.enter_context(patch.dict(REMOTE.BASELINE, {'k8s-control01': expected}))
        # Temporary test ancestors are not production root-owned directories.
        # Retain the actual protection checks for every journal/lock leaf.
        protected = BASE.protected
        ancestors = set(base.parents)
        self.stack.enter_context(patch.object(BASE, 'protected', side_effect=lambda p, **kw:
            p.lstat() if p in ancestors else protected(p, **kw)))
        return base, path, state, raw

    def test_success_and_save_refusal_preserve_original_bytes(self):
        base, path, state, original = self.fixture()
        journal = REMOTE.ReadOnlyJournal(remote_request(), BASE, base=base)
        try:
            self.assertEqual(journal.read(), original)
            with self.assertRaises(ValueError):
                journal.save()
        finally:
            journal.close()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['state.json'])

    def test_missing_lock_or_journal_is_not_created(self):
        for missing in ('lock', 'journal'):
            with self.subTest(missing=missing):
                base, path, state, raw = self.fixture()
                target = base / '.lock' if missing == 'lock' else path
                target.unlink()
                with self.assertRaises((ValueError, OSError)):
                    REMOTE.ReadOnlyJournal(remote_request(), BASE, base=base)
                self.assertFalse(target.exists())

    def test_unfinished_or_wrong_identity_journal_is_refused(self):
        variants = [('host', 'k8s-worker01'), ('run_id', 'ntp-onepass-other'),
                    ('snapshot', {'status': 'COLLECTING'}), ('snapshot', None),
                    ('operations', [])]
        variants += [('operations', [{'state': state}]) for state in
                     ('PREPARED', 'UNCERTAIN', 'REMOVED', 'REMOVE_PREPARED')]
        for key, value in variants:
            with self.subTest(key=key, value=value):
                base, path, state, original = self.fixture()
                state[key] = value
                changed = json.dumps(state).encode()
                path.write_bytes(changed)
                with self.assertRaises(ValueError):
                    REMOTE.ReadOnlyJournal(remote_request(), BASE, base=base)
                self.assertEqual(path.read_bytes(), changed)

    def test_valid_looking_new_operation_and_whitespace_drift_are_refused(self):
        for kind in ('operation', 'format'):
            with self.subTest(kind=kind):
                base, path, state, original = self.fixture()
                if kind == 'operation':
                    state['operations'].append({'state': 'ADDED', 'object': {'kind': 'rich'}})
                    changed = json.dumps(state).encode()
                else:
                    changed = original + b'\n'
                path.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, 'bytes/ownership'):
                    REMOTE.ReadOnlyJournal(remote_request(), BASE, base=base)
                self.assertEqual(path.read_bytes(), changed)

    def test_symlink_journal_is_refused_without_replacing_it(self):
        base, path, state, original = self.fixture()
        target = path.with_name('retained.json')
        path.rename(target)
        path.symlink_to(target.name)
        with self.assertRaises(ValueError):
            REMOTE.ReadOnlyJournal(remote_request(), BASE, base=base)
        self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_bytes(), original)


class ObservationFixture:
    """Real retained firewall text, synthetic bounded file/journal observations."""
    def __init__(self, case, host='k8s-control01'):
        self.case, self.host = case, host
        self.firewall = ReplayFirewall(host)
        self.raw_journal = b'field-journal-bytes-for-local-fixture'
        self.data = {'snapshot': {'status': 'COMPLETE'}, 'operations': []}
        self.journal = types.SimpleNamespace(data=self.data, read=lambda: self.raw_journal)
        self.nft = 'table inet firewalld {\n chain filter_OUTPUT { counter packets 1 bytes 76 drop }\n}\n'
        self.files = {name: {'path': name, 'exists': False} for name in BASE.FILES}
        for name in ('/etc/chrony.conf', '/etc/chrony.d/50-cr-p1-ntp-01-01.conf',
                     '/etc/firewalld/direct.xml'):
            self.files[name] = {'path': name, 'exists': True, 'uid': 0, 'gid': 0,
                                'mode': '0o644', 'sha256': REMOTE.digest(name.encode())}
        self.counter, self.sent, self.calls = 0, [], []
        self.increment = True
        self.tracking = ('Stratum : 3\nSystem time : 0.0001 seconds slow of NTP time\n'
                         'Last offset : -0.0002 seconds\nLeap status : Normal\n')
        allowed = ['162.159.200.1', '162.159.200.123'] if host == 'k8s-control01' else ['10.1.93.102']
        self.sources = '\n'.join(('^* ' if index == 0 else '^+ ') + address +
                                 ' 2 6 377 3 +1us[ +1us] +/- 1ms'
                                 for index, address in enumerate(allowed)) + '\n'
        baseline = {'journal_sha256': REMOTE.digest(self.raw_journal),
                    'files': {name: {k: v for k, v in value.items() if k != 'path'}
                              for name, value in self.files.items() if value['exists']},
                    'kernel': {'iptables': REMOTE.digest(REMOTE.normalize_iptables(
                                   self.firewall.commands['iptables-save']).encode()),
                               'ip6tables': REMOTE.digest(REMOTE.normalize_iptables(
                                   self.firewall.commands['ip6tables-save']).encode()),
                               'nft': REMOTE.digest(REMOTE.normalize_nft(self.nft).encode())}}
        case.stack.enter_context(patch.dict(REMOTE.BASELINE, {host: baseline}))
        case.stack.enter_context(patch.object(REMOTE, 'validate_window'))
        case.stack.enter_context(patch.object(BASE.os, 'geteuid', return_value=0))
        case.stack.enter_context(patch.object(BASE.socket, 'gethostname', return_value=host))

    def runner(self, argv, timeout=20):
        self.calls.append(list(argv))
        result = {'argv': argv, 'rc': 0, 'stdout': '', 'stderr': ''}
        if argv[0] == '/usr/sbin/ip':
            result['stdout'] = json.dumps([{'addr_info': [{'family': 'inet', 'local': BASE.HOSTS[self.host]}]}])
        elif argv == [BASE.FIREWALL, '--state']:
            result['stdout'] = 'running\n'
        elif '--get-zone-of-interface=ens160' in argv:
            result['stdout'] = 'public\n'
        elif argv == ['/usr/sbin/nft', 'list', 'ruleset']:
            result['stdout'] = self.nft
        elif argv[0] == '/usr/sbin/iptables' and '-L' in argv:
            result['stdout'] = ('Chain FDS_NTP_0101 (1 references)\n'
                                'num pkts bytes target prot opt in out source destination\n'
                                '1 %d 0 DROP all -- * * 0.0.0.0/0 0.0.0.0/0\n' % self.counter)
        elif any(arg.startswith('--query-rich-rule=') for arg in argv):
            self.case.assertIn(argv, [BASE.fw_args(obj, 'query') for obj in BASE.ingress_objects()])
        elif argv == ['/usr/bin/chronyc', '-n', 'tracking']:
            result['stdout'] = self.tracking
        elif argv == ['/usr/bin/chronyc', '-n', 'sources', '-a']:
            result['stdout'] = self.sources
        else:
            return self.firewall(argv, timeout=timeout)
        return result

    def sender(self):
        self.sent.append(self.host)
        self.counter += int(self.increment)
        return {'bytes': 48, 'destination': '192.0.2.123', 'port': 123, 'source_port': 49152}

    def verifier(self, action='preflight', expected=None):
        verifier = REMOTE.Verifier(remote_request(action, self.host, expected), BASE,
                                   self.journal, runner=self.runner, sender=self.sender)
        self.case.stack.enter_context(patch.object(verifier.engine, 'read_file',
                                                  side_effect=lambda name: copy.deepcopy(self.files[name])))
        return verifier

    def preflight(self):
        return self.verifier().execute()['preservation_after']


class RemoteVerificationTests(NoLiveActions):
    def test_retained_rules_all_six_preflight_without_packets(self):
        for host in FIELD['hosts']:
            with self.subTest(host=host):
                fixture = ObservationFixture(self, host)
                result = fixture.verifier().execute()
                self.assertTrue(result['configuration_unchanged'])
                self.assertTrue(result['journal_unchanged'])
                self.assertEqual(result['preservation_before'], result['preservation_after'])
                self.assertEqual(fixture.sent, [])

    def test_verify_proves_counter_increment_and_preserves_bytes(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        result = fixture.verifier('verify', expected).execute()
        self.assertEqual(fixture.sent, ['k8s-control01'])
        self.assertTrue(result['observation']['negative_ipv4_probe']['pass'])
        self.assertEqual(result['observation']['ipv6_packet_test'], 'NOT_PERFORMED')
        self.assertEqual(result['preservation_after'], expected)

    def test_no_counter_increment_never_becomes_success(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        fixture.increment = False
        verifier = fixture.verifier('verify', expected)
        with self.assertRaisesRegex(ValueError, 'increment'):
            verifier.execute()
        self.assertEqual(fixture.sent, ['k8s-control01'])
        self.assertFalse(verifier.engine.details['negative_ipv4_probe']['pass'])
        self.assertEqual(verifier.preservation(), expected)

    def test_config_journal_and_native_nft_drift_block_packet(self):
        for kind in ('config', 'journal', 'nft', 'kernel'):
            with self.subTest(kind=kind):
                fixture = ObservationFixture(self)
                expected = fixture.preflight()
                if kind == 'config':
                    fixture.files['/etc/chrony.conf']['sha256'] = 'f' * 64
                elif kind == 'journal':
                    fixture.raw_journal += b'\n'
                elif kind == 'nft':
                    fixture.nft = fixture.nft.replace('drop', 'accept')
                else:
                    fixture.firewall.commands['iptables-save'] = fixture.firewall.commands['iptables-save'].replace(
                        '-A FDS_NTP_0101 -j DROP', '-A FDS_NTP_0101 -j RETURN')
                with self.assertRaises(ValueError):
                    fixture.verifier('verify', expected).execute()
                self.assertEqual(fixture.sent, [])

    def test_missing_or_foreign_preflight_receipt_blocks_packet(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        for receipt in ({}, dict(expected, journal_sha256='0' * 64)):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                fixture.verifier('verify', receipt).execute()
        self.assertEqual(fixture.sent, [])

    def test_observation_actions_cannot_call_packet_sender(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        for action in ('preflight', 'sample', 'finalize'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                fixture.verifier(action, expected).send()
        self.assertEqual(fixture.sent, [])

    def test_mutation_commands_never_reach_runner(self):
        fixture = ObservationFixture(self)
        verifier = fixture.verifier()
        commands = [[BASE.FIREWALL, '--reload'], [BASE.FIREWALL, '--runtime-to-permanent'],
                    ['/usr/bin/chronyc', 'makestep'], ['/usr/bin/systemctl', 'restart', 'chronyd'],
                    ['/usr/sbin/iptables', '-F'], ['/usr/sbin/conntrack', '-F']]
        commands += [BASE.fw_args(obj, verb) for obj in BASE.egress_objects('k8s-control01')
                     for verb in ('add', 'remove')]
        for argv in commands:
            with self.subTest(argv=argv), self.assertRaisesRegex(ValueError, 'allowlist'):
                verifier.read_command(argv)
        self.assertEqual(fixture.calls, [])

    def test_pending_journal_intent_blocks_packet(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        fixture.data['operations'] = [{'state': 'PREPARED'}]
        with self.assertRaises(ValueError):
            fixture.verifier('verify', expected).execute()
        self.assertEqual(fixture.sent, [])

    def test_wrong_chrony_source_fails_sample_without_packet(self):
        fixture = ObservationFixture(self, 'k8s-worker01')
        expected = fixture.preflight()
        fixture.sources = fixture.sources.replace('10.1.93.102', '8.8.8.8')
        with self.assertRaises(ValueError):
            fixture.verifier('sample', expected).execute()
        self.assertEqual(fixture.sent, [])

    def test_window_expiring_during_final_preservation_blocks_send(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        verifier = fixture.verifier('verify', expected)
        with patch.object(verifier, 'preservation', return_value=expected), patch.object(
                verifier, 'guard', side_effect=[None, ValueError('Window expired during observation')]):
            with self.assertRaisesRegex(ValueError, 'expired'):
                verifier.send()
        self.assertEqual(fixture.sent, [])

    def test_drift_retains_observed_raw_kernel_output(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        fixture.firewall.commands['iptables-save'] = fixture.firewall.commands['iptables-save'].replace(
            '-A FDS_NTP_0101 -j DROP', '-A FDS_NTP_0101 -j RETURN')
        verifier = fixture.verifier('verify', expected)
        with self.assertRaises(ValueError):
            verifier.execute()
        raw = [record['stdout'] for record in verifier.records
               if record['argv'] == ['/usr/sbin/iptables-save']]
        self.assertEqual(raw, [fixture.firewall.commands['iptables-save']])
        self.assertEqual(fixture.sent, [])


class RemoteFailureReceiptTests(NoLiveActions):
    def test_counter_failure_emits_negative_receipt_and_raw_observations(self):
        fixture = ObservationFixture(self)
        expected = fixture.preflight()
        fixture.increment = False
        verifier = fixture.verifier('verify', expected)
        fixture.journal.close = lambda: None
        output = io.StringIO()
        with patch.object(REMOTE, 'ReadOnlyJournal', return_value=fixture.journal), \
                patch.object(REMOTE, 'Verifier', return_value=verifier), \
                patch.object(REMOTE, 'load_base', return_value=BASE), \
                patch.object(BASE.Engine, 'identity'), contextlib.redirect_stdout(output):
            code = REMOTE.main(verifier.req, BASE_SOURCE)
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'STOP')
        self.assertFalse(result['details']['observation']['negative_ipv4_probe']['pass'])
        self.assertTrue(result['commands'])
        self.assertEqual(result['journal_sha256_after'], REMOTE.digest(fixture.raw_journal))

    def test_journal_reread_failure_still_emits_bound_stop_and_closes(self):
        req = remote_request('verify', expected={})
        closed = []
        journal = types.SimpleNamespace(read=lambda: (_ for _ in ()).throw(OSError('journal inaccessible')),
                                        close=lambda: closed.append(True))
        verifier = types.SimpleNamespace(records=[], engine=types.SimpleNamespace(details={}),
                                         before=None, after=None,
                                         execute=lambda: (_ for _ in ()).throw(ValueError('preflight drift')))
        output = io.StringIO()
        with patch.object(REMOTE, 'validate_request'), patch.object(REMOTE, 'load_base', return_value=BASE), \
                patch.object(BASE.Engine, 'identity'), patch.object(REMOTE, 'ReadOnlyJournal', return_value=journal), \
                patch.object(REMOTE, 'Verifier', return_value=verifier), contextlib.redirect_stdout(output):
            code = REMOTE.main(req, BASE_SOURCE)
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'STOP')
        self.assertEqual(result['prior_run_id'], REMOTE.PRIOR_RUN_ID)
        self.assertEqual(result['host'], req['host'])
        self.assertTrue(result['preservation_uncertain'])
        self.assertEqual(closed, [True])


def controller_input():
    return {'reviewed_followup_sha': 'b' * 40, 'window_start': START, 'window_end': END,
            'approval_ref': 'https://github.com/321Team/infra-ansible/pull/999#review-local-fixture',
            'network_policy_ref': '/home/server01_ansible/ntp-refs/CR-P1-NTP-01-01-NETWORK.md',
            'recovery_ref': '/home/server01_ansible/ntp-refs/CR-P1-NTP-01-01-RECOVERY.md'}


class PipelineFixture:
    def __init__(self, case, verify=True, failure=None):
        self.case, self.failure, self.events = case, failure, []
        self.directory = Path(case.stack.enter_context(tempfile.TemporaryDirectory()))
        self.rollout = self.directory / 'rollout'
        self.rollout.mkdir()
        args = argparse.Namespace(rollout_repo=self.rollout, input=self.directory / 'input.json',
                                  evidence_parent=self.directory, verify=verify)
        self.controller = CONTROLLER.Followup(args, repo_root=ROOT)
        self.controller.root = self.directory / 'evidence'
        self.controller.root.mkdir(mode=0o700)
        (self.controller.root / 'remote').mkdir()
        self.controller.summary['run_id'] = 'ntp-post-egress-' + 'b' * 32
        self.controller.input = controller_input()

    def remote(self, action, host):
        self.events.append((action, host))
        if self.failure == (action, host):
            return {'status': 'STOP', 'error': 'Fixture observation failure'}
        expected = {'host': host, 'journal_sha256': 'c' * 64}
        return {'status': 'OK', 'details': {'preservation_before': expected,
                'preservation_after': expected, 'pass': True}, 'host': host, 'action': action}

    def positive(self):
        self.events.append(('positive', None))
        if self.failure == ('positive', None):
            raise ValueError('Fixture positive receipt validation failed')

    def samples(self):
        self.events.append(('samples', None))
        if self.failure == ('samples', None):
            raise ValueError('Fixture late sample failed')

    def execute(self):
        with patch.object(self.controller, 'remote', side_effect=self.remote), \
                patch.object(self.controller, 'post_egress_gates', side_effect=self.positive), \
                patch.object(self.controller, 'sample_all', side_effect=self.samples):
            self.controller.execute_pipeline()


class ControllerBoundaryTests(NoLiveActions):
    def test_source_loader_ignores_stale_matching_bytecode_cache(self):
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        source = directory / 'dependency.py'
        source.write_text("VALUE = 'old'\n")
        original_stat = source.stat()
        py_compile.compile(str(source), doraise=True)
        source.write_text("VALUE = 'new'\n")
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        loaded = CONTROLLER.module('source_binding_local_fixture', source,
                                   expected=hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(loaded.VALUE, 'new')

    def test_default_is_offline_without_any_remote_or_packet_stage(self):
        fixture = PipelineFixture(self, verify=False)
        fixture.execute()
        self.assertEqual(fixture.events, [])
        self.assertEqual(fixture.controller.summary['status'], 'FOLLOWUP_OFFLINE_PREPARED_NOT_EXECUTED')
        with patch.object(fixture.controller, 'load_input'), \
                patch.object(fixture.controller, 'mutation_guard'), \
                patch.object(fixture.controller, 'run_command', side_effect=AssertionError('offline external command')):
            fixture.controller.prepare()

    def test_all_six_preflights_precede_first_packet_and_finalize_is_last(self):
        fixture = PipelineFixture(self)
        fixture.execute()
        hosts = list(CONTROLLER.W.HOSTS)
        self.assertEqual(fixture.events,
                         [('preflight', host) for host in hosts] +
                         [('verify', host) for host in hosts] + [('positive', None), ('samples', None)] +
                         [('finalize', host) for host in hosts])
        self.assertEqual(set(fixture.controller.preflight_receipts), set(hosts))
        self.assertEqual(fixture.controller.summary['status'], 'POST_EGRESS_VERIFIED_REVIEW_REQUIRED')

    def test_any_preflight_failure_blocks_every_packet_stage(self):
        hosts = list(CONTROLLER.W.HOSTS)
        for index, host in enumerate(hosts):
            with self.subTest(host=host):
                fixture = PipelineFixture(self, failure=('preflight', host))
                with self.assertRaises(ValueError):
                    fixture.execute()
                self.assertEqual(fixture.events, [('preflight', h) for h in hosts[:index + 1]])
                self.assertEqual(fixture.controller.summary['negative_completed'], [])

    def test_later_failure_preserves_prior_stage_receipts_without_replay(self):
        hosts = list(CONTROLLER.W.HOSTS)
        for failed in [('verify', hosts[2]), ('positive', None), ('samples', None), ('finalize', hosts[3])]:
            with self.subTest(failed=failed):
                fixture = PipelineFixture(self, failure=failed)
                with self.assertRaises(ValueError):
                    fixture.execute()
                self.assertEqual(fixture.controller.summary['preflight_completed'], hosts)
                self.assertFalse(any(event[0] in {'snapshot', 'ingress', 'egress', 'rollout'} or
                                     event[0].startswith('rollback') for event in fixture.events))
                self.assertNotEqual(fixture.controller.summary['status'], 'POST_EGRESS_VERIFIED_REVIEW_REQUIRED')
                if failed[0] in ('positive', 'samples', 'finalize'):
                    self.assertEqual(fixture.controller.summary['negative_completed'], hosts)

    def test_input_requires_actual_references_and_exact_schema(self):
        CONTROLLER.validate_input(controller_input())
        cases = [('reviewed_followup_sha', '1234567'), ('approval_ref', 'PENDING'),
                 ('network_policy_ref', 'relative.md'), ('recovery_ref', '<replace>'),
                 ('window_start', '2026-09-21T10:35:00+09:00'), ('apply', True)]
        for key, value in cases:
            changed = controller_input()
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                CONTROLLER.validate_input(changed)

    def test_separate_approval_and_live_window_are_both_required(self):
        fixture = PipelineFixture(self)
        controller = fixture.controller
        with patch.object(controller, 'assert_sources'), patch.object(controller, 'verify_input'):
            with patch.dict(os.environ, {'CR_CHANGE_APPROVED': CONTROLLER.W.CHANGE_ID}, clear=True):
                with self.assertRaisesRegex(ValueError, 'CR_NTP_FOLLOWUP_APPROVED'):
                    controller.mutation_guard()
            with patch.dict(os.environ, {'CR_NTP_FOLLOWUP_APPROVED': CONTROLLER.W.CHANGE_ID}, clear=True), \
                    patch.object(CONTROLLER.R, 'validate_window', side_effect=ValueError('expired')):
                with self.assertRaisesRegex(ValueError, 'expired'):
                    controller.mutation_guard()

    def test_forbidden_remote_actions_rollout_and_rollback_are_unavailable(self):
        fixture = PipelineFixture(self)
        controller = fixture.controller
        for action in ('snapshot', 'ingress', 'egress', 'rollback_ingress', 'rollback_egress'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                controller.remote(action, 'k8s-control01')
        with self.assertRaises(ValueError):
            controller.run_child()
        with self.assertRaises(ValueError):
            controller.rollback_confirmed('rollback_egress', 'k8s-control01')

    def test_source_drift_refuses_before_submitting_remote_command(self):
        fixture = PipelineFixture(self)
        with patch.object(fixture.controller, 'assert_sources', side_effect=ValueError('reviewed source drift')), \
                patch.object(fixture.controller, 'run_command') as run:
            with self.assertRaisesRegex(ValueError, 'source drift'):
                fixture.controller.remote('preflight', 'k8s-control01')
            run.assert_not_called()

    def test_six_round_sampler_waits_after_each_prior_round_completes(self):
        fixture = PipelineFixture(self)
        clock, lock = [1000.0], threading.Lock()
        observations = []

        def sample(action, host):
            self.assertEqual(action, 'sample')
            with lock:
                clock[0] += 0.25
                observations.append((host, clock[0]))
            return {'status': 'OK', 'details': {'pass': True}}

        def sleep(seconds):
            self.assertGreaterEqual(seconds, 0)
            clock[0] += seconds

        with patch.object(fixture.controller, 'remote', side_effect=sample), \
                patch.object(fixture.controller, 'mutation_guard'), \
                patch.object(CONTROLLER.W.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(CONTROLLER.W.time, 'sleep', side_effect=sleep):
            fixture.controller.sample_all()
        receipt = json.loads((fixture.controller.root / 'SAMPLES.json').read_text())
        self.assertEqual(receipt['status'], 'PASSED')
        self.assertEqual(len(receipt['samples']), 6)
        for previous, current in zip(receipt['samples'], receipt['samples'][1:]):
            self.assertGreaterEqual(current['started_monotonic'] - previous['completed_monotonic'], 60)
        for host in CONTROLLER.W.HOSTS:
            times = [value for name, value in observations if name == host]
            self.assertEqual(len(times), 6)
            self.assertTrue(all(b - a >= 60 for a, b in zip(times, times[1:])))

    def test_insufficient_positive_gate_window_never_starts_probe(self):
        fixture = PipelineFixture(self)

        class FixedClock(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        with patch.object(fixture.controller, 'mutation_guard'), \
                patch.object(CONTROLLER, 'datetime', types.SimpleNamespace(datetime=FixedClock,
                             timezone=datetime.timezone)), \
                patch.object(CONTROLLER.R, 'validate_window', return_value=(NOW, NOW + datetime.timedelta(seconds=1809))), \
                patch.object(CONTROLLER.W.OnePass, 'post_egress_gates') as gates:
            with self.assertRaisesRegex(ValueError, '900-second'):
                fixture.controller.post_egress_gates()
            gates.assert_not_called()

    def test_command_must_fit_window_before_process_starts(self):
        fixture = PipelineFixture(self)

        class FixedClock(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        with patch.object(fixture.controller, 'mutation_guard'), \
                patch.object(CONTROLLER, 'datetime', types.SimpleNamespace(datetime=FixedClock,
                             timezone=datetime.timezone)), \
                patch.object(CONTROLLER.R, 'validate_window', return_value=(NOW, NOW + datetime.timedelta(seconds=189))), \
                patch.object(CONTROLLER.W.OnePass, 'run_command') as run:
            with self.assertRaisesRegex(ValueError, 'cleanup margin'):
                fixture.controller.run_command('preflight', ['ansible'], timeout=180)
            run.assert_not_called()


class ResponseBindingTests(NoLiveActions):
    def exchange(self, transform=None, parent_rc=0, action='preflight'):
        fixture = PipelineFixture(self)
        controller = fixture.controller
        controller.followup_remote_hash = CONTROLLER.W.sha256((ROOT / 'tools/ntp-post-egress-remote.py').read_bytes())
        host = 'k8s-control01'
        baseline = CONTROLLER.R.BASELINE[host]
        files = {name: dict(path=name, **copy.deepcopy(baseline['files'][name])) if name in baseline['files']
                 else {'path': name, 'exists': False} for name in BASE.FILES}
        preservation = {'files': files,
                        'kernel': copy.deepcopy(baseline['kernel']),
                        'journal_sha256': baseline['journal_sha256']}
        controller.preflight_receipts[host] = preservation

        def command(phase, argv, timeout=60, env=None):
            destination = Path(argv[argv.index('--tree') + 1])
            request = json.loads((destination.parent / 'REQUEST.json').read_text())
            response = dict(request, status='OK', changed=False,
                            journal_sha256_after=baseline['journal_sha256'],
                            details={'configuration_unchanged': True, 'journal_unchanged': True,
                                     'preservation_before': copy.deepcopy(preservation),
                                     'preservation_after': copy.deepcopy(preservation),
                                     'observation': {'pass': True}})
            if transform:
                transform(response)
            child_rc = 0 if response['status'] == 'OK' else 2
            (destination / host).write_text(json.dumps({'rc': child_rc, 'stdout': json.dumps(response)}))
            return {'returncode': parent_rc, 'timed_out': False, 'interrupted': False, 'output_limit': False}

        with patch.object(controller, 'mutation_guard'), patch.object(controller, 'run_command', side_effect=command):
            return controller.remote(action, host), fixture

    def test_valid_bound_sample_preserves_observation_for_sampler(self):
        result, fixture = self.exchange(action='sample')
        self.assertTrue(result['details']['pass'])
        self.assertEqual(len(fixture.controller.remote_results), 1)

    def test_valid_negative_receipt_is_accepted(self):
        def negative(response):
            response['details']['observation'] = {'negative_ipv4_probe': {
                'destination': '192.0.2.123', 'port': 123, 'bytes': 48,
                'counter_before': 3, 'counter_after': 4, 'pass': True}}
        result, fixture = self.exchange(transform=negative, action='verify')
        self.assertEqual(result['status'], 'OK')

    def test_verify_success_without_real_negative_counter_proof_is_uncertain(self):
        for variation in ('missing', 'equal', 'wrong_destination', 'false'):
            def malformed(response):
                packet = {'destination': '192.0.2.123', 'port': 123, 'bytes': 48,
                          'counter_before': 3, 'counter_after': 4, 'pass': True}
                if variation == 'equal':
                    packet['counter_after'] = packet['counter_before']
                elif variation == 'wrong_destination':
                    packet['destination'] = '8.8.8.8'
                elif variation == 'false':
                    packet['pass'] = False
                response['details']['observation'] = {} if variation == 'missing' else {'negative_ipv4_probe': packet}
            with self.subTest(variation=variation), self.assertRaises(CONTROLLER.W.StateUncertain):
                self.exchange(transform=malformed, action='verify')

    def test_success_without_complete_preservation_is_uncertain(self):
        def missing(response):
            response['details'].pop('preservation_before')
            response['details'].pop('preservation_after')

        def empty(response):
            for key in ('preservation_before', 'preservation_after'):
                response['details'][key]['files'] = {}

        def bad_hash(response):
            for key in ('preservation_before', 'preservation_after'):
                response['details'][key]['files']['/etc/chrony.conf']['sha256'] = 'f' * 64

        def missing_optional_file(response):
            for key in ('preservation_before', 'preservation_after'):
                response['details'][key]['files'].pop('/etc/sysconfig/chronyd')

        for transform in (missing, empty, bad_hash, missing_optional_file):
            with self.subTest(variant=transform.__name__), self.assertRaises(CONTROLLER.W.StateUncertain):
                self.exchange(transform=transform)

    def test_nonzero_transport_cannot_reuse_successful_remote_result(self):
        with self.assertRaisesRegex(CONTROLLER.W.StateUncertain, 'transport failed'):
            self.exchange(parent_rc=2)

    def test_bound_stop_remains_stop_when_ansible_reports_failure(self):
        def stop(response):
            response.update(status='STOP', error='Kernel mismatch')
        result, fixture = self.exchange(transform=stop, parent_rc=2)
        self.assertEqual(result['status'], 'STOP')
        self.assertEqual(fixture.controller.remote_results[0]['response']['error'], 'Kernel mismatch')

    def test_response_with_wrong_run_or_claimed_mutation_is_uncertain(self):
        for key, value in [('followup_run_id', 'ntp-post-egress-' + 'c' * 32), ('changed', True)]:
            with self.subTest(key=key), self.assertRaises(CONTROLLER.W.StateUncertain):
                self.exchange(transform=lambda response: response.update({key: value}))


if __name__ == '__main__':
    unittest.main()
