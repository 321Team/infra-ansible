"""Matrix omissions and process failures must stop the CI gate without Linux."""
import ast
import copy
import importlib.util
import json
import re
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

# Review contract, deliberately independent from the YAML's configurable input.
ISOLATED_LABELS = ['self-hosted', 'Linux', 'X64', 'fds-ci', 'ansible-isolated']
ISOLATED_SETTING = json.dumps(ISOLATED_LABELS, separators=(',', ':'))


def workflow_gate_model(expression, values):
    """String-only model of this template; not GitHub's expression engine."""
    expression = re.sub(r'(?:vars|github)(?:\.[A-Za-z_]+)+',
                        lambda match: repr(values[match.group()]), expression)
    tree = ast.parse(expression.replace('&&', 'and').replace('||', 'or').strip(), mode='eval')

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is str:
            # GitHub's string equality is case-insensitive. Inputs here are ASCII.
            return node.value.casefold()
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            results = [visit(child) for child in node.values]
            return all(results) if isinstance(node.op, ast.And) else any(results)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = visit(node.left), visit(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise ValueError('Unsupported workflow expression in the local model')

    return visit(tree)


def workflow_cases(job):
    repo = '321Team/infra-ansible'
    cases = [
        ('same-repo', 'true', ISOLATED_SETTING, 'pull_request', repo, True),
        ('manual', 'true', ISOLATED_SETTING, 'workflow_dispatch', '', True),
        ('case-insensitive', 'TRUE', ISOLATED_SETTING.lower(), 'pull_request', repo.upper(), True),
        ('disabled', 'false', ISOLATED_SETTING, 'pull_request', repo, False),
        ('enabled-unset', '', ISOLATED_SETTING, 'pull_request', repo, False),
        ('enabled-not-boolean-text', '1', ISOLATED_SETTING, 'pull_request', repo, False),
        ('labels-unset', 'true', '', 'pull_request', repo, False),
        ('labels-malformed', 'true', 'not-json', 'pull_request', repo, False),
        ('labels-empty-array', 'true', '[]', 'pull_request', repo, False),
        ('labels-null', 'true', 'null', 'pull_request', repo, False),
        ('labels-group-object', 'true', '{"group":"unreviewed"}', 'pull_request', repo, False),
        ('labels-broad', 'true', '["self-hosted"]', 'pull_request', repo, False),
        ('labels-hosted', 'true', '["ubuntu-latest"]', 'pull_request', repo, False),
        ('labels-missing-isolation', 'true', '["self-hosted","Linux","X64","fds-ci"]', 'pull_request', repo, False),
        ('labels-reordered', 'true', json.dumps(list(reversed(ISOLATED_LABELS)), separators=(',', ':')), 'pull_request', repo, False),
        ('labels-spaced', 'true', json.dumps(ISOLATED_LABELS), 'pull_request', repo, False),
        ('fork', 'true', ISOLATED_SETTING, 'pull_request', 'other/infra-ansible', False),
        ('missing-pr-repository', 'true', ISOLATED_SETTING, 'pull_request', '', False),
        ('pull-request-target', 'true', ISOLATED_SETTING, 'pull_request_target', repo, False),
        ('push', 'true', ISOLATED_SETTING, 'push', repo, False),
        ('workflow-call', 'true', ISOLATED_SETTING, 'workflow_call', repo, False),
        ('unknown-event', 'true', ISOLATED_SETTING, 'unknown', repo, False),
    ]
    results = []
    for name, enabled, labels, event, head_repo, expected_gate in cases:
        values = {'vars.ANSIBLE_CI_ENABLED': enabled, 'vars.ANSIBLE_CI_RUNNER_LABELS': labels,
                  'github.event_name': event, 'github.event.pull_request.head.repo.full_name': head_repo,
                  'github.repository': repo}
        gate = workflow_gate_model(job['if'], values)
        results.append({'case': name, 'expected': expected_gate, 'observed_model': gate,
                        'selector': job['runs-on'],
                        'passed': gate == expected_gate and job['runs-on'] == ISOLATED_LABELS})
    return results

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

    def test_artifact_export_failure_marks_writable_results_failed(self):
        original = Path.write_text
        def fail_manifest(path, text, *args, **kwargs):
            if path.name == 'SHA256SUMS' and path.parent.name == 'artifact':
                raise OSError(28, 'SYNTHETIC_STORAGE_FAULT')
            return original(path, text, *args, **kwargs)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            with patch.object(Path, 'write_text', fail_manifest):
                result, _, _ = self.run_fake(out)
            self.assertEqual(result['status'], 'FAIL')
            self.assertEqual(result['artifact_export']['status'], 'FAILED')
            self.assertEqual(result['artifact_export']['errno'], 28)
            for path in (out / 'CI_RESULT.json', out / 'artifact/CI_RESULT.json'):
                self.assertEqual(json.loads(path.read_text())['status'], 'FAIL')
            self.assertFalse((out / 'artifact/SHA256SUMS').exists())

    def test_cli_exit_status_tracks_failure(self):
        for status, code in [('PASS',0),('FAIL',1)]:
            with patch('sys.argv',['run-ansible-ci.py','--commit',CODE,'--output','/fake']), \
                 patch.object(ci,'execute',return_value={'status':status}):
                self.assertEqual(ci.main(),code)

    def test_template_cannot_activate_and_leak_token_by_default(self):
        workflow=yaml.load((ROOT/'docs/ci/ansible-regression.workflow.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertEqual(workflow['permissions'],{'contents':'read'})
        self.assertEqual(set(workflow['on']), {'pull_request', 'workflow_dispatch'})
        job=workflow['jobs']['regression']; self.assertIn("vars.ANSIBLE_CI_ENABLED == 'true'",job['if'])
        self.assertEqual(job['runs-on'], ISOLATED_LABELS)
        self.assertEqual(job['steps'][0]['with']['persist-credentials'],'false')
        for step in job['steps']:
            self.assertNotIn('continue-on-error',step)
            if 'uses' in step:self.assertRegex(step['uses'],r'^[^@]+@[0-9a-f]{40}$')

    def test_workflow_gate_and_fixed_selector_for_each_scenario(self):
        workflow = yaml.load((ROOT/'docs/ci/ansible-regression.workflow.yml').read_text(), Loader=yaml.BaseLoader)
        for result in workflow_cases(workflow['jobs']['regression']):
            with self.subTest(case=result['case']):
                self.assertTrue(result['passed'], result)

if __name__ == '__main__': unittest.main()
