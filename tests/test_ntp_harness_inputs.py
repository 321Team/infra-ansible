"""Check generated fixture inputs against production contracts, without Ansible."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml
from jinja2 import Environment, StrictUndefined, UndefinedError

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE = load('ntp_role_fixture_inputs', 'tests/ntp_source/test_ntp_source.py')
WRAPPER = load('ntp_wrapper_fixture_inputs', 'tests/ntp_source/test_wrapper.py')


class BeforeAnsible(BaseException):
    """Stop before any executable is launched; never a simulated role PASS."""


class NTPHarnessInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ntp-inputs-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def generated(self, repeat=False):
        calls = 0

        def stop(*args, **kwargs):
            nonlocal calls
            calls += 1
            if repeat and calls == 1:
                return subprocess.CompletedProcess(args[0], 0, 'changed=0 ', '')
            raise BeforeAnsible()

        # Windows has no uid/gid; these are fixture-owner inputs only. No
        # chown or Ansible action occurs before the subprocess boundary.
        with patch.object(os, 'getuid', return_value=1000, create=True), \
             patch.object(os, 'getgid', return_value=1000, create=True), \
             patch.object(ROLE.subprocess, 'run', side_effect=stop):
            with self.assertRaises(BeforeAnsible):
                ROLE.run_case(('case', {'repeat': repeat}), self.root, '/never-executed/ansible-playbook')
        return yaml.safe_load((self.root / 'case/case.yml').read_text())[0]['vars']

    def captured_at(self, variables):
        tasks = yaml.safe_load((ROOT / 'roles/ntp_source/tasks/_legacy.yml').read_text())

        def expressions(items):
            for task in items:
                before = task.get('ansible.builtin.set_fact', {}).get('cr_ntp_before_state', '')
                if 'captured_at' in before:
                    yield before
                for key in ('block', 'rescue', 'always'):
                    yield from expressions(task.get(key, []))

        contents = list(expressions(tasks))
        self.assertEqual(len(contents), 1)
        # Render the exact timestamp expression from the production task;
        # this is input compatibility, not Ansible task execution.
        expressions = re.findall(r"'captured_at':\s*([^,]+),", contents[0])
        self.assertEqual(len(expressions), 1)
        env = Environment(undefined=StrictUndefined)
        return env.from_string('{{ '+expressions[0]+' }}').render(**variables)

    def test_generated_facts_render_current_baseline_expression(self):
        variables = self.generated()
        self.assertNotIn('ansible_date_time', variables)
        self.assertIn('2026-09-18T00:00:00Z', self.captured_at(variables))

    def test_repeat_changes_current_fact_namespace(self):
        self.assertIn('2026-09-18T00:01:00Z', self.captured_at(self.generated(repeat=True)))

    def test_old_injected_fact_does_not_satisfy_current_expression(self):
        variables = self.generated()
        variables['ansible_date_time'] = variables.pop('ansible_facts')['date_time']
        with self.assertRaises(UndefinedError):
            self.captured_at(variables)

    def test_staged_wrapper_includes_real_sibling_helper(self):
        repo = self.root / 'repo'
        repo.mkdir()
        script = WRAPPER.stage_wrapper(repo)
        self.assertEqual(script.read_bytes(), WRAPPER.SCRIPT.read_bytes())
        helper = script.parent / 'lib/ansible-engine.sh'
        self.assertEqual(helper.read_bytes(), (ROOT / 'scripts/lib/ansible-engine.sh').read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
