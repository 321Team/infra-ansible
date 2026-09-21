"""Replay retained field output and adversarial variants; no firewall or SSH calls."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_onepass_firewall import M, MemoryJournal, request


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/onepass_post_egress_pdv_sd3n.json').read_text())
HOOK = '-A OUTPUT -p udp -m udp --dport 123 -m conntrack --ctstate NEW -j FDS_NTP_0101'
BRIDGE = '-A OUTPUT -j OUTPUT_direct'


class ReplayFirewall:
    def __init__(self, host):
        self.host = host
        self.commands = copy.deepcopy(FIXTURE['hosts'][host]['commands'])
        self.calls = []

    def __call__(self, argv, timeout=20):
        self.calls.append(argv)
        if argv == ['/usr/sbin/iptables-save']:
            name = 'iptables-save'
        elif argv == ['/usr/sbin/ip6tables-save']:
            name = 'ip6tables-save'
        elif argv[0] == M.FIREWALL:
            scope = 'permanent' if '--permanent' in argv else 'runtime'
            for flag in ('--get-all-rules', '--get-all-chains', '--get-all-passthroughs'):
                if flag in argv:
                    name = scope + '-direct-' + flag[6:]
                    break
            else:
                for obj in M.egress_objects(self.host):
                    if argv != M.fw_args(obj, 'query'):
                        continue
                    if obj['kind'] == 'chain':
                        row = ' '.join([obj['family'], 'filter', obj['chain']])
                        name = scope + '-direct-all-chains'
                    else:
                        row = ' '.join([obj['family'], 'filter', obj['chain'], obj['priority']] + obj['args'])
                        name = scope + '-direct-all-rules'
                    return {'rc': 0 if row in self.commands[name].splitlines() else 1,
                            'stdout': '', 'stderr': '', 'argv': argv}
                raise AssertionError('Unexpected or mutating firewall command: ' + repr(argv))
        else:
            raise AssertionError('Unexpected command: ' + repr(argv))
        return {'rc': 0, 'stdout': self.commands[name], 'stderr': '', 'argv': argv}

    def filter_edit(self, family, transform):
        name = 'iptables-save' if family == 'ipv4' else 'ip6tables-save'
        before, body = self.commands[name].split('*filter\n', 1)
        body, after = body.split('\nCOMMIT', 1)
        self.commands[name] = before + '*filter\n' + '\n'.join(transform(body.splitlines())) + '\nCOMMIT' + after

    def indirect(self, family):
        def transform(rows):
            result = []
            for row in rows:
                if row.startswith(':FDS_NTP_0101 '):
                    result.append(':OUTPUT_direct - [0:0]')
                if row == HOOK:
                    result.extend([BRIDGE, row.replace('-A OUTPUT ', '-A OUTPUT_direct ', 1)])
                else:
                    result.append(row)
            return result
        self.filter_edit(family, transform)

    def other_table(self, family, table, additions):
        name = 'iptables-save' if family == 'ipv4' else 'ip6tables-save'
        text = self.commands[name]
        marker = '*' + table + '\n'
        if marker not in text:
            text += '\n' + marker + ':OUTPUT ACCEPT [0:0]\nCOMMIT\n'
        before, body = text.split(marker, 1)
        body, after = body.split('\nCOMMIT', 1)
        rows = body.splitlines()
        declarations = [row for row in additions if row.startswith(':')]
        rules = [row for row in additions if not row.startswith(':')]
        index = next((i for i, row in enumerate(rows) if row.startswith('-A ')), len(rows))
        rows[index:index] = declarations
        self.commands[name] = before + marker + '\n'.join(rows + rules) + '\nCOMMIT' + after


class KernelLayoutTests(unittest.TestCase):
    def setUp(self):
        self.no_process = patch.object(M.subprocess, 'Popen', side_effect=AssertionError('Live process forbidden'))
        self.no_process.start()
        self.addCleanup(self.no_process.stop)
        self.no_packet = patch.object(M.socket, 'socket', side_effect=AssertionError('Live socket forbidden'))
        self.no_packet.start()
        self.addCleanup(self.no_packet.stop)

    def validate(self, fw, kernel_only=False):
        engine = M.Engine(request(host=fw.host), MemoryJournal(), runner=fw)
        if kernel_only:
            engine.kernel_topology(fw.commands['runtime-direct-all-rules'])
        else:
            engine.topology()

    def layouts(self):
        for family in ('ipv4', 'ipv6'):
            for layout in ('direct', 'indirect'):
                fw = ReplayFirewall(M.SOURCE)
                if layout == 'indirect':
                    fw.indirect(family)
                yield family, layout, fw

    def test_field_replay_all_six_hosts(self):
        for host in FIXTURE['hosts']:
            with self.subTest(host=host):
                self.validate(ReplayFirewall(host))

    def test_indirect_layout_all_six_hosts(self):
        for host in FIXTURE['hosts']:
            fw = ReplayFirewall(host)
            fw.indirect('ipv4')
            fw.indirect('ipv6')
            with self.subTest(host=host):
                self.validate(fw)

    def test_family_layouts_are_independent(self):
        for family in ('ipv4', 'ipv6'):
            fw = ReplayFirewall(M.SOURCE)
            fw.indirect(family)
            with self.subTest(family=family):
                self.validate(fw)

    def test_hook_missing_or_duplicate(self):
        for family, layout, fw in self.layouts():
            hook = HOOK if layout == 'direct' else HOOK.replace('-A OUTPUT ', '-A OUTPUT_direct ', 1)
            for copies in (0, 2):
                changed = copy.deepcopy(fw)
                changed.filter_edit(family, lambda rows: [value for row in rows for value in ([row] * copies if row == hook else [row])])
                with self.subTest(family=family, layout=layout, copies=copies), self.assertRaises(M.Stop):
                    self.validate(changed)

    def test_mixed_layout_rejected(self):
        for family in ('ipv4', 'ipv6'):
            fw = ReplayFirewall(M.SOURCE)
            fw.indirect(family)
            fw.filter_edit(family, lambda rows: rows + [HOOK])
            with self.subTest(family=family), self.assertRaises(M.Stop):
                self.validate(fw)

    def test_hook_scope_changes_rejected(self):
        changes = [('--ctstate NEW', '--ctstate NEW,ESTABLISHED'), ('--dport 123', '--dport 124'),
                   ('-p udp -m udp', '-p tcp -m tcp'), (' -m conntrack --ctstate NEW', ''),
                   ('-j FDS_NTP_0101', '-g FDS_NTP_0101')]
        for family, layout, fw in self.layouts():
            for old, new in changes:
                changed = copy.deepcopy(fw)
                changed.filter_edit(family, lambda rows: [row.replace(old, new) for row in rows])
                with self.subTest(family=family, layout=layout, change=(old, new)), self.assertRaises(M.Stop):
                    self.validate(changed)

    def test_owned_rule_missing_duplicate_or_changed(self):
        for family, layout, fw in self.layouts():
            for replacement in ('', '-A FDS_NTP_0101 -j RETURN', '-A FDS_NTP_0101 -j ACCEPT',
                                '-A FDS_NTP_0101 -j DROP\n-A FDS_NTP_0101 -j DROP'):
                changed = copy.deepcopy(fw)
                changed.filter_edit(family, lambda rows: [r for row in rows for r in (replacement.splitlines() if row == '-A FDS_NTP_0101 -j DROP' else [row])])
                with self.subTest(family=family, layout=layout, replacement=replacement), self.assertRaises(M.Stop):
                    self.validate(changed)

    def test_drop_before_allow_rejected(self):
        for layout in ('direct', 'indirect'):
            fw = ReplayFirewall(M.SOURCE)
            if layout == 'indirect':
                fw.indirect('ipv4')
            fw.filter_edit('ipv4', lambda rows: ['-A FDS_NTP_0101 -j DROP'] + [row for row in rows if row != '-A FDS_NTP_0101 -j DROP'])
            with self.subTest(layout=layout), self.assertRaises(M.Stop):
                self.validate(fw)

    def test_destination_expansion_rejected(self):
        fw = ReplayFirewall(M.SOURCE)
        fw.filter_edit('ipv4', lambda rows: [row.replace('162.159.200.1/32', '162.159.200.0/24') for row in rows])
        with self.assertRaises(M.Stop):
            self.validate(fw)

    def test_registry_and_kernel_scope_expansion_rejected(self):
        fw = ReplayFirewall(M.SOURCE)
        for name in fw.commands:
            fw.commands[name] = fw.commands[name].replace('--ctstate NEW', '--ctstate NEW,ESTABLISHED')
        with self.assertRaises(M.Stop):
            self.validate(fw)

    def test_duplicate_registry_even_with_duplicate_kernel_rejected(self):
        fw = ReplayFirewall(M.SOURCE)
        name = 'runtime-direct-all-rules'
        duplicate = fw.commands[name].splitlines()[0]
        fw.commands[name] += duplicate + '\n'
        fw.filter_edit('ipv4', lambda rows: rows + ['-A FDS_NTP_0101 -d 162.159.200.1/32 -j RETURN'])
        with self.assertRaises(M.Stop):
            self.validate(fw)

    def test_foreign_filter_chain_references_rejected(self):
        for family, layout, fw in self.layouts():
            for target in ('FDS_NTP_0101', 'OUTPUT_direct'):
                for jump in ('-j', '-g'):
                    changed = copy.deepcopy(fw)
                    changed.filter_edit(family, lambda rows: rows + ['-A FORWARD ' + jump + ' ' + target])
                    with self.subTest(family=family, layout=layout, target=target, jump=jump), self.assertRaises(M.Stop):
                        self.validate(changed)

    def test_other_table_output_direct_is_a_separate_namespace(self):
        # Synthetic compatibility cases; the retained operating evidence is filter/direct.
        for family, layout, fw in self.layouts():
            for table in ('mangle', 'nat', 'raw', 'security'):
                for bridge in (False, True):
                    changed = copy.deepcopy(fw)
                    rows = [':OUTPUT_direct - [0:0]']
                    if bridge:
                        rows += [BRIDGE, '-A OUTPUT_direct -j RETURN']
                    changed.other_table(family, table, rows)
                    with self.subTest(family=family, layout=layout, table=table, bridge=bridge):
                        self.validate(changed)

    def test_other_table_namespace_does_not_mask_filter_drift(self):
        for family, layout, fw in self.layouts():
            hook = HOOK if layout == 'direct' else HOOK.replace('-A OUTPUT ', '-A OUTPUT_direct ', 1)
            for table in ('mangle', 'nat', 'raw', 'security'):
                drifts = ('missing', 'duplicate', 'scope', 'predecessor_accept')
                if layout == 'indirect':
                    drifts += ('bridge_missing',)
                for drift in drifts:
                    changed = copy.deepcopy(fw)
                    changed.other_table(family, table, [':OUTPUT_direct - [0:0]', BRIDGE, '-A OUTPUT_direct -j RETURN'])
                    if drift == 'missing':
                        changed.filter_edit(family, lambda rows: [row for row in rows if row != hook])
                    elif drift == 'duplicate':
                        changed.filter_edit(family, lambda rows: rows + [hook])
                    elif drift == 'scope':
                        changed.filter_edit(family, lambda rows: [row.replace('--ctstate NEW', '--ctstate NEW,ESTABLISHED') for row in rows])
                    elif drift == 'bridge_missing':
                        changed.filter_edit(family, lambda rows: [row for row in rows if row != BRIDGE])
                    else:
                        changed.filter_edit(family, lambda rows: ['-A OUTPUT -j ACCEPT'] + rows)
                    with self.subTest(family=family, layout=layout, table=table, drift=drift), self.assertRaisesRegex(
                            M.Stop, 'NTP hook layout|Unreviewed OUTPUT predecessor'):
                        self.validate(changed)

    def test_dedicated_chain_declaration_in_other_tables_rejected(self):
        for family, layout, fw in self.layouts():
            for table in ('mangle', 'nat', 'raw', 'security'):
                changed = copy.deepcopy(fw)
                changed.other_table(family, table, [':FDS_NTP_0101 - [0:0]'])
                with self.subTest(family=family, layout=layout, table=table), self.assertRaisesRegex(
                        M.Stop, 'Dedicated chain declared outside filter table'):
                    self.validate(changed)

    def test_dedicated_references_or_body_in_other_tables_rejected(self):
        for family, layout, fw in self.layouts():
            for table in ('mangle', 'nat', 'raw', 'security'):
                for rule in ('-A OUTPUT_direct -j FDS_NTP_0101', '-A OUTPUT_direct -g FDS_NTP_0101',
                             '-A FDS_NTP_0101 -j DROP'):
                    changed = copy.deepcopy(fw)
                    # Omit the FDS declaration to exercise the independent rule/body guard.
                    changed.other_table(family, table, [':OUTPUT_direct - [0:0]', BRIDGE, rule])
                    with self.subTest(family=family, layout=layout, table=table, rule=rule), self.assertRaisesRegex(
                            M.Stop, 'Dedicated chain referenced outside filter table'):
                        self.validate(changed)

    def test_bridge_missing_duplicate_conditional_or_goto_rejected(self):
        for family in ('ipv4', 'ipv6'):
            for replacement in ('', BRIDGE + '\n' + BRIDGE, '-A OUTPUT -p udp -j OUTPUT_direct', '-A OUTPUT -g OUTPUT_direct'):
                fw = ReplayFirewall(M.SOURCE)
                fw.indirect(family)
                fw.filter_edit(family, lambda rows: [r for row in rows for r in (replacement.splitlines() if row == BRIDGE else [row])])
                with self.subTest(family=family, replacement=replacement), self.assertRaises(M.Stop):
                    self.validate(fw)

    def test_preceding_accept_return_or_unknown_path_rejected(self):
        for family, layout, fw in self.layouts():
            for predecessor in ('-A OUTPUT -j ACCEPT', '-A OUTPUT -j RETURN', '-A OUTPUT -j UNKNOWN', '-A OUTPUT -g UNKNOWN'):
                changed = copy.deepcopy(fw)
                changed.filter_edit(family, lambda rows: [predecessor] + rows)
                with self.subTest(family=family, layout=layout, predecessor=predecessor), self.assertRaises(M.Stop):
                    self.validate(changed)

    def test_kube_name_does_not_authorize_altered_chain(self):
        for extra in ('-A KUBE-FIREWALL -j ACCEPT', '-A KUBE-FIREWALL -j RETURN', '-A KUBE-FIREWALL -g UNKNOWN'):
            fw = ReplayFirewall(M.SOURCE)
            fw.filter_edit('ipv4', lambda rows: rows + [extra])
            with self.subTest(extra=extra), self.assertRaises(M.Stop):
                self.validate(fw)

    def test_missing_chain_declarations_rejected(self):
        for family, layout, fw in self.layouts():
            fw.filter_edit(family, lambda rows: [row for row in rows if not row.startswith(':FDS_NTP_0101 ')])
            with self.subTest(family=family, layout=layout), self.assertRaises(M.Stop):
                self.validate(fw)

    def test_preapply_and_rollback_empty_chains_with_optional_bridge(self):
        for bridge in (False, True):
            for keep_chain in (False, True):
                fw = ReplayFirewall(M.SOURCE)
                for family in ('ipv4', 'ipv6'):
                    if bridge:
                        fw.indirect(family)
                    fw.filter_edit(family, lambda rows: [row for row in rows if 'FDS_NTP_0101' not in row or (keep_chain and row.startswith(':FDS_NTP_0101 '))])
                fw.commands['runtime-direct-all-rules'] = ''
                if not keep_chain:
                    fw.commands['runtime-direct-all-chains'] = ''
                with self.subTest(bridge=bridge, keep_chain=keep_chain):
                    self.validate(fw, kernel_only=True)

    def test_unregistered_hook_or_nonempty_direct_chain_rejected(self):
        for layout in ('direct', 'indirect'):
            fw = ReplayFirewall(M.SOURCE)
            if layout == 'indirect':
                fw.indirect('ipv4')
            name = 'runtime-direct-all-rules'
            fw.commands[name] = '\n'.join(row for row in fw.commands[name].splitlines() if ' filter OUTPUT ' not in row)
            with self.subTest(layout=layout), self.assertRaises(M.Stop):
                self.validate(fw, kernel_only=True)


if __name__ == '__main__':
    unittest.main()
