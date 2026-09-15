#!/usr/bin/env python3
"""Run synthetic SSH guards through the public ansible-playbook CLI only."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from ssh_guard_fixtures import generate
from regression_expectations import ENGINES

ROOT = Path(__file__).resolve().parents[1]


def classify(case, observation):
    result = {k: case[k] for k in ('case', 'guard', 'expected_failure')}
    condition = observation.get('failed_when_result')
    failed = observation.get('failed')
    stdout = observation.get('stdout')
    result.update(rc=observation.get('rc'), count=stdout.strip() if isinstance(stdout, str) else None)
    # Newer engines attach exception diagnostics to ordinary failed_when=True
    # rejections too. The public boolean condition result, failed flag, and
    # independent grep rc/count contract distinguish those from expression errors.
    if (type(condition) is not bool or type(failed) is not bool
            or type(result['rc']) is not int or not isinstance(stdout, str)
            or observation.get('skipped') or observation.get('unreachable')):
        return dict(result, outcome='ERROR', error='Missing/invalid CLI observation or expression/module error')
    result['observed_failure'] = condition
    result['outcome'] = 'PASS' if (
        condition == failed == case['expected_failure']
        and result['rc'] == case['expected_rc']
        and result['count'] == case['expected_count']) else 'FAIL'
    return result


def run(args, directory):
    case_list = generate(args.source, directory)
    results = []
    summary = {'engine': None, 'source': str(args.source.resolve()),
               'scope': 'public ansible-playbook CLI; synthetic localhost fixtures only',
               'total': len(case_list), 'results': results}
    for case in case_list:
        path = directory / f"result-{case['case']}-{case['index']}.json"
        if path.exists():
            path.unlink()  # Never accept observations from an earlier run.
    config = directory / 'ansible.cfg'
    config.write_text('[defaults]\nretry_files_enabled = False\n', encoding='utf-8')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('ANSIBLE_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(ANSIBLE_CONFIG=str(config), ANSIBLE_NOCOLOR='1',
               ANSIBLE_STDOUT_CALLBACK='default', ANSIBLE_LOCAL_TEMP=str(directory / 'tmp'))
    executable = args.ansible_playbook or str(Path(sys.executable).parent / 'ansible-playbook')
    executable = shutil.which(executable) or executable
    try:
        version = subprocess.run([executable, '--version'], env=env, cwd=directory,
                                 capture_output=True, text=True, timeout=30, check=True)
        match = re.search(r'ansible-playbook \[core ([^\]]+)\]', version.stdout)
        if not match:
            raise ValueError('Cannot identify ansible-playbook core version')
        summary['engine'] = match.group(1)
        if args.expect_engine and summary['engine'] != args.expect_engine:
            raise ValueError('Engine version does not match --expect-engine')
        command = [executable, '-i', 'localhost,', '-c', 'local',
                   '-e', json.dumps({'ansible_python_interpreter': sys.executable}),
                   str(directory / 'regression.yml')]
        completed = subprocess.run(command, env=env, cwd=directory, capture_output=True,
                                   text=True, timeout=args.timeout)
        (directory / 'regression.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        summary['cli_rc'] = completed.returncode
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        summary.update(cli_rc=None, error=str(exc))
        def decoded(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
        log = decoded(getattr(exc, 'stdout', '')) + decoded(getattr(exc, 'stderr', ''))
        (directory / 'regression.log').write_text(log + '\n' + str(exc) + '\n', encoding='utf-8')
    for case in case_list:
        try:
            path = directory / f"result-{case['case']}-{case['index']}.json"
            observation = json.loads(path.read_text(encoding='utf-8'))
            results.append(classify(case, observation))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            results.append(dict(case, outcome='ERROR', error=str(exc)))
    summary['outcomes'] = {s: sum(r['outcome'] == s for r in results) for s in ('PASS', 'FAIL', 'ERROR')}
    summary['status'] = 'PASS' if summary.get('cli_rc') == 0 and summary['outcomes']['PASS'] == len(case_list) else 'FAIL'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('engine', 'total', 'outcomes', 'status')}))
    return 0 if summary['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=ROOT / 'playbooks/harden_svc_ansible_key.yml')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--export-dir', type=Path)
    parser.add_argument('--ansible-playbook')
    parser.add_argument('--expect-engine', choices=ENGINES)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    if args.export_dir:
        return run(args, args.export_dir.resolve())
    with tempfile.TemporaryDirectory(prefix='fds-ssh-guards-') as scratch:
        return run(args, Path(scratch))


if __name__ == '__main__':
    raise SystemExit(main())
