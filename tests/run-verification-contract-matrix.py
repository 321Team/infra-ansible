#!/usr/bin/env python3
"""Real public CLI callback tests on six local aliases; no operational inventory."""
import argparse
import copy
import json
from pathlib import Path
import sys

import yaml
from regression_expectations import CONTRACT_CLI_CASES, EVENT_MUTATIONS, complete_contract

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'scripts'))
from verification_contract import (ENGINES, capture, clean_environment, completion_play, context,
                                   decode, digest, runtime_command, source_sha, stage, validate, write_json)

HOSTS = tuple(f'fixture-{n}' for n in range(1, 7))


def ssh_proof_task():
    """Exercise the exact real-node producer, without executing its SSH tasks."""
    plays = yaml.safe_load((ROOT / 'tests/ssh-server-readonly.yml').read_text(encoding='utf-8'))
    matches = [task for play in plays for task in play.get('tasks', [])
               if 'fds_ssh_verified' in task.get('tags', [])]
    if len(matches) != 1 or 'ansible.builtin.debug' not in matches[0]:
        raise ValueError('Expected exactly one debug SSH proof producer')
    return copy.deepcopy(matches[0])


def make_play(case, python, metadata):
    tasks = [{'name': 'Positive fixture', 'ansible.builtin.debug': {'msg': 'fixture success'}},
             {'name': 'Loop result fixture', 'ansible.builtin.command': {'argv': [str(python), '-c', 'pass']},
              'loop': [1, 2], 'changed_when': False}]
    play = {'name': 'Local callback fixture', 'hosts': 'fixtures', 'gather_facts': False,
            'connection': 'local', 'become': False, 'tasks': tasks}
    command = {'name': 'Negative fixture', 'ansible.builtin.command': {'argv': [str(python), '-c', 'raise SystemExit(7)']},
               'changed_when': False, 'register': 'probe'}
    if case == 'wording':
        tasks[0]['name'] = '  Different wording / whitespace  '
        tasks[0]['ansible.builtin.debug']['msg'] = 'PLAY RECAP\n  SSH_READONLY_PASS  \nnot a verdict'
    elif case == 'serial':
        play['serial'] = 1
    elif case in ('ssh_proof', 'ssh_proof_wrong_count'):
        play['vars'] = {'ansible_facts': {'python_version': 'fixture'},
                        'ssh_effective_user': {'stdout': 'root\n'},
                        'p1_managed_key_count': {'stdout': '2\n' if case == 'ssh_proof_wrong_count' else '1\n'},
                        'p1_restricted_key_count': {'stdout': '1\n'}}
        tasks.append(ssh_proof_task())
    elif case == 'expected_negative':
        tasks.append({**command, 'ignore_errors': True, 'failed_when': 'probe.rc == 7', 'tags': ['fds_expected_failure']})
    elif case == 'expected_expression':
        tasks.append({**command, 'ignore_errors': True, 'failed_when': 'undefined_contract_probe.value == 1',
                      'tags': ['fds_expected_failure']})
    elif case == 'failure':
        tasks.append({'name': 'Unexpected failure', 'ansible.builtin.fail': {'msg': 'fixture failure'}})
    elif case == 'ignored':
        tasks.append({'name': 'Ignored failure', 'ansible.builtin.fail': {'msg': 'fixture failure'}, 'ignore_errors': True})
    elif case == 'rescued':
        tasks.append({'block': [{'ansible.builtin.fail': {'msg': 'fixture failure'}}],
                      'rescue': [{'ansible.builtin.debug': {'msg': 'rescued fixture'}}]})
    elif case == 'expression':
        tasks.append({**command, 'failed_when': 'undefined_contract_probe.value == 1'})
    elif case == 'hidden_rc':
        tasks.append({**command, 'failed_when': False})
    elif case == 'changed':
        tasks[0]['changed_when'] = True
    elif case == 'transport_error':
        play['vars'] = {'ansible_shell_executable': '/nonexistent-fds-fixture-shell'}
    elif case == 'timeout':
        play['tasks'] = [{'ansible.builtin.command': {'argv': [str(python), '-c', 'import time; time.sleep(30)']}, 'changed_when': False}]
    return [play, completion_play(metadata, 'fixtures')]


