"""Host-independent checks. These do not claim an Ansible engine PASS."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import yaml
from ssh_guard_fixtures import cases, extract, generate, FIXTURES

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'playbooks/harden_svc_ansible_key.yml'
spec = importlib.util.spec_from_file_location('runner', HERE / 'test-ssh-key-guards.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class HarnessTests(unittest.TestCase):
    def test_cli_contract_and_stale_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = SimpleNamespace(source=SOURCE, output=root / 'summary.json',
                                   ansible_playbook='ansible-playbook',
                                   expect_engine='2.16.19', timeout=600)
            generate(SOURCE, root)
            stale = root / 'result-empty-0.json'
            stale.write_text('{"stale": true}')

            def public_cli(command, **kwargs):
                self.assertEqual(kwargs['cwd'], root)
                if command[-1] == '--version':
                    self.assertFalse(stale.exists())
                    return SimpleNamespace(stdout='ansible-playbook [core 2.16.19]', stderr='', returncode=0)
                self.assertEqual(command[1:5], ['-i', 'localhost,', '-c', 'local'])
                for case in cases():
                    observation = {'failed_when_result': case['expected_failure'],
                                   'failed': case['expected_failure'], 'rc': case['expected_rc'],
                                   'stdout': case['expected_count']}
                    (root / f"result-{case['case']}-{case['index']}.json").write_text(json.dumps(observation))
                return SimpleNamespace(stdout='synthetic subprocess stub', stderr='', returncode=0)

            with patch.object(runner.subprocess, 'run', side_effect=public_cli):
                self.assertEqual(runner.run(args, root), 0)
            with patch.object(runner.subprocess, 'run', side_effect=FileNotFoundError('engine absent')):
                self.assertEqual(runner.run(args, root), 1)
            summary = json.loads(args.output.read_text())
            self.assertEqual(summary['outcomes']['ERROR'], 14)
            self.assertEqual(summary['status'], 'FAIL')

    def test_engine_mismatch_stops_before_playbook(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = SimpleNamespace(source=SOURCE, output=root / 'summary.json',
                                   ansible_playbook='ansible-playbook',
                                   expect_engine='2.21.3', timeout=600)
            version = SimpleNamespace(stdout='ansible-playbook [core 2.16.19]', returncode=0)
            with patch.object(runner.subprocess, 'run', return_value=version) as process:
                self.assertEqual(runner.run(args, root), 1)
                self.assertEqual(process.call_count, 1)

    def test_fixture_export_and_source_preservation(self):
        original = SOURCE.read_bytes()
        guards, variables = extract(SOURCE)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(len(generate(SOURCE, root)), 14)
            self.assertEqual(yaml.safe_load((root / 'ssh-guards.yml').read_text()), guards)
            self.assertEqual(json.loads((root / 'source-vars.json').read_text()), variables)
            for name, contents in FIXTURES.items():
                path = root / 'fixtures' / name
                if contents is None:
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(path.read_text(), contents)
            play = yaml.safe_load((root / 'regression.yml').read_text())[0]
            self.assertEqual(play['hosts'], 'localhost')
            self.assertFalse(play['become'])
            commands = [t for t in play['tasks'] if 'ansible.builtin.command' in t]
            self.assertEqual(len(commands), 14)
            for i, task in enumerate(commands):
                expected = copy.deepcopy(guards[i % 2])
                expected['name'] = task['name']
                expected['ignore_errors'] = True
                expected['ansible.builtin.command']['argv'][-1] = task['ansible.builtin.command']['argv'][-1]
                self.assertEqual(task, expected)
        self.assertEqual(SOURCE.read_bytes(), original)

    def test_missing_fixture_collision_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generate(SOURCE, root)
            (root / 'fixtures' / 'missing').write_text('unexpected')
            with self.assertRaises(ValueError):
                generate(SOURCE, root)

    def test_all_independent_expectations(self):
        for case in cases():
            observation = {'rc': case['expected_rc'], 'stdout': case['expected_count'],
                           'failed_when_result': case['expected_failure'],
                           'failed': case['expected_failure']}
            self.assertEqual(runner.classify(case, observation)['outcome'], 'PASS')
            observation['failed_when_result'] = not case['expected_failure']
            self.assertEqual(runner.classify(case, observation)['outcome'], 'FAIL')

    def test_expression_errors_cannot_pass_as_expected_rejection(self):
        case = next(cases())
        for value in ('The conditional check failed', 'true', None, 1, {}):
            observation = {'rc': 1, 'stdout': '0', 'failed': True,
                           'failed_when_result': value}
            self.assertEqual(runner.classify(case, observation)['outcome'], 'ERROR')

    def test_engine221_expected_rejection_with_exception_diagnostics(self):
        # Observed in the submitted 2.21.3 CLI evidence (commit 3fdcc6b):
        # exception is present for failed_when=True with grep rc 0, 1, and 2.
        for case in cases():
            if not case['expected_failure']:
                continue
            observation = {'rc': case['expected_rc'], 'stdout': case['expected_count'],
                           'failed': True, 'failed_when_result': True,
                           'exception': '(traceback unavailable)',
                           'failed_when_suppressed_exception': '(traceback unavailable)'}
            self.assertEqual(runner.classify(case, observation)['outcome'], 'PASS')
            observation['failed_when_result'] = "Error while evaluating conditional: 'undefined_ssh_guard_probe' is undefined"
            self.assertEqual(runner.classify(case, observation)['outcome'], 'ERROR')

    def test_exception_diagnostics_do_not_hide_missing_or_wrong_grep_results(self):
        case = next(cases())
        observation = {'rc': 1, 'stdout': '0', 'failed': True,
                       'failed_when_result': True, 'exception': '(traceback unavailable)'}
        for value in (None, 0, [], {}):
            self.assertEqual(runner.classify(case, dict(observation, stdout=value))['outcome'], 'ERROR')
        missing = dict(observation)
        missing.pop('stdout')
        self.assertEqual(runner.classify(case, missing)['outcome'], 'ERROR')
        self.assertEqual(runner.classify(case, dict(observation, rc=127))['outcome'], 'FAIL')
        self.assertEqual(runner.classify(case, dict(observation, stdout='2'))['outcome'], 'FAIL')

    def test_transport_and_missing_results_fail_closed(self):
        case = next(cases())
        for observation in ({}, {'unreachable': True}, {'skipped': True},
                            {'rc': '1', 'stdout': '0', 'failed': True, 'failed_when_result': True}):
            self.assertEqual(runner.classify(case, observation)['outcome'], 'ERROR')

    def test_unexpected_command_shape_rejected(self):
        data = yaml.safe_load(SOURCE.read_text())
        data[0]['tasks'][0]['delegate_to'] = 'remote'
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.yml'
            source.write_text(yaml.safe_dump(data))
            with self.assertRaises(ValueError):
                extract(source)


if __name__ == '__main__':
    unittest.main()
