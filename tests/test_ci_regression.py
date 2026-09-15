"""Matrix omissions and process failures must stop the CI gate without Linux."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
import regression_expectations as expected

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ci_runner', ROOT / 'tools/run-ansible-ci.py')
ci = importlib.util.module_from_spec(spec); spec.loader.exec_module(ci)
CODE = 'a' * 40

def rows(variants, field):
    return [{'engine': e, field: c, 'passed': True} for e in expected.ENGINES for c in variants]

class MatrixCoverageTests(unittest.TestCase):
    def test_guard_and_callback_complete_identities(self):
        self.assertTrue(expected.complete_guards(rows(expected.GUARD_VARIANTS, 'variant')))
        variants = (*expected.CONTRACT_CLI_CASES, *('derived-' + n for n in expected.DERIVED_CASES))
        self.assertTrue(expected.complete_contract(rows(variants, 'case')))

    def test_same_count_duplicate_cannot_hide_missing_case(self):
        for variants, field in [(expected.GUARD_VARIANTS, 'variant'),
            ((*expected.CONTRACT_CLI_CASES, *('derived-' + n for n in expected.DERIVED_CASES)), 'case')]:
            good = rows(variants, field); bad = copy.deepcopy(good); bad[-1] = bad[0]
            self.assertFalse(expected.complete_matrix(bad, variants, field))

    def test_wrong_engine_extra_case_and_nonboolean_pass_rejected(self):
        good = rows(expected.GUARD_VARIANTS, 'variant')
        for update in ({'engine': '2.0.0'}, {'variant': 'unknown'}, {'passed': 1}, {'passed': 'true'}, {'engine': []}):
            bad = copy.deepcopy(good); bad[0].update(update)
            self.assertFalse(expected.complete_guards(bad))
        self.assertFalse(expected.complete_guards(good[:-1]))
        self.assertFalse(expected.complete_guards(good + [good[0]]))

    def test_added_expected_case_requires_execution(self):
        good = rows(expected.GUARD_VARIANTS, 'variant')
        self.assertFalse(expected.complete_matrix(good, (*expected.GUARD_VARIANTS, 'new-probe'), 'variant'))

    def test_engine_lock_and_requirement_files_stay_in_sync(self):
        lock = json.loads((ROOT / 'tools/verification-wheels.lock.json').read_text())
        self.assertEqual(set(lock['engines']), set(expected.ENGINES))
        for engine in expected.ENGINES:
            text = (ROOT / f'tests/requirements-verification-{engine}.txt').read_text()
            pins = dict(line.split('==') for line in text.splitlines() if line and not line.startswith('#'))
            self.assertEqual(pins, lock['engines'][engine])

class CIGateTests(unittest.TestCase):
    def run_fake(self, output, fixture_status='PASS_FRESH_OFFLINE_FIXTURES', fail_syntax=False, fixture_code=CODE):
        calls = []
        def logged(command, cwd, env, directory, timeout):
            calls.append(command)
            self.assertIn('--syntax-check', command)
            self.assertEqual(command[2:6], ['-i', 'localhost,', '-c', 'local'])
            self.assertTrue(str(command[-1]).startswith(str(output / 'runtime/repo')))
            if fail_syntax: raise ValueError('deliberate syntax failure')
        fixture = {'status': fixture_status, 'source_commit': fixture_code}
        with patch.object(ci.kit, 'clean_source'), patch.object(ci.kit, 'target_host'), \
             patch.object(ci.kit, 'build', return_value={'source_commit': CODE, 'archive': '/fake-kit', 'sha256': 'b'*64}), \
             patch.object(ci.kit, 'prepare', return_value={'source_commit': CODE, 'status': 'PREPARED'}), \
             patch.object(ci.kit, 'logged', side_effect=logged), patch.object(ci.kit, 'run', return_value=fixture) as run:
            result = ci.execute(ROOT, CODE, output, Path('/preloaded-wheels'))
            return result, calls, run.call_count

    def test_syntax_and_fixture_success_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'; result, calls, invoked = self.run_fake(out)
            self.assertEqual(result['status'], 'PASS'); self.assertEqual(invoked, 1)
            self.assertEqual(len(calls), len(ci.syntax_paths(ROOT)) * len(expected.ENGINES))
            self.assertEqual(json.loads((out/'artifact/CI_RESULT.json').read_text())['source_commit'], CODE)
            self.assertTrue((out/'artifact/SHA256SUMS').is_file())

    def test_fixture_failure_not_promoted_to_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _, _ = self.run_fake(Path(tmp)/'run', fixture_status='FAIL')
            self.assertEqual(result['status'], 'FAIL')

    def test_wrong_fixture_commit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _, _ = self.run_fake(Path(tmp)/'run', fixture_code='c'*40)
            self.assertEqual(result['status'], 'FAIL')

    def test_syntax_failure_prevents_fixture_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'run'; result, calls, invoked = self.run_fake(out, fail_syntax=True)
            self.assertEqual(result['status'], 'FAIL'); self.assertEqual(len(calls), 1); self.assertEqual(invoked, 0)
            self.assertIn('deliberate syntax failure', (out/'artifact/CI_RESULT.json').read_text())

    def test_existing_output_and_source_output_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); marker=out/'original'; marker.write_text('preserved')
            with self.assertRaises(ValueError): ci.execute(ROOT, CODE, out)
            self.assertEqual(marker.read_text(), 'preserved')
        with self.assertRaises(ValueError): ci.execute(ROOT, CODE, ROOT/'never-create-ci-output')
        with self.assertRaises(ValueError): ci.execute(ROOT, CODE, ROOT.parent/'unrelated/..'/ROOT.name/'never-create-ci-output')
        self.assertFalse((ROOT/'never-create-ci-output').exists())

    def test_bad_source_still_creates_failure_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'run'
            with patch.object(ci.kit, 'clean_source', side_effect=ValueError('dirty source')):
                result=ci.execute(ROOT,CODE,out)
            self.assertEqual(result['status'], 'FAIL')
            self.assertIn('dirty source', (out/'artifact/CI_RESULT.json').read_text())

    def test_cli_exit_status_tracks_failure(self):
        for status, code in [('PASS',0),('FAIL',1)]:
            with patch('sys.argv',['run-ansible-ci.py','--commit',CODE,'--output','/fake']), \
                 patch.object(ci,'execute',return_value={'status':status}):
                self.assertEqual(ci.main(),code)

    def test_template_cannot_activate_and_leak_token_by_default(self):
        workflow=yaml.load((ROOT/'docs/ci/ansible-regression.workflow.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertEqual(workflow['permissions'],{'contents':'read'})
        self.assertNotIn('pull_request_target',workflow['on'])
        job=workflow['jobs']['regression']; self.assertIn("vars.ANSIBLE_CI_ENABLED == 'true'",job['if'])
        self.assertIn('ANSIBLE_CI_RUNNER_LABELS',job['runs-on'])
        self.assertEqual(job['steps'][0]['with']['persist-credentials'],'false')
        for step in job['steps']:
            self.assertNotIn('continue-on-error',step)
            if 'uses' in step:self.assertRegex(step['uses'],r'^[^@]+@[0-9a-f]{40}$')

if __name__ == '__main__': unittest.main()
