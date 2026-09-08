#!/usr/bin/env python3
"""Exercise the source SSH guards with real grep results and Ansible conditions.

Only temporary fixture files are read. --export-dir also prepares a localhost
playbook containing copies of the source guard tasks, plus a read-only include
for real server verification. No authorized_keys file is modified by this test.
"""
import argparse
import copy
import inspect
import json
import subprocess
import tempfile
from pathlib import Path

import yaml
from ansible import __version__
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.conditional import Conditional
from ansible.template import Templar

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=ROOT/'playbooks/harden_svc_ansible_key.yml')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--export-dir', type=Path)
args = parser.parse_args()
loader = DataLoader()
options = {'trusted_as_template': True} if 'trusted_as_template' in inspect.signature(loader.load_from_file).parameters else {}
play = loader.load_from_file(str(args.source.resolve()), **options)[0]
plain_play = yaml.safe_load(args.source.read_text())[0]
names = ['Count P1 managed SSH keys', 'Verify restricted P1 managed SSH key']
guards = [next(t for t in play['tasks'] if t['name'] == name) for name in names]
plain_guards = [next(t for t in plain_play['tasks'] if t['name'] == name) for name in names]
plain = 'ssh-ed25519 AAAATESTFIXTURE P1-ANS-01 svc_ansible\n'
restricted = 'from="10.250.10.10",restrict ' + plain
fixtures = {'empty': '', 'one_plain': plain, 'one_restricted': restricted,
            'two_plain': plain*2, 'two_restricted': restricted*2,
            'mixed': plain+restricted, 'missing': None}
valid = [{'one_plain', 'one_restricted'}, {'one_restricted', 'mixed'}]
results = []
export = args.export_dir.resolve() if args.export_dir else None
scratch = tempfile.TemporaryDirectory(prefix='fds-ssh-guards-') if not export else None
fixture_root = export/'fixtures' if export else Path(scratch.name)
fixture_root.mkdir(parents=True, exist_ok=True)
regression_tasks = []
for case, data in fixtures.items():
    path = fixture_root/case
    if data is not None:
        path.write_text(data)
    elif path.exists():
        raise RuntimeError('Missing-file fixture already exists; use a new export directory')
    for index, guard in enumerate(guards):
        task = copy.deepcopy(plain_guards[index])
        task['ansible.builtin.command']['argv'][-1] = str(path)
        cmd = task['ansible.builtin.command']['argv']
        command = subprocess.run(cmd, capture_output=True, text=True, check=False)
        expected = case not in valid[index]
        variables = {guard['register']: {'rc': command.returncode, 'stdout': command.stdout}}
        result = {'case': case, 'guard': names[index], 'rc': command.returncode,
                  'count': command.stdout.strip(), 'expected_failure': expected}
        try:
            templar = Templar(loader=loader, variables=variables)
            expression = guard['failed_when']
            if hasattr(templar, 'evaluate_conditional'):
                observed = all(templar.evaluate_conditional(v) for v in (expression if isinstance(expression, list) else [expression]))
            else:
                conditional = Conditional(loader=loader)
                conditional.when = expression if isinstance(expression, list) else [expression]
                observed = conditional.evaluate_conditional(templar, variables)
            result.update(observed_failure=observed, outcome='PASS' if observed == expected else 'FAIL')
        except Exception as exc:
            result.update(outcome='ERROR', error=str(exc))
        results.append(result)
        if export:
            task['name'] = f'Execute source guard: {case}: {names[index]}'
            regression_tasks.extend([
                {'name': f'Reset observation: {case}: {index}',
                 'ansible.builtin.set_fact': {'guard_rejected': False, 'guard_condition_was_true': False}},
                {'name': f'Observe guard: {case}: {index}', 'block': [task],
                 'rescue': [{'name': 'Record intended rejection', 'ansible.builtin.set_fact': {
                     'guard_rejected': True,
                     'guard_condition_was_true': '{{ ansible_failed_result.failed_when_result | default(false) is sameas true }}'}}]},
                {'name': f'Assert contract: {case}: {index}', 'ansible.builtin.assert': {
                    'that': [f'guard_rejected == {expected}', 'not guard_rejected or guard_condition_was_true'],
                    'fail_msg': f'Guard did not satisfy the independent fixture expectation: {case}: {names[index]}'}}
            ])

summary = {'engine': __version__, 'source': str(args.source.resolve()), 'scope': 'real grep + original Ansible conditional; no remote I/O',
           'total': len(results), 'outcomes': {s: sum(r['outcome'] == s for r in results) for s in ['PASS', 'FAIL', 'ERROR']}, 'results': results}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
if export:
    (export/'ssh-guards.yml').write_text(yaml.safe_dump(plain_guards, sort_keys=False))
    (export/'source-vars.json').write_text(json.dumps(plain_play['vars'], indent=2)+'\n')
    (export/'regression.yml').write_text(yaml.safe_dump([{'name': 'SSH guard localhost regression', 'hosts': 'localhost',
        'connection': 'local', 'gather_facts': False, 'become': False, 'tasks': regression_tasks}], sort_keys=False))
print(json.dumps({k: summary[k] for k in ['engine', 'total', 'outcomes']}))
if scratch:
    scratch.cleanup()
raise SystemExit(0 if all(r['outcome'] == 'PASS' for r in results) else 1)
