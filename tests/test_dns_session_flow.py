"""Real Ansible role flow with simulated NetworkManager and real temp snapshots.

Only external I/O modules are replaced in a temporary copy. Production task
ordering, when/rescue/assert logic and snapshot implementation run unchanged.
No managed endpoint, privilege escalation, service or network operation occurs.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = '''
from ansible.plugins.action import ActionBase
import base64, importlib.util, json, os
from pathlib import Path
class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        root = Path(os.environ['FDS_DNS_FIXTURE'])
        statepath = root / 'state.json'
        state = json.loads(statepath.read_text())
        args = self._task.args
        kind = self._task.action
        if kind == 'fixture_session':
            spec = importlib.util.spec_from_file_location('dns', root / 'snapshot.py')
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            try:
                return mod.run(args['action'], args['session_id'], args['source_sha'],
                               args['current'], args['desired'], args['expected_sha256'],
                               self._play_context.check_mode, root=root / 'snapshots', uid=os.geteuid())
            except Exception as exc:
                return {'failed': True, 'msg': str(exc)}
        if kind == 'fixture_forbidden':
            return {'failed': True, 'msg': 'LEGACY_BACKUP_MUST_NOT_RUN'}
        if kind == 'fixture_wait':
            return {'changed': False}
        if kind == 'fixture_slurp':
            text = ''.join('nameserver ' + x + '\\n' for x in state['ipv4.dns'].replace(',', ' ').split())
            text += 'search ' + state['ipv4.dns-search'] + '\\n'
            return {'changed': False, 'content': base64.b64encode(text.encode()).decode()}
        argv = args['argv']; out = ''
        if argv[0] == 'nmcli':
            if argv[1] == '--get-values':
                out = 'System eth0' if argv[2] == 'GENERAL.CONNECTION' else state[argv[2]]
            elif argv[1:3] == ['connection', 'modify']:
                if self._play_context.check_mode: return {'skipped': True, 'changed': False}
                state['writes'].append(argv)
                for i in range(4, len(argv), 2): state[argv[i]] = argv[i+1]
            elif argv[1:3] == ['device', 'reapply']:
                if self._play_context.check_mode: return {'skipped': True, 'changed': False}
                state['writes'].append(argv)
                if state.get('fail_reapply_once'):
                    state['fail_reapply_once'] = False
                    statepath.write_text(json.dumps(state))
                    return {'failed': True, 'rc': 1, 'stdout': '', 'stderr': 'SYNTHETIC_REAPPLY_FAILURE'}
            else: raise AssertionError(argv)
        elif argv[0] == 'systemctl': out = 'loaded\\nactive'
        elif argv[0] in ('dig', 'getent'):
            if argv[-1] == 'k8s-api.fds.internal' and state.get('fail_post_verify_once'):
                state['fail_post_verify_once'] = False
                statepath.write_text(json.dumps(state))
                return {'failed': True, 'rc': 1, 'stdout': '', 'stderr': 'SYNTHETIC_POST_VERIFY_FAILURE'}
            out = '10.1.93.109'
        else: raise AssertionError(argv)
        statepath.write_text(json.dumps(state))
        return {'changed': False, 'rc': 0, 'stdout': out, 'stdout_lines': out.splitlines(), 'stderr': ''}
'''


class SessionFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cli = Path(sys.executable).parent / 'ansible-playbook'
        self.assertTrue(self.cli.is_file())
        tasks = self.root / 'roles/dns_resolver/tasks'
        tasks.mkdir(parents=True)
        substitutions = {'ansible.builtin.command:': 'fixture_command:',
                         'ansible.builtin.slurp:': 'fixture_slurp:',
                         'ansible.builtin.wait_for:': 'fixture_wait:',
                         'ansible.builtin.file:': 'fixture_forbidden:',
                         'ansible.builtin.copy:': 'fixture_forbidden:',
                         'fds_dns_session:': 'fixture_session:'}
        for p in (ROOT / 'roles/dns_resolver/tasks').glob('*.yml'):
            content = p.read_text()
            for old, new in substitutions.items(): content = content.replace(old, new)
            (tasks / p.name).write_text(content)
        shutil.copyfile(ROOT / 'library/fds_dns_session.py', self.root / 'snapshot.py')
        plugins = self.root / 'plugins'; plugins.mkdir()
        for name in ('command', 'slurp', 'wait', 'forbidden', 'session'):
            (plugins / ('fixture_' + name + '.py')).write_text(PLUGIN)
        (self.root / 'ansible.cfg').write_text('[defaults]\naction_plugins = ' + str(plugins) +
                                              '\nroles_path = ' + str(self.root / 'roles') + '\n')
        self.statepath = self.root / 'state.json'
        self.original = {'ipv4.dns': '192.0.2.1', 'ipv4.dns-search': 'old.example',
                         'ipv4.ignore-auto-dns': 'no', 'writes': []}
        self.statepath.write_text(json.dumps(self.original))
        self.extra = {'ansible_host': '10.1.93.107', 'ansible_user': 'svc_ansible',
                      'cr_dns_session_enabled': True, 'cr_dns_session_id': 'w02-20261009T150000-1234abcd',
                      'cr_dns_session_source': 'a' * 40, 'cr_dns_change_id': 'CR-P1-ANS-01-01',
                      'cr_dns_change_approved': 'CR-P1-ANS-01-01',
                      'cr_dns_servers': ['10.1.93.52', '10.1.93.53'], 'cr_dns_search_domains': ['fds.internal'],
                      'cr_dns_expected_address': '10.1.93.109', 'cr_dns_internal_name': 'k8s-api.fds.internal',
                      'cr_dns_external_name': 'github.com', 'cr_dns_short_name': 'k8s-api',
                      'ansible_facts': {'default_ipv4': {'interface': 'eth0'}, 'date_time': {'iso8601': 'fixture'}}}

    def invoke(self, action, check=False):
        extra = dict(self.extra, cr_dns_session_action=action,
                     cr_dns_phase='apply' if action in ('apply', 'reapply') else 'precheck')
        (self.root / 'extra.json').write_text(json.dumps(extra))
        entry = 'session-rollback.yml' if action == 'rollback' else 'main.yml'
        (self.root / 'flow.yml').write_text('''---
- hosts: k8s-worker02
  gather_facts: false
  become: false
  tasks:
    - ansible.builtin.include_role:
        name: dns_resolver
        tasks_from: ''' + entry + '\n')
        env = dict(os.environ, ANSIBLE_CONFIG=str(self.root / 'ansible.cfg'), FDS_DNS_FIXTURE=str(self.root),
                   ANSIBLE_NOCOLOR='1', ANSIBLE_LOCAL_TEMP=str(self.root / 'local-tmp'))
        argv = [str(self.cli), '-i', 'k8s-worker02,', '-c', 'local', '-e', '@extra.json', 'flow.yml']
        if check: argv.append('--check')
        return subprocess.run(argv, cwd=self.root, env=env, text=True, capture_output=True, timeout=90)

    def prepare(self):
        result = self.invoke('prepare')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.path = self.root / 'snapshots' / self.extra['cr_dns_session_id'] / 'original-resolver.json'
        self.extra['cr_dns_session_sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(json.loads(self.statepath.read_text())['writes'], [])

    def test_full_flow_reapply_changes_zero_and_rollback_restores_original(self):
        self.prepare()
        original_bytes = self.path.read_bytes()
        result = self.invoke('apply', check=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.statepath.read_text())['writes'], [])
        for action in ('apply', 'reapply'):
            result = self.invoke(action)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(json.loads(self.statepath.read_text())['writes']), 2)
        result = self.invoke('rollback')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        restored = json.loads(self.statepath.read_text())
        for key in self.original:
            if key != 'writes': self.assertEqual(restored[key], self.original[key])
        self.assertEqual(self.path.read_bytes(), original_bytes)

    def test_bad_hash_blocks_before_any_modify(self):
        self.prepare()
        self.extra['cr_dns_session_sha256'] = '0' * 64
        for action in ('apply', 'rollback'):
            result = self.invoke(action)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SHA256 mismatch', result.stdout)
            self.assertEqual(json.loads(self.statepath.read_text())['writes'], [])

    def test_apply_failure_runs_rescue_then_stays_failed(self):
        self.prepare()
        state = json.loads(self.statepath.read_text()); state['fail_reapply_once'] = True
        self.statepath.write_text(json.dumps(state))
        result = self.invoke('apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SYNTHETIC_REAPPLY_FAILURE', result.stdout)
        restored = json.loads(self.statepath.read_text())
        for key in self.original:
            if key != 'writes': self.assertEqual(restored[key], self.original[key])
        self.assertEqual(len(restored['writes']), 4)

    def test_post_validation_failure_runs_rescue_and_stays_failed(self):
        self.prepare()
        state = json.loads(self.statepath.read_text()); state['fail_post_verify_once'] = True
        self.statepath.write_text(json.dumps(state))
        result = self.invoke('apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SYNTHETIC_POST_VERIFY_FAILURE', result.stdout)
        restored = json.loads(self.statepath.read_text())
        for key in self.original:
            if key != 'writes': self.assertEqual(restored[key], self.original[key])
        self.assertEqual(len(restored['writes']), 4)

    def test_unrelated_drift_stops_reapply_and_manual_rollback(self):
        self.prepare()
        result = self.invoke('apply')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = json.loads(self.statepath.read_text()); state['ipv4.dns'] = '192.0.2.99'
        self.statepath.write_text(json.dumps(state))
        for action in ('reapply', 'rollback'):
            result = self.invoke(action)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(self.statepath.read_text())['writes'], state['writes'])
