"""Exercise production expressions on localhost, never production tasks/hosts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import yaml


def fixture(source):
    plays = yaml.safe_load(source)
    gate = plays[-1]['tasks'][0]['assert']['that']
    waits = [task['until'] for task in plays[1]['tasks'][0]['block']
             if task.get('register') == 'td_done']
    if len(waits) != 1:
        raise ValueError('Expected one production async completion expression')
    tasks = []
    cases = {'ok': {'failed': False}, 'failed': {'failed': True},
             'empty': {}, 'string_false': {'failed': 'false'}, 'zero': {'failed': 0}}
    for name, verdict in cases.items():
        tasks.append({'ansible.builtin.add_host': {'name': name, 'verdict': verdict},
                      'changed_when': False})
    tasks.append({'ansible.builtin.add_host': {'name': 'missing'}, 'changed_when': False})
    tasks.append({'name': 'Evaluate production final gate',
                  'ansible.builtin.assert': {'that': gate},
                  'loop': list(cases) + ['missing'], 'ignore_errors': True,
                  'register': 'observed'})
    tasks.append({'name': 'Only explicit false may pass', 'ansible.builtin.assert': {
        'that': ['(observed.results | rejectattr("failed") | map(attribute="item") | list) == ["ok"]']}})
    for value in [0, 1, False, True]:
        tasks.append({'name': 'Async finished input ' + repr(value),
                      'ansible.builtin.assert': {'that': ['(' + waits[0] + ') == expected']},
                      'vars': {'td_done': {'finished': value}, 'expected': bool(value)}})
    return [{'hosts': 'localhost', 'gather_facts': False, 'tasks': tasks}]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    source = root / 'playbooks/p1-sec-01-b2-collect-58.yml'
    play = out / 'fixture.yml'
    play.write_text(yaml.safe_dump(fixture(source.read_text()), sort_keys=False))
    command = [str(Path(sys.executable).parent / 'ansible-playbook'),
               '-i', 'localhost,', '-c', 'local', '-e',
               'ansible_python_interpreter=' + sys.executable, str(play)]
    try:
        with (out / 'stdout.log').open('wb') as stdout, (out / 'stderr.log').open('wb') as stderr:
            result = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr, timeout=120)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        rc = 124
    (out / 'RESULT.json').write_text(json.dumps({'rc': rc, 'passed': rc == 0,
        'scope': 'production expressions only; localhost synthetic inventory',
        'python': sys.executable}, indent=2) + '\n')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
