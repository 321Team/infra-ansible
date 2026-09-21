"""Focused LOCAL/MOCK tests; never execute firewall binaries or send packets."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('onepass_remote', ROOT / 'tools/ntp-onepass-remote.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def request(action='egress', host=M.SOURCE):
    return {'schema_version': 1, 'action': action, 'run_id': '20260920_test0123456789', 'host': host}


def key(obj):
    return json.dumps(obj, sort_keys=True)


class MemoryJournal:
    def __init__(self):
        self.data = {'schema_version': 1, 'snapshot': {'status': 'COMPLETE'}, 'operations': []}
        self.saved = []

    def save(self):
        self.saved.append(copy.deepcopy(self.data))


class Firewall:
    def __init__(self, host=M.SOURCE):
        self.objects = M.ingress_objects() + M.egress_objects(host)
        self.present = set()
        self.calls = []
        self.fail_add_number = None
        self.add_calls = 0
        self.extra_direct = []
        self.extra_kernel = []
        self.kernel_chain_only = False
        self.drop = 0
        self.before_mutate = None
        self.snapshot_fail = None

    def preload(self, objects):
        self.present.update(key(o) for o in objects)

    def __call__(self, argv, timeout=20):
        self.calls.append(argv)
        result = {'argv': argv, 'rc': 0, 'stdout': '', 'stderr': ''}
        for obj in self.objects:
            for verb in ('query', 'add', 'remove'):
                if argv != M.fw_args(obj, verb):
                    continue
                if verb == 'query':
                    result['rc'] = 0 if key(obj) in self.present else 1
                elif verb == 'add':
                    self.add_calls += 1
                    if self.before_mutate:
                        self.before_mutate(obj)
                    self.present.add(key(obj))
                    if self.add_calls == self.fail_add_number:
                        result['rc'] = 124
                        result['stderr'] = 'simulated timeout after possible commit'
                else:
                    if self.before_mutate:
                        self.before_mutate(obj)
                    self.present.discard(key(obj))
                return result
        if '--get-all-rules' in argv:
            permanent = '--permanent' in argv
            rows = [' '.join([obj['family'], 'filter', obj['chain'], obj['priority']] + obj['args'])
                    for obj in self.objects if obj['kind'] == 'direct' and obj['permanent'] == permanent and key(obj) in self.present]
            result['stdout'] = '\n'.join(rows + self.extra_direct)
        elif argv[0].endswith('tables-save'):
            family = 'ipv6' if 'ip6tables' in argv[0] else 'ipv4'
            objs = [obj for obj in self.objects if obj.get('family') == family and not obj['permanent'] and key(obj) in self.present]
            rows = ['*filter', ':OUTPUT ACCEPT [0:0]']
            if self.kernel_chain_only or any(obj['kind'] == 'chain' for obj in objs):
                rows.append(':' + M.CHAIN + ' - [0:0]')
            if any(obj.get('chain') == 'OUTPUT' for obj in objs):
                rows += [':OUTPUT_direct - [0:0]', '-A OUTPUT -j OUTPUT_direct']
            for obj in objs:
                if obj['kind'] == 'direct':
                    args = list(obj['args'])
                    if '--dport' in args:
                        i = args.index('--dport')
                        args[i:i] = ['-m', 'udp']
                    rows.append(' '.join(['-A', 'OUTPUT_direct' if obj['chain'] == 'OUTPUT' else obj['chain']] + args))
            rows += self.extra_kernel
            rows.append('COMMIT')
            result['stdout'] = '\n'.join(rows)
        elif argv[0] == '/usr/sbin/iptables' and '-L' in argv:
            result['stdout'] = 'Chain FDS_NTP_0101 (1 references)\nnum pkts bytes target prot opt in out source destination\n1 %d 0 DROP all -- * * 0.0.0.0/0 0.0.0.0/0\n' % self.drop
        elif argv[0] == '/usr/sbin/ip':
            result['stdout'] = json.dumps([{'addr_info': [{'family': 'inet', 'local': '10.1.93.102'}]}])
        elif '--get-zone-of-interface=ens160' in argv:
            result['stdout'] = 'public\n'
        if self.snapshot_fail and self.snapshot_fail in argv:
            result['rc'] = 1
            result['stderr'] = 'simulated observation failure'
        return result


class ContractTests(unittest.TestCase):
    def test_exact_contract_and_actions(self):
        for action in M.ACTIONS:
            self.assertEqual(M.request(json.dumps(request(action)).encode())['action'], action)

    def test_reject_duplicate_key(self):
        with self.assertRaises(M.Stop):
            M.request(b'{"host":"k8s-control01","host":"k8s-worker01"}')

    def test_reject_extra_unknown_and_large_input(self):
        cases = [dict(request(), command='reload'), dict(request(), host='db01'),
                 dict(request(), action='reload'), dict(request(), schema_version=True),
                 dict(request(), run_id='../../unsafe'), dict(request(), run_id='x' * 65)]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(M.Stop):
                M.request(json.dumps(case).encode())
        with self.assertRaises(M.Stop):
            M.request(b' ' * (M.MAX_REQUEST + 1))

    def test_wrong_identity_never_reaches_firewall(self):
        fw = Firewall()
        engine = M.Engine(request(), MemoryJournal(), runner=fw)
        with patch.object(M.os, 'geteuid', return_value=0), patch.object(M.socket, 'gethostname', return_value='wrong-host'):
            with self.assertRaises(M.Stop):
                engine.identity()
        self.assertEqual(fw.calls, [])

    def test_binding_rejects_wrong_ip(self):
        fw = Firewall()
        engine = M.Engine(request(host='k8s-worker01'), MemoryJournal(), runner=fw)
        with patch.object(M.os, 'geteuid', return_value=0), patch.object(M.socket, 'gethostname', return_value='k8s-worker01'):
            with self.assertRaises(M.Stop):
                engine.identity()
        self.assertFalse(any(argv[0] == M.FIREWALL for argv in fw.calls))


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.fw = Firewall()
        self.journal = MemoryJournal()
        self.engine = M.Engine(request(), self.journal, runner=self.fw)

    def test_ingress_exact_five_addresses_both_scopes(self):
        objects = M.ingress_objects()
        self.assertEqual(len(objects), 10)
        self.assertEqual(sum(o['permanent'] for o in objects), 5)
        for rule in M.rich_rules():
            self.assertIn('destination address="10.1.93.102/32"', rule)
            self.assertIn('port port="123" protocol="udp"', rule)
            self.assertNotIn('/24', rule)

    def test_ingress_rejects_client(self):
        self.engine.req['host'] = 'k8s-worker01'
        with self.assertRaises(M.Stop):
            self.engine.ingress()
        self.assertFalse(self.fw.calls)

    def test_ingress_preexisting_is_not_owned_or_removed(self):
        preexisting = M.ingress_objects()[0]
        self.fw.preload([preexisting])
        self.engine.ingress()
        self.engine.rollback('ingress')
        self.assertEqual(self.fw.present, {key(preexisting)})
        states = [op['state'] for op in self.journal.data['operations']]
        self.assertEqual(states.count('PREEXISTING'), 1)
        self.assertEqual(states.count('REMOVED'), 9)

    def test_mutation_intent_is_saved_first(self):
        def check(obj):
            last = self.journal.saved[-1]['operations'][-1]
            self.assertEqual(last['object'], obj)
            self.assertEqual(last['state'], 'PREPARED')
        self.fw.before_mutate = check
        self.engine.ingress()
        self.assertEqual(self.fw.add_calls, 10)

    def test_timeout_preserves_uncertain_and_blocks_rollback(self):
        self.fw.fail_add_number = 3
        with self.assertRaises(M.Stop):
            self.engine.ingress()
        self.assertEqual([o['state'] for o in self.journal.data['operations']], ['ADDED', 'ADDED', 'UNCERTAIN'])
        before = list(self.fw.calls)
        with self.assertRaises(M.Stop):
            self.engine.rollback('ingress')
        self.assertEqual(self.fw.calls, before)

    def test_idempotent_same_journal_no_duplicate_add(self):
        self.engine.ingress()
        self.engine.ingress()
        self.assertEqual(self.fw.add_calls, 10)

    def test_old_run_missing_owned_rule_is_drift(self):
        self.engine.ingress()
        self.fw.present.remove(key(M.ingress_objects()[0]))
        with self.assertRaises(M.Stop):
            self.engine.ingress()

    def test_egress_new_only_never_accept_or_forward(self):
        for host in M.HOSTS:
            objects = M.egress_objects(host)
            for obj in objects:
                self.assertIn(obj['chain'], (M.CHAIN, 'OUTPUT'))
                self.assertNotIn('ACCEPT', obj.get('args', []))
                if obj['chain'] == 'OUTPUT':
                    self.assertEqual(obj['args'], ['-p', 'udp', '--dport', '123', '-m', 'conntrack', '--ctstate', 'NEW', '-j', M.CHAIN])
                if obj['kind'] == 'direct' and obj['family'] == 'ipv6' and obj['chain'] == M.CHAIN:
                    self.assertEqual(obj['args'], ['-j', 'DROP'])
            returned = [o['args'][1] for o in objects if o['kind'] == 'direct' and o['args'][-1] == 'RETURN' and not o['permanent']]
            self.assertEqual(returned, [ip + '/32' for ip in (M.UPSTREAMS if host == M.SOURCE else ['10.1.93.102'])])

    def test_egress_builds_chain_before_hook_and_removes_hook_first(self):
        self.engine.egress()
        added = [op['object'] for op in self.journal.data['operations']]
        for family in ('ipv4', 'ipv6'):
            for permanent in (False, True):
                subset = [o for o in added if o['family'] == family and o['permanent'] == permanent]
                self.assertEqual(subset[0]['kind'], 'chain')
                self.assertEqual(subset[-1]['chain'], 'OUTPUT')
        self.engine.rollback('egress')
        self.assertFalse(self.fw.present)
        self.assertFalse(any('--reload' in argv or '--runtime-to-permanent' in argv for argv in self.fw.calls))

    def test_complete_preexisting_chain_preserved(self):
        self.fw.preload(M.egress_objects(M.SOURCE))
        self.engine.egress()
        self.assertEqual(self.fw.add_calls, 0)
        self.engine.rollback('egress')
        self.assertEqual(len(self.fw.present), len(M.egress_objects(M.SOURCE)))

    def test_partial_foreign_chain_stops_before_add(self):
        self.fw.preload([M.egress_objects(M.SOURCE)[0]])
        with self.assertRaises(M.Stop):
            self.engine.egress()
        self.assertEqual(self.fw.add_calls, 0)

    def test_foreign_direct_output_stops(self):
        self.fw.extra_direct = ['ipv4 filter OUTPUT 0 -j ACCEPT']
        with self.assertRaises(M.Stop):
            self.engine.egress()
        self.assertEqual(self.fw.add_calls, 0)

    def test_foreign_kernel_chain_stops_before_claiming(self):
        self.fw.kernel_chain_only = True
        with self.assertRaises(M.Stop):
            self.engine.egress()
        self.assertEqual(self.fw.add_calls, 0)

    def test_foreign_kernel_rule_drift_blocks_rollback(self):
        self.engine.egress()
        self.fw.extra_kernel = ['-A FDS_NTP_0101 -j ACCEPT']
        before = set(self.fw.present)
        with self.assertRaises(M.Stop):
            self.engine.rollback('egress')
        self.assertEqual(self.fw.present, before)

    def test_foreign_kernel_forward_hook_stops(self):
        self.fw.preload(M.egress_objects(M.SOURCE))
        self.fw.extra_kernel = ['-A FORWARD -j FDS_NTP_0101']
        with self.assertRaises(M.Stop):
            self.engine.egress()

    def test_negative_probe_needs_counter_increment(self):
        self.engine.ingress()
        self.engine.egress()
        self.engine.sender = lambda: {'bytes': 48, 'destination': '192.0.2.123'}
        with self.assertRaises(M.Stop):
            self.engine.verify()
        def dropped():
            self.fw.drop += 1
            return {'bytes': 48, 'destination': '192.0.2.123'}
        self.engine.sender = dropped
        self.engine.verify()
        self.assertTrue(self.engine.details['negative_ipv4_probe']['pass'])
        self.assertEqual(self.engine.details['ipv6_packet_test'], 'NOT_PERFORMED')

    def test_no_negative_packet_before_full_config(self):
        sent = []
        self.engine.sender = lambda: sent.append(True)
        with self.assertRaises(M.Stop):
            self.engine.verify()
        self.assertFalse(sent)

    def test_snapshot_partial_preserved(self):
        self.journal.data['snapshot'] = None
        self.fw.snapshot_fail = '--list-all-policies'
        with self.assertRaises(M.Stop):
            self.engine.snapshot()
        snapshot = self.journal.saved[-1]['snapshot']
        self.assertEqual(snapshot['status'], 'COLLECTING')
        self.assertIn('runtime_zones', snapshot['observations'])
        self.assertEqual(snapshot['observations']['runtime_policies']['rc'], 1)
        self.assertFalse(self.fw.add_calls)

    def test_no_action_from_partial_snapshot(self):
        self.journal.data['snapshot']['status'] = 'COLLECTING'
        with self.assertRaises(M.Stop):
            self.engine.dispatch()
        self.assertFalse(self.fw.calls)


class SampleTests(unittest.TestCase):
    TRACK = 'Stratum : 3\nSystem time : 0.0001 seconds slow of NTP time\nLast offset : -0.0002 seconds\nLeap status : Normal\n'

    def test_sample_requires_exact_pair_one_selected(self):
        good = '^* 162.159.200.1 2 6 377 3 +1us[ +1us] +/- 1ms\n^+ 162.159.200.123 2 6 377 3 +1us[ +1us] +/- 1ms\n'
        self.assertTrue(M.parse_sample(self.TRACK, good, M.SOURCE)['pass'])
        self.assertFalse(M.parse_sample(self.TRACK, good + '^? 8.8.8.8 2 6 0 0 0\n', M.SOURCE)['pass'])
        self.assertFalse(M.parse_sample(self.TRACK, good.replace('^*', '^+'), M.SOURCE)['pass'])
        self.assertFalse(M.parse_sample(self.TRACK.replace('-0.0002', '0.101'), good, M.SOURCE)['pass'])
        self.assertFalse(M.parse_sample(self.TRACK.replace('Normal', 'Not synchronised'), good, M.SOURCE)['pass'])

    def test_client_only_102(self):
        good = '^* 10.1.93.102 2 6 377 3 +1us[ +1us] +/- 1ms\n'
        self.assertTrue(M.parse_sample(self.TRACK, good, 'k8s-worker01')['pass'])
        self.assertFalse(M.parse_sample(self.TRACK, good.replace('10.1.93.102', '162.159.200.1'), 'k8s-worker01')['pass'])

    def test_missing_duplicate_and_nonfinite_tracking(self):
        for text in (self.TRACK + 'Stratum : 3\n', self.TRACK.replace('Stratum : 3\n', ''), self.TRACK.replace('-0.0002', 'NaN')):
            with self.assertRaises(M.Stop):
                M.parse_sample(text, '', M.SOURCE)
        self.assertFalse(M.parse_sample(self.TRACK.replace('-0.0002', '1e999'), '^* 10.1.93.102 2 6 377 3 0\n', 'k8s-worker01')['pass'])


class SecurePathTests(unittest.TestCase):
    def test_symlink_hardlink_writable_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / 'state.json'
            target.write_text('{}')
            target.chmod(0o600)
            link = base / 'symlink'
            link.symlink_to(target)
            with self.assertRaises(M.Stop):
                M.protected(link, private=True)
            import os
            os.link(target, base / 'hardlink')
            with self.assertRaises(M.Stop):
                M.protected(target, private=True)
            (base / 'hardlink').unlink()
            target.chmod(0o666)
            with self.assertRaises(M.Stop):
                M.protected(target, private=True)


if __name__ == '__main__':
    unittest.main()
