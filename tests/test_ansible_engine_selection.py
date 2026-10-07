"""Mock CLI selection tests: no Ansible, SSH, sudo, or operational changes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/lib/ansible-engine.sh'
CLIS = ('ansible-playbook', 'ansible-inventory', 'ansible', 'ansible-config')


class Selection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / 'engine with spaces'
        self.bin.mkdir()
        for cli in CLIS:
            p = self.bin / cli
            p.write_text('#!' + sys.executable + '\n' + '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
if sys.argv[1:] == ['--version']:
    if os.environ.get('FAIL_VERSION') == name:
        sys.exit(8)
    version = '9.0.0' if os.environ.get('WRONG_VERSION') == name else os.environ.get('MOCK_VERSION', '2.21.3')
    print(name + ' [core ' + version + ']')
else:
    print(json.dumps({'cli': name, 'argv': sys.argv[1:], 'tty': os.environ.get('ANSIBLE_SSH_USETTY'), 'path': os.environ['PATH']}))
    sys.exit(int(os.environ.get('MOCK_RC', '0')))
''')
            p.chmod(0o700)

    def invoke(self, cli='ansible-playbook', selected=True, **updates):
        env = {'HOME': self.tmp.name, 'PATH': str(self.bin) + ':/usr/bin:/bin'}
        if selected:
            env.update(FDS_ANSIBLE_ENGINE_DIR=str(self.bin), FDS_ANSIBLE_ENGINE_VERSION='2.21.3')
        env.update(updates)
        return subprocess.run(['/bin/bash', '-c',
            'source "$1"; fds_engine_init || exit "$?"; fds_engine_exec "$2" "argument with spaces"',
            'fixture', str(HELPER), cli], env=env, capture_output=True, text=True)

    def test_all_selected_clis_and_argument_boundaries(self):
        for cli in CLIS:
            with self.subTest(cli=cli):
                r = self.invoke(cli)
                self.assertEqual(r.returncode, 0, r.stderr)
                data = json.loads(r.stdout)
                self.assertEqual(data['cli'], cli)
                self.assertEqual(data['argv'], ['argument with spaces'])
                self.assertEqual(data['tty'], 'false')
                self.assertEqual(data['path'], str(self.bin) + ':/usr/bin:/bin')
                self.assertIn('FDS_ENGINE_EXEC=', r.stderr)

    def test_unset_preserves_path_and_tty(self):
        r = self.invoke(selected=False, ANSIBLE_SSH_USETTY='true')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)['tty'], 'true')
        self.assertEqual(r.stderr, '')

    def test_old_engine_can_be_explicitly_selected(self):
        r = self.invoke(FDS_ANSIBLE_ENGINE_VERSION='2.16.19', MOCK_VERSION='2.16.19')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_selected_command_failure_propagates(self):
        self.assertEqual(self.invoke(MOCK_RC='7').returncode, 7)

    def test_relative_and_missing_directory_rejected(self):
        for value in ('relative', '/nonexistent/issue9-engine'):
            r = self.invoke(FDS_ANSIBLE_ENGINE_DIR=value)
            self.assertEqual(r.returncode, 64)
            self.assertEqual(r.stdout, '')

    def test_missing_cli_no_path_fallback(self):
        (self.bin / 'ansible-config').unlink()
        r = self.invoke()
        self.assertEqual(r.returncode, 64)
        self.assertEqual(r.stdout, '')

    def test_each_version_mismatch_blocks_execution(self):
        for cli in CLIS:
            with self.subTest(cli=cli):
                r = self.invoke(WRONG_VERSION=cli)
                self.assertEqual(r.returncode, 64)
                self.assertEqual(r.stdout, '')

    def test_version_query_failure_blocks_execution(self):
        r = self.invoke(FAIL_VERSION='ansible-inventory')
        self.assertEqual(r.returncode, 64)
        self.assertEqual(r.stdout, '')

    def test_missing_or_unsupported_expected_version(self):
        for value in ('', '2.22.0'):
            self.assertEqual(self.invoke(FDS_ANSIBLE_ENGINE_VERSION=value).returncode, 64)

    def test_version_without_directory_rejected(self):
        self.assertEqual(self.invoke(selected=False, FDS_ANSIBLE_ENGINE_VERSION='2.21.3').returncode, 64)

    def test_unsupported_cli_rejected(self):
        self.assertEqual(self.invoke('python3').returncode, 64)

    def wrapper(self, name, action, rc=0):
        repo = Path(self.tmp.name) / ('repo-' + name + '-' + action + '-' + str(rc))
        (repo / 'scripts/lib').mkdir(parents=True)
        (repo / 'tools').mkdir()
        (repo / 'inventory/group_vars').mkdir(parents=True)
        for path in ('inventory/hosts.yml', 'inventory/group_vars/all.yml', 'key'):
            (repo / path).write_text('synthetic fixture\n')
        shutil.copyfile(HELPER, repo / 'scripts/lib/ansible-engine.sh')
        shutil.copyfile(ROOT / 'scripts' / name, repo / 'scripts' / name)
        # Only exercise wrapper dispatch. The real NTP lock implementation is
        # deliberately not mocked into a claim about lock/FD correctness.
        (repo / 'tools/ntp-workflow-lock.py').write_text(
            'import sys\nassert sys.argv[1:] == ["--check-inherited", "9"]\n')
        mock = repo / 'mock'
        mock.mkdir()
        programs = {
            'hostnamectl': '#!/bin/sh\nprintf "ansible01\\n"\n',
            'id': '#!/bin/sh\nprintf "server01_ansible\\n"\n',
            'git': '#!' + sys.executable + '\n' + '''
import os, sys
args = sys.argv[1:]
if '--show-toplevel' in args:
    print(os.environ['FIXTURE_REPO'])
elif 'rev-parse' in args:
    print('5' * 40)
''',
        }
        for key, value in programs.items():
            p = mock / key
            p.write_text(value)
            p.chmod(0o700)
        env = {'HOME': str(repo), 'PATH': str(mock) + ':' + str(self.bin) + ':/usr/bin:/bin',
               'FIXTURE_REPO': str(repo), 'ANSIBLE_PRIVATE_KEY_FILE': str(repo / 'key'),
               'CR_EVIDENCE_DIR': str(repo / 'evidence'), 'GATE0_EVIDENCE_DIR': str(repo / 'evidence'),
               'CR_NTP_WORKFLOW_LOCK_FD': '9', 'FDS_ANSIBLE_ENGINE_DIR': str(self.bin),
               'FDS_ANSIBLE_ENGINE_VERSION': '2.21.3', 'MOCK_RC': str(rc)}
        return subprocess.run(['/bin/bash', str(repo / 'scripts' / name), action],
                              cwd=repo, env=env, capture_output=True, text=True)

    def test_four_wrapper_dispatch_and_failure_propagation(self):
        for name, action in [('cr-p1-ans-01-01-run.sh', 'verify'),
                             ('cr-p1-mon-01-01-run.sh', 'verify'),
                             ('cr-p1-ntp-01-01-run.sh', 'verify'),
                             ('p1-k8s-01-gate0-run.sh', 'syntax')]:
            for rc in (0, 7):
                with self.subTest(wrapper=name, rc=rc):
                    r = self.wrapper(name, action, rc)
                    self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
                    self.assertIn('"cli": "ansible-playbook"', r.stdout)
                    self.assertIn('"tty": "false"', r.stdout)

    def test_existing_change_approval_still_blocks(self):
        for name, action in [('cr-p1-ans-01-01-run.sh', 'workers'),
                             ('cr-p1-mon-01-01-run.sh', 'apply'),
                             ('cr-p1-ntp-01-01-run.sh', 'source')]:
            with self.subTest(wrapper=name):
                r = self.wrapper(name, action)
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn('"cli":', r.stdout)

    def test_dns_worker02_dispatch_is_separate_and_propagates_failure(self):
        for rc in (0, 7):
            with self.subTest(rc=rc):
                r = self.wrapper('cr-p1-ans-01-01-run.sh', 'verify-worker02', rc)
                self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
                calls = [json.loads(line) for line in r.stdout.splitlines() if line.startswith('{')]
                self.assertEqual(len(calls), 1)
                self.assertTrue(calls[0]['argv'][-1].endswith('/cr-p1-ans-01-01-verify-worker02.yml'))
                self.assertNotIn('--extra-vars', calls[0]['argv'])
                self.assertNotIn('-e', calls[0]['argv'])
                self.assertIn('"tty": "false"', r.stdout)


if __name__ == '__main__':
    unittest.main()