def corruptions(events):
    """Derived negative fixtures retain a reference to the original CLI stream."""
    for case in EVENT_MUTATIONS:
        rows = copy.deepcopy(events)
        if case == 'missing_complete':
            rows.pop()
        elif case == 'missing_node':
            rows[-1]['nodes'].pop()
        elif case == 'duplicate_node':
            rows[-1]['nodes'][0] = rows[-1]['nodes'][1]
        elif case == 'wrong_node':
            rows[-1]['nodes'][0]['host'] = 'other-host'
        elif case == 'missing_marker':
            next(r for r in rows if 'completion' in r).pop('completion')
        elif case == 'duplicate_result':
            rows.insert(2, copy.deepcopy(rows[1]))
            for i, row in enumerate(rows):
                row['seq'] = i
        elif case == 'sequence_gap':
            rows[1]['seq'] = 999
        elif case == 'wrong_code':
            rows[0]['code_sha'] = '0' * 40
        elif case == 'wrong_engine':
            rows[0]['engine'] = '0.0.0'
        elif case == 'wrong_stage':
            rows[0]['stage_id'] = 'other-stage'
        yield case, ''.join(json.dumps(row) + '\n' for row in rows)
    raw = ''.join(json.dumps(row) + '\n' for row in events)
    yield 'truncated', raw[:-5]
    yield 'duplicate_key', raw.replace('"seq": 0', '"seq": 0, "seq": 0', 1)
    yield 'whitespace', ''.join(' ' + json.dumps(row, separators=(',  ', ' : ')) + ' \n' for row in events)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python216', type=Path, required=True)
    parser.add_argument('--python221', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Real Ansible callback tests require Linux')
    code = source_sha(ROOT)
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('Use a new output directory outside the source checkout')
    output.mkdir(parents=True, exist_ok=False)
    env = clean_environment(ROOT, output)
    config = output / 'ansible.cfg'
    config.write_text('[defaults]\nhost_key_checking=True\nretry_files_enabled=False\n', encoding='utf-8')
    env['ANSIBLE_CONFIG'] = str(config)
    runs, comparisons = [], []
    cases = CONTRACT_CLI_CASES
    for engine, python in zip(ENGINES, (args.python216.absolute(), args.python221.absolute())):
        inventory = output / (engine + '-inventory.json')
        write_json(inventory, {'all': {'children': {'fixtures': {'hosts': {n: {'ansible_connection': 'local',
            'ansible_python_interpreter': str(python), 'ansible_become': False} for n in HOSTS}}}}})
        # Check the provided venv without installing or modifying packages.
        rc, timeout, stdout, stderr = capture(runtime_command(python, ROOT, engine), ROOT, env, 60)
        (output / (engine + '-dependencies.stdout.log')).write_bytes(stdout)
        (output / (engine + '-dependencies.stderr.log')).write_bytes(stderr)
        if rc or timeout:
            runs.append({'engine': engine, 'case': 'dependencies', 'passed': False})
            continue
        for case in cases:
            metadata = context(code, engine, engine + '_' + case)
            playbook = output / (engine + '-' + case + '.json')
            write_json(playbook, make_play(case, python, metadata))
            command = [python.parent / 'ansible-playbook', '-i', inventory, '-c', 'local', playbook]
            if case == 'limited_nodes':
                command += ['--limit', HOSTS[0]]
            result = stage(command, ROOT, output / (engine + '-' + case), env, metadata, HOSTS,
                           timeout=2 if case == 'timeout' else 300,
                           require_ssh=case in ('ssh_proof', 'ssh_proof_wrong_count'),
                           expected_negative=case in ('expected_negative', 'expected_expression'))
            expected = ('PASS' if case in ('baseline', 'wording', 'serial', 'ssh_proof') else
                        'EXPECTED_FAILURE_CONFIRMED' if case == 'expected_negative' else 'REVIEW_REQUIRED')
            stream = output / (engine + '-' + case) / 'events.jsonl'
            try:
                events = [decode(line) for line in stream.read_text(encoding='utf-8').splitlines()]
                identity = events[0] == {'type': 'start', 'seq': 0, **metadata}
            except (OSError, ValueError, IndexError):
                events, identity = [], False
            passed = identity and result['status'] == expected
            if case in ('baseline', 'wording', 'serial', 'ssh_proof', 'ssh_proof_wrong_count',
                        'expected_negative', 'expected_expression', 'ignored', 'rescued', 'hidden_rc', 'changed', 'limited_nodes'):
                passed &= result['cli_rc'] == 0
            elif case == 'timeout':
                passed &= result['timed_out'] is True
            else:
                passed &= result['cli_rc'] != 0
            runs.append({'engine': engine, 'case': case, 'passed': bool(passed), 'status': result['status'],
                         'cli_rc': result['cli_rc'], 'origin': 'real CLI on local fixture aliases'})
            print(json.dumps(runs[-1]), flush=True)
            if case == 'baseline' and not passed:
                # A broken launcher is not evidence for the negative cases.
                # Keep its logs and try the other pinned engine immediately.
                break
            if case == 'baseline' and passed:
                comparisons.append(result['nodes'])
                for mutation, content in corruptions(events):
                    path = output / (engine + '-derived-' + mutation + '.jsonl')
                    path.write_text(content, encoding='utf-8')
                    derived = validate(path, metadata, HOSTS, cli_rc=0)
                    good = derived['status'] == ('PASS' if mutation == 'whitespace' else 'REVIEW_REQUIRED')
                    runs.append({'engine': engine, 'case': 'derived-' + mutation, 'passed': good,
                                 'status': derived['status'], 'origin': 'mutated callback fixture', 'source_sha256': digest(stream)})
    same = len(comparisons) == len(ENGINES) and all(row == comparisons[0] for row in comparisons)
    source_matches = source_sha(ROOT) == code
    passed = source_matches and same and complete_contract(runs)
    write_json(output / 'MATRIX.json', {'schema_version': 1, 'code_sha': code, 'scope': 'six LOCAL aliases; no operational SSH',
               'status': 'PASS' if passed else 'FAIL', 'same_baseline_results': same, 'runs': runs})
    files = sorted(p for p in output.rglob('*') if p.is_file())
    (output / 'SHA256SUMS').write_text(''.join(digest(p) + '  ' + p.relative_to(output).as_posix() + '\n' for p in files), encoding='utf-8')
    print('MATRIX: ' + ('PASS' if passed else 'FAIL'), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
