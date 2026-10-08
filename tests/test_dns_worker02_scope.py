"""Real Ansible target selection with local-only inventory and a stub DNS role.

The production playbook is copied unchanged. This tests scope/fail-stop behavior,
not DNS correctness, SSH, sudo, or the operational role. Run using each pinned
venv's Python; a missing sibling ansible-playbook is an error, not a skipped PASS.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Worker02Scope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cli = Path(sys.executable).parent / 'ansible-playbook'
        self.assertTrue(self.cli.is_file(), 'Run with a pinned Ansible venv Python')
        self.playbook = self.root / 'verify.yml'
        shutil.copyfile(ROOT / 'playbooks/cr-p1-ans-01-01-verify-worker02.yml', self.playbook)
        role = self.root / 'roles/dns_resolver/tasks'
        role.mkdir(parents=True)
        self.role = role / 'main.yml'
        self.role.write_text('''---
- ansible.builtin.assert:
    that:
      - inventory_hostname == 'k8s-worker02'
      - cr_dns_phase == 'verify'
- ansible.builtin.debug:
    msg: SCOPE_FIXTURE_REACHED
''')
        self.inventory = {'all': {'vars': {
            'ansible_connection': 'local', 'ansible_become': False,
            'ansible_python_interpreter': sys.executable,
            'ansible_user': 'svc_ansible'}, 'children': {
                'k8s_nodes': {'children': {'k8s_workers': {'hosts': {
                    'k8s-worker01': {'ansible_host': '10.1.93.105'},
                    'k8s-worker02': {'ansible_host': '10.1.93.107'},
                    'k8s-worker03': {'ansible_host': '10.1.93.108'},
                }}}}}}}
        config = self.root / 'ansible.cfg'
        config.write_text('[defaults]\nroles_path = ' + str(self.root / 'roles') +
                          '\nretry_files_enabled = False\nhost_key_checking = True\n')
        self.env = {'HOME': str(self.root), 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8',
                    'ANSIBLE_CONFIG': str(config), 'ANSIBLE_NOCOLOR': '1',
                    'ANSIBLE_LOCAL_TEMP': str(self.root / 'local-tmp')}

    def invoke(self, inventory=None):
        path = self.root / 'inventory.json'
        path.write_text(json.dumps(self.inventory if inventory is None else inventory))
        return subprocess.run([str(self.cli), '-i', str(path), str(self.playbook)],
                              cwd=self.root, env=self.env, text=True,
                              capture_output=True, timeout=90)

    def assert_blocked(self, inventory):
        result = self.invoke(inventory)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('NOT RUN:', result.stdout)
        self.assertNotIn('SCOPE_FIXTURE_REACHED', result.stdout)
        self.assertNotIn('TASK [Gathering Facts]', result.stdout)

    def test_exact_worker02_only_with_other_workers_present(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SCOPE_FIXTURE_REACHED', result.stdout)
        self.assertIn('ok: [k8s-worker02]', result.stdout)
        self.assertNotIn('ok: [k8s-worker01]', result.stdout)
        self.assertNotIn('ok: [k8s-worker03]', result.stdout)

    def test_missing_worker02_stops_before_managed_play(self):
        inventory = copy.deepcopy(self.inventory)
        del inventory['all']['children']['k8s_nodes']['children']['k8s_workers']['hosts']['k8s-worker02']
        self.assert_blocked(inventory)

    def test_empty_inventory_is_not_success(self):
        self.assert_blocked({'all': {'hosts': {}}})

    def test_group_named_worker02_cannot_expand_scope(self):
        inventory = copy.deepcopy(self.inventory)
        inventory['all']['children']['k8s-worker02'] = {'hosts': {'k8s-worker01': {}}}
        self.assert_blocked(inventory)

    def test_group_only_alias_cannot_select_worker01(self):
        inventory = copy.deepcopy(self.inventory)
        del inventory['all']['children']['k8s_nodes']['children']['k8s_workers']['hosts']['k8s-worker02']
        inventory['all']['children']['k8s-worker02'] = {'hosts': {'k8s-worker01': {}}}
        self.assert_blocked(inventory)

    def test_wrong_address_or_account_stops(self):
        for field, value in [('ansible_host', '10.1.93.105'), ('ansible_user', 'root')]:
            with self.subTest(field=field):
                inventory = copy.deepcopy(self.inventory)
                inventory['all']['children']['k8s_nodes']['children']['k8s_workers']['hosts']['k8s-worker02'][field] = value
                self.assert_blocked(inventory)

    def test_wrong_group_membership_stops(self):
        inventory = copy.deepcopy(self.inventory)
        workers = inventory['all']['children']['k8s_nodes']['children'].pop('k8s_workers')
        inventory['all']['children']['other'] = workers
        self.assert_blocked(inventory)

    def test_role_failure_is_not_swallowed(self):
        self.role.write_text('---\n- ansible.builtin.fail:\n    msg: SYNTHETIC_DNS_FAILURE\n')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SYNTHETIC_DNS_FAILURE', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
