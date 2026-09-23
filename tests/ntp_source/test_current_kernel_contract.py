"""Observed Calico/kube-proxy paths: pin NTP-relevant paths and reject drift.

All input is retained field text. No command, socket, packet, or server is used.
"""
import copy
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((Path(__file__).parent / 'fixtures/current_kernel_20260921_1614.json').read_text())
SOURCE = ROOT / 'tools/ntp-kernel-contract.py'
COMMANDS = ('iptables-save', 'ip6tables-save', 'nft-ruleset', 'ipset-save')
CONTRACT_KEYS = {'iptables_contract', 'ip6tables_contract', 'nft_contract', 'ipset_contract'}


def edit_table(text, name, transform):
    marker = '*' + name + '\n'
    if text.count(marker) != 1:
        raise AssertionError('Expected one table: '+name)
    start = text.index(marker) + len(marker)
    end = text.index('\nCOMMIT', start)
    return text[:start] + '\n'.join(transform(text[start:end].splitlines())) + text[end:]


def insert_before_first_rule(text, table, rule):
    def change(rows):
        first = next(i for i, row in enumerate(rows) if row.startswith('-A '))
        return rows[:first] + [rule] + rows[first:]
    return edit_table(text, table, change)


def replace_once(text, before, after):
    if before not in text:
        raise AssertionError('Mutation anchor absent: '+before)
    return text.replace(before, after, 1)


def edit_nft_chain(text, table, chain, transform):
    table_start = text.index('table '+table+' {')
    table_end = text.index('\n}', table_start)
    chain_start = text.index('\tchain '+chain+' {\n', table_start)
    if chain_start >= table_end:
        raise AssertionError('Chain outside the selected table')
    body_start = text.index('\n', chain_start) + 1
    body_end = text.index('\n\t}', body_start)
    return text[:body_start] + '\n'.join(transform(text[body_start:body_end].splitlines())) + text[body_end:]


class CurrentKernelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process = mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('Live process forbidden'))
        cls.packet = mock.patch.object(socket, 'socket', side_effect=AssertionError('Live socket forbidden'))
        cls.process_mock = cls.process.start()
        cls.packet_mock = cls.packet.start()
        cls.addClassCleanup(cls.process.stop)
        cls.addClassCleanup(cls.packet.stop)
        spec = importlib.util.spec_from_file_location('ntp_current_kernel_contract_under_test', SOURCE)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.process_mock.assert_not_called()
        cls.packet_mock.assert_not_called()

    def validate(self, host='k8s-control01', **overrides):
        values = dict(FIXTURE['hosts'][host]['commands'])
        values.update(overrides)
        return self.module.validate_kernel(host, *(values[name] for name in COMMANDS))

    def reject_each_host(self, command, mutate):
        for host, record in FIXTURE['hosts'].items():
            with self.subTest(host=host, command=command):
                original = record['commands'][command]
                changed = mutate(original)
                self.assertNotEqual(original, changed)
                with self.assertRaises(ValueError):
                    self.validate(host, **{command: changed})

    def test_all_six_retained_field_contracts_match(self):
        self.assertEqual(FIXTURE['source_archive_sha256'],
                         '7945a9bc4c18f0bc05d22dc329773b9820134e57cdaa764cfcd8cc21f218fcb6')
        self.assertEqual(set(FIXTURE['hosts']), {'k8s-control01', 'k8s-control02', 'k8s-control03',
                                               'k8s-worker01', 'k8s-worker02', 'k8s-worker03'})
        for host in FIXTURE['hosts']:
            with self.subTest(host=host):
                receipt = self.validate(host)
                self.assertEqual(set(receipt), CONTRACT_KEYS)
                self.assertTrue(all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                                    for value in receipt.values()))

    def test_ipv4_early_new_ntp_accept_is_rejected(self):
        self.reject_each_host('iptables-save', lambda text: insert_before_first_rule(text, 'filter',
            '-A OUTPUT -p udp -m udp --dport 123 -m conntrack --ctstate NEW -j ACCEPT'))

    def test_ipv6_early_new_ntp_accept_is_rejected(self):
        self.reject_each_host('ip6tables-save', lambda text: insert_before_first_rule(text, 'filter',
            '-A OUTPUT -p udp -m udp --dport 123 -m conntrack --ctstate NEW -j ACCEPT'))

    def test_unknown_ntp_dnat_is_rejected(self):
        self.reject_each_host('iptables-save', lambda text: insert_before_first_rule(text, 'nat',
            '-A OUTPUT -p udp -m udp --dport 123 -j DNAT --to-destination 162.159.200.1:123'))

    def test_udp123_service_dispatch_cannot_be_excluded_as_non_ntp(self):
        self.reject_each_host('iptables-save', lambda text: replace_once(text,
            '-d 10.96.0.10/32 -p udp -m comment --comment "kube-system/kube-dns:dns cluster IP" -m udp --dport 53',
            '-d 10.96.0.10/32 -p udp -m comment --comment "kube-system/kube-dns:dns cluster IP" -m udp --dport 123'))

    def test_negated_service_port_cannot_be_excluded_as_non_ntp(self):
        self.reject_each_host('iptables-save', lambda text: replace_once(text,
            '-d 10.96.0.10/32 -p udp -m comment --comment "kube-system/kube-dns:dns cluster IP" -m udp --dport 53',
            '-d 10.96.0.10/32 -p udp -m comment --comment "kube-system/kube-dns:dns cluster IP" -m udp ! --dport 53'))

    def test_native_output_hook_priority_change_is_rejected(self):
        self.reject_each_host('nft-ruleset', lambda text: replace_once(text,
            'type filter hook output priority filter + 10; policy accept;',
            'type filter hook output priority filter - 10; policy accept;'))

    def test_native_output_early_ntp_accept_is_rejected(self):
        self.reject_each_host('nft-ruleset', lambda text: edit_nft_chain(text, 'ip filter', 'OUTPUT',
            lambda rows: rows[:1] + ['\t\tudp dport 123 ct state new accept'] + rows[1:]))

    def test_native_unknown_dnat_is_rejected(self):
        self.reject_each_host('nft-ruleset', lambda text: edit_nft_chain(text, 'ip nat', 'OUTPUT',
            lambda rows: rows[:1] + ['\t\tudp dport 123 dnat to 162.159.200.1:123'] + rows[1:]))

    def test_new_iptables_table_is_rejected(self):
        self.reject_each_host('iptables-save', lambda text: text +
            '*security\n:INPUT ACCEPT [0:0]\n:FORWARD ACCEPT [0:0]\n:OUTPUT ACCEPT [0:0]\nCOMMIT\n')

    def test_new_native_table_and_hook_are_rejected(self):
        self.reject_each_host('nft-ruleset', lambda text: text +
            'table inet unreviewed {\n\tchain output {\n'
            '\t\ttype filter hook output priority -1; policy accept;\n\t\tudp dport 123 accept\n\t}\n}\n')

    def test_previously_empty_hep_chain_activation_is_rejected(self):
        self.reject_each_host('iptables-save', lambda text: edit_table(text, 'filter', lambda rows:
            rows + ['-A cali-to-host-endpoint -p udp -m udp --dport 123 -j ACCEPT']))

    def test_native_hep_chain_activation_is_rejected(self):
        self.reject_each_host('nft-ruleset', lambda text: replace_once(text,
            '\tchain cali-to-host-endpoint {\n\t}',
            '\tchain cali-to-host-endpoint {\n\t\tudp dport 123 accept\n\t}'))

    def test_fds_allowed_destination_expansion_is_rejected(self):
        for host, record in FIXTURE['hosts'].items():
            with self.subTest(host=host):
                destination = '162.159.200.1' if host == 'k8s-control01' else '10.1.93.102'
                changed = replace_once(record['commands']['iptables-save'],
                    '-A FDS_NTP_0101 -d '+destination+'/32 -j RETURN',
                    '-A FDS_NTP_0101 -d '+destination+'/24 -j RETURN')
                with self.assertRaises(ValueError):
                    self.validate(host, **{'iptables-save':changed})

    def test_fds_drop_replaced_by_return_is_rejected(self):
        self.reject_each_host('iptables-save', lambda text: replace_once(text,
            '-A FDS_NTP_0101 -j DROP', '-A FDS_NTP_0101 -j RETURN'))

    def test_referenced_ipset_membership_change_is_rejected(self):
        self.reject_each_host('ipset-save', lambda text: text + 'add cali40this-host 192.0.2.123\n')

    def test_referenced_ipset_network_expansion_is_rejected(self):
        self.reject_each_host('ipset-save', lambda text: replace_once(text,
            'add cali40network-ip-pools 10.244.0.0/16',
            'add cali40network-ip-pools 0.0.0.0/0'))

    def test_ipset_duplicate_membership_is_not_silently_deduplicated(self):
        self.reject_each_host('ipset-save', lambda text: text +
            next(line for line in text.splitlines() if line.startswith('add cali40this-host ')) + '\n')

    def test_ipset_nomatch_semantics_are_preserved(self):
        self.reject_each_host('ipset-save', lambda text: replace_once(text,
            'add cali40network-ip-pools 10.244.0.0/16',
            'add cali40network-ip-pools 10.244.0.0/16 nomatch'))

    def test_ipv4_dns_and_tcp_service_dispatch_reordering_is_allowed(self):
        def change(rows):
            indices=[i for i,row in enumerate(rows) if row.startswith('-A KUBE-SERVICES -d ')]
            self.assertEqual(len(indices),4)
            values=[rows[i] for i in indices][::-1]
            result=list(rows)
            for index,value in zip(indices,values): result[index]=value
            return result
        for host,record in FIXTURE['hosts'].items():
            with self.subTest(host=host):
                changed=edit_table(record['commands']['iptables-save'],'nat',change)
                self.assertEqual(self.validate(host),self.validate(host,**{'iptables-save':changed}))

    def test_native_dns_and_tcp_service_dispatch_reordering_is_allowed(self):
        def change(rows):
            indices=[i for i,row in enumerate(rows) if 'ip daddr ' in row and ' jump KUBE-SVC-' in row]
            self.assertEqual(len(indices),4)
            values=[rows[i] for i in indices][::-1]
            result=list(rows)
            for index,value in zip(indices,values): result[index]=value
            return result
        for host,record in FIXTURE['hosts'].items():
            with self.subTest(host=host):
                changed=edit_nft_chain(record['commands']['nft-ruleset'],'ip nat','KUBE-SERVICES',change)
                self.assertEqual(self.validate(host),self.validate(host,**{'nft-ruleset':changed}))

    def test_counter_timestamp_and_ipset_hash_seed_changes_are_allowed(self):
        for host,record in FIXTURE['hosts'].items():
            with self.subTest(host=host):
                changed={}
                for command in ('iptables-save','ip6tables-save'):
                    text=re.sub(r'\[[0-9]+:[0-9]+\]','[998:778899]',record['commands'][command])
                    changed[command]=re.sub(r'(?m)^#.*$', '# Later collection timestamp',text)
                changed['nft-ruleset']=re.sub(r'\bcounter packets [0-9]+ bytes [0-9]+\b',
                    'counter packets 778899 bytes 99887766',record['commands']['nft-ruleset'])
                changed['ipset-save']=re.sub(r'\binitval 0x[0-9a-fA-F]+\b',
                    'initval 0x01020304',record['commands']['ipset-save'])
                self.assertEqual(self.validate(host),self.validate(host,**changed))

    def test_ipset_membership_output_order_is_allowed(self):
        for host,record in FIXTURE['hosts'].items():
            with self.subTest(host=host):
                rows=record['commands']['ipset-save'].splitlines()
                creates=[row for row in rows if row.startswith('create ')]
                members=[row for row in rows if row.startswith('add ')][::-1]
                changed='\n'.join(creates+members)+'\n'
                self.assertEqual(self.validate(host),self.validate(host,**{'ipset-save':changed}))

    def test_unknown_host_is_rejected(self):
        raw=FIXTURE['hosts']['k8s-control01']['commands']
        with self.assertRaises(ValueError):
            self.module.validate_kernel('unreviewed-host',*(raw[name] for name in COMMANDS))

    def test_incomplete_pinned_contract_is_rejected(self):
        with mock.patch.dict(self.module.BASELINE, {'k8s-control01': {}}):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                self.validate()

    def test_arp_map_type_or_reference_drift_is_rejected(self):
        for before, after in (
                ('type ifname : verdict', 'type ipv4_addr : verdict'),
                ('vmap @filter-cali-arp-dispatch', 'vmap @missing-map'),
                ('type ifname : verdict', 'type ifname : verdict\n\t\ttimeout 30s')):
            self.reject_each_host('nft-ruleset', lambda text: replace_once(text, before, after))

    def test_arp_map_verdict_and_duplicate_key_are_rejected(self):
        original = FIXTURE['hosts']['k8s-control01']['commands']['nft-ruleset']
        entry = '"calia8163a6cff8" : goto filter-cali-arp-calia8163a6cff8'
        for changed in (replace_once(original, entry, entry + ', ' + entry),
                        replace_once(original, entry, '"calia8163a6cff8" : goto missing-chain'),
                        replace_once(original, entry, '"calia8163a6cff8" : accept'),
                        replace_once(original, entry, '"calia8163a6cff8" : goto FDS_NTP_0101')):
            with self.subTest(change=changed[:40]), self.assertRaises(ValueError):
                self.validate(**{'nft-ruleset': changed})

    def test_unmaterialised_builtin_is_not_excused_with_rule_or_drop(self):
        for policy, rule in (('DROP', None), ('ACCEPT', '-A INPUT -j ACCEPT')):
            def change(text):
                def rows(values):
                    values = [row.replace(':INPUT ACCEPT ', ':INPUT ' + policy + ' ')
                              for row in values]
                    return values + ([rule] if rule else [])
                return edit_table(text, 'mangle', rows)
            self.reject_each_host('iptables-save', change)

    def test_new_hook_in_excluded_service_chain_is_rejected(self):
        for host, record in FIXTURE['hosts'].items():
            raw = record['commands']['nft-ruleset']
            chain = re.search(r'chain (KUBE-SVC-[A-Z0-9]{16}) \{', raw)[1]
            changed = edit_nft_chain(raw, 'ip nat', chain,
                                    lambda rows: ['\t\ttype filter hook output priority -1; policy accept;'] + rows)
            with self.subTest(host=host), self.assertRaises(ValueError):
                self.validate(host, **{'nft-ruleset': changed})

    def test_nft_service_side_effect_before_match_cannot_be_pruned(self):
        self.reject_each_host('nft-ruleset', lambda text: replace_once(text,
            'meta l4proto udp ip daddr 10.96.0.10  udp dport 53',
            'meta mark set 0x10000 meta l4proto udp ip daddr 10.96.0.10  udp dport 53'))


if __name__ == '__main__':
    unittest.main()
