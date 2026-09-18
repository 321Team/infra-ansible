#!/usr/bin/env python3
"""Exercise the actual wrapper with local fake host identity/playbook commands."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/cr-p1-ntp-01-01-run.sh'
FAKE = '''#!{python}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
if name == 'hostnamectl': print('ansible01')
elif name == 'id': print('server01_ansible')
elif name == 'git':
    if 'status' in sys.argv: pass
    elif sys.argv[-1] == 'HEAD': print('a' * 40)
    else: print(os.environ['FIXTURE_REPO'])
elif name == 'ansible-playbook':
    p = pathlib.Path(os.environ['FIXTURE_CALLS'])
    calls = json.loads(p.read_text()) if p.exists() else []
    calls.append(sys.argv[1:])
    p.write_text(json.dumps(calls))
    sys.exit(2 if len(calls) == int(os.environ['FIXTURE_FAIL_AT']) else 0)
else: raise RuntimeError('unknown fake command')
'''


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='ntp-wrapper-tests-'))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    syntax = subprocess.run(['bash', '-n', str(SCRIPT)], capture_output=True, text=True)
    results = [dict(name='bash_syntax', passed=syntax.returncode == 0),
               dict(name='executable_bit', passed=bool(SCRIPT.stat().st_mode & 0o111))]
    for name, action, fail_at, approval, expected_calls, expected_ok in (
        ('source_sequence', 'source', 0, True, 3, True),
        ('clients_sequence', 'clients', 0, True, 3, True),
        ('check_stops_apply', 'clients', 1, True, 1, False),
        ('apply_stops_idempotency', 'clients', 2, True, 2, False),
        ('idempotency_failure_propagated', 'clients', 3, True, 3, False),
        ('approval_still_required', 'source', 0, False, 0, False),
    ):
        case = output / name
        binaries = case / 'bin'
        binaries.mkdir(parents=True)
        for executable in ('git', 'id', 'hostnamectl', 'ansible-playbook'):
            path = binaries / executable
            path.write_text(FAKE.format(python=sys.executable))
            path.chmod(0o700)
        key = case / 'fixture-key'
        key.write_text('fixture only; not an SSH key\n')
        calls_path = case / 'calls.json'
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ANSIBLE_', 'CR_', 'FIXTURE_'))}
        env.update(PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                   FIXTURE_REPO=str(ROOT), FIXTURE_CALLS=str(calls_path),
                   FIXTURE_FAIL_AT=str(fail_at), ANSIBLE_PRIVATE_KEY_FILE=str(key),
                   CR_EVIDENCE_DIR=str(case / 'evidence'))
        if approval:
            env['CR_CHANGE_APPROVED'] = 'CR-P1-NTP-01-01'
        run = subprocess.run([str(SCRIPT), action], env=env, cwd=ROOT,
                             capture_output=True, text=True, timeout=30)
        calls = json.loads(calls_path.read_text()) if calls_path.exists() else []
        errors = []
        if (run.returncode == 0) != expected_ok or len(calls) != expected_calls:
            errors.append('incorrect exit status or playbook sequence length')
        if calls and not {'--check', '--diff'} <= set(calls[0]):
            errors.append('first run is not dry-run/diff')
        if len(calls) > 1 and '--check' in calls[1]:
            errors.append('apply was not reached')
        if len(calls) > 2 and not {'--check', '--diff', '{"cr_ntp_require_no_change":true}'} <= set(calls[2]):
            errors.append('idempotency pass lacks explicit zero-change check')
        (case / 'output.log').write_text(run.stdout + run.stderr)
        results.append(dict(name=name, passed=not errors, errors=errors, rc=run.returncode))
    report = dict(scope='LOCAL/MOCK wrapper only; no managed host execution', results=results,
                  passed=sum(x['passed'] for x in results), total=len(results))
    (output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
