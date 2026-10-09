"""Real Ansible selection tests; all hosts are local and rollback writes are stubbed.

Copy both production play headers, controller guard and the remote leading
assert/end_host checks unchanged. Stub subsequent remote reads/writes with a
marker: no nmcli, service changes, SSH or sudo.
Run with each pinned Ansible venv's Python; missing tooling is a failure.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class RollbackScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cli = Path(sys.executable).parent / 'ansible-playbook'
        self.assertTrue(self.cli.is_file(), 'Run with a pinned Ansible venv Python')
        plays = yaml.safe_load((ROOT / 'playbooks/cr-p1-ans-01-01-rollback.yml').read_text())
        remote = plays[-1]
        checks = []
        for task in remote.get('pre_tasks', []):
            if not ('ansible.builtin.assert' in task or 'ansible.builtin.meta' in task):
                break
            checks.append(task)
        remote['pre_tasks'] = checks
        remote['tasks'] = [{'ansible.builtin.debug': {'msg': 'ROLLBACK_SCOPE_REACHED'}}]
        self.playbook = self.root / 'rollback.yml'
        self.playbook.write_text(yaml.safe_dump(plays, sort_keys=False))
        self.inventory = {'all': {'vars': {
            'ansible_connection': 'local', 'ansible_become': False,
            'ansible_python_interpreter': sys.executable,
            'cr_dns_change_id': 'CR-P1-ANS-01-01'}, 'children': {
                'k8s_nodes': {'hosts': {
                    'k8s-control01': {}, 'k8s-worker01': {},
                    'k8s-worker02': {}, 'k8s-worker03': {}}}}}}
        self.args = {'cr_dns_rollback_host': 'k8s-worker02',
                     'cr_dns_rollback_approved': 'CR-P1-ANS-01-01'}
        config = self.root / 'ansible.cfg'
        config.write_text('[defaults]\nretry_files_enabled = False\nhost_key_checking = True\n')
        self.env = {'HOME': str(self.root), 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8',
                    'ANSIBLE_CONFIG': str(config), 'ANSIBLE_NOCOLOR': '1',
                    'ANSIBLE_LOCAL_TEMP': str(self.root / 'local-tmp')}

    def invoke(self, args=None, inventory=None):
        inv = self.root / 'inventory.json'
        inv.write_text(json.dumps(self.inventory if inventory is None else inventory))
        extra = self.root / 'extra.json'
        extra.write_text(json.dumps(self.args if args is None else args))
        return subprocess.run([str(self.cli), '-i', str(inv), '-e', '@' + str(extra), str(self.playbook)],
                              cwd=self.root, env=self.env, text=True, capture_output=True, timeout=90)

    def assert_blocked(self, args=None, inventory=None):
        result = self.invoke(args, inventory)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('NOT RUN:', result.stdout)
        self.assertNotIn('TASK [Gathering Facts]', result.stdout)
        self.assertNotIn('ROLLBACK_SCOPE_REACHED', result.stdout)

    def test_only_selected_host_collects_facts(self):
        for selected in ('k8s-worker02', 'k8s-control01'):
            with self.subTest(selected=selected):
                result = self.invoke({**self.args, 'cr_dns_rollback_host': selected})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('ROLLBACK_SCOPE_REACHED', result.stdout)
                self.assertIn('ok: [' + selected + ']', result.stdout)
                for other in self.inventory['all']['children']['k8s_nodes']['hosts']:
                    if other != selected:
                        self.assertNotIn('ok: [' + other + ']', result.stdout)

    def test_missing_target(self):
        self.assert_blocked({'cr_dns_rollback_approved': 'CR-P1-ANS-01-01'})

    def test_empty_or_nonstring_target(self):
        for target in ('', [], None):
            with self.subTest(target=target):
                self.assert_blocked({**self.args, 'cr_dns_rollback_host': target})

    def test_missing_or_wrong_approval(self):
        self.assert_blocked({'cr_dns_rollback_host': 'k8s-worker02'})
        self.assert_blocked({**self.args, 'cr_dns_rollback_approved': 'OTHER'})

    def test_unknown_host(self):
        self.assert_blocked({**self.args, 'cr_dns_rollback_host': 'missing'})

    def test_group_and_patterns(self):
        for target in ('k8s_nodes', 'all', 'k8s-worker*', 'k8s-worker01:k8s-worker02'):
            with self.subTest(target=target):
                self.assert_blocked({**self.args, 'cr_dns_rollback_host': target})

    def test_group_host_collision(self):
        inventory = copy.deepcopy(self.inventory)
        inventory['all']['children']['k8s-worker02'] = {'hosts': {'k8s-worker01': {}}}
        self.assert_blocked(inventory=inventory)

    def test_host_outside_k8s_nodes(self):
        inventory = copy.deepcopy(self.inventory)
        del inventory['all']['children']['k8s_nodes']['hosts']['k8s-worker02']
        inventory['all']['hosts'] = {'k8s-worker02': {}}
        self.assert_blocked(inventory=inventory)

    def test_empty_inventory(self):
        self.assert_blocked(inventory={'all': {'vars': {'cr_dns_change_id': 'CR-P1-ANS-01-01'}}})

    def test_remote_failure_propagates(self):
        plays = yaml.safe_load(self.playbook.read_text())
        plays[-1]['tasks'] = [{'ansible.builtin.fail': {'msg': 'SYNTHETIC_ROLLBACK_FAILURE'}}]
        self.playbook.write_text(yaml.safe_dump(plays, sort_keys=False))
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SYNTHETIC_ROLLBACK_FAILURE', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
