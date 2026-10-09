"""Shell entrypoint contract against fake CLIs; no Ansible or SSH execution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SessionWrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        scripts = self.root / 'scripts'; (scripts / 'lib').mkdir(parents=True)
        self.wrapper = scripts / 'cr-p1-ans-01-01-run.sh'
        shutil.copyfile(ROOT / 'scripts' / self.wrapper.name, self.wrapper)
        shutil.copyfile(ROOT / 'scripts/lib/ansible-engine.sh', scripts / 'lib/ansible-engine.sh')
        self.bin = self.root / 'bin'; self.bin.mkdir()
        for name in ('hostnamectl', 'id', 'git', 'ansible-playbook', 'ansible-inventory', 'ansible', 'ansible-config'):
            p = self.bin / name
            p.write_text('#!' + sys.executable + '\n' + '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'hostnamectl': print('ansible01')
elif name == 'id': print('server01_ansible')
elif name == 'git':
    if '--show-toplevel' in args: print(os.environ['MOCK_REPO'])
    elif 'rev-parse' in args: print('a' * 40)
    elif 'diff' in args: sys.exit(int(os.environ.get('MOCK_DIRTY', '0')))
    elif 'ls-files' in args:
        print(os.environ.get('MOCK_UNTRACKED', ''), end='')
        sys.exit(int(os.environ.get('MOCK_LS_FAILURE', '0')))
elif args == ['--version']: print(name + ' [core 2.21.3]')
else:
    with open(os.environ['MOCK_CALLS'], 'a') as stream: stream.write(json.dumps(args) + '\\n')
    sys.exit(int(os.environ.get('MOCK_RC', '0')))
''')
            p.chmod(0o700)
        key = self.root / 'not-a-key'; key.write_text('fixture only')
        self.session = 'w02-20261009T150000-1234abcd'
        self.calls = self.root / 'calls'
        self.env = dict(os.environ, PATH=str(self.bin) + ':/usr/bin:/bin',
                        MOCK_REPO=str(self.root), MOCK_CALLS=str(self.calls),
                        FDS_ANSIBLE_ENGINE_DIR=str(self.bin), FDS_ANSIBLE_ENGINE_VERSION='2.21.3',
                        ANSIBLE_PRIVATE_KEY_FILE=str(key), CR_CHANGE_APPROVED='CR-P1-ANS-01-01',
                        CR_DNS_SOURCE_SHA='a' * 40, CR_EVIDENCE_DIR=str(self.root / 'logs'))

    def invoke(self, action='apply', **env):
        args = ['bash', str(self.wrapper), 'worker02-session', action, self.session]
        if action != 'prepare': args.append('b' * 64)
        merged = dict(self.env, CR_DNS_SESSION_APPROVED=self.session + ':' + action)
        merged.update(env)
        return subprocess.run(args, cwd=self.root, env=merged, text=True, capture_output=True)

    def test_four_actions_use_one_narrow_entrypoint_and_exact_inputs(self):
        for action in ('prepare', 'apply', 'reapply', 'rollback'):
            result = self.invoke(action)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(x) for x in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 4)
        for argv in calls:
            self.assertTrue(argv[-1].endswith('cr-p1-ans-01-01-worker02-session.yml'))
            self.assertIn('cr_dns_session_source=' + 'a' * 40, argv)
            self.assertNotIn('--limit', argv)

    def test_missing_approval_dirty_source_or_unselected_engine_never_invokes_playbook(self):
        for override in ({'CR_DNS_SESSION_APPROVED': ''}, {'CR_CHANGE_APPROVED': ''},
                         {'CR_DNS_SOURCE_SHA': 'b' * 40}, {'MOCK_DIRTY': '1'},
                         {'MOCK_UNTRACKED': 'library/shadow.py'},
                         {'MOCK_LS_FAILURE': '7'},
                         {'FDS_ANSIBLE_ENGINE_DIR': '', 'FDS_ANSIBLE_ENGINE_VERSION': ''}):
            with self.subTest(override=override):
                result = self.invoke(**override)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls.exists())

    def test_check_flags_and_failed_playbook_propagation(self):
        result = self.invoke(CR_DNS_CHECK_ONLY='1', MOCK_RC='7')
        self.assertEqual(result.returncode, 7)
        argv = json.loads(self.calls.read_text())
        self.assertIn('--check', argv)
        self.assertIn('--diff', argv)
