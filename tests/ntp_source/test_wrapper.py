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


def stage_wrapper(fixture_repo):
    script = fixture_repo / 'scripts' / SCRIPT.name
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    script.chmod(0o700)
    library = script.parent / 'lib'
    library.mkdir()
    # The real wrapper sources this sibling before dispatching any action.
    (library / 'ansible-engine.sh').write_bytes(
        (ROOT / 'scripts/lib/ansible-engine.sh').read_bytes())
    return script


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
    for name, action, fail_at, approval, mode, expected_calls, expected_ok in (
        ('source_sequence', 'source', 0, True, None, 3, True),
        ('clients_sequence', 'clients', 0, True, None, 3, True),
        ('check_stops_apply', 'clients', 1, True, None, 1, False),
        ('apply_stops_idempotency', 'clients', 2, True, None, 2, False),
        ('idempotency_failure_propagated', 'clients', 3, True, None, 3, False),
        ('approval_still_required', 'source', 0, False, None, 0, False),
        ('migration_source_sequence', 'source', 0, True, '1', 3, True),
        ('source_check_failure_stops_apply', 'source', 1, True, '1', 1, False),
        ('source_apply_failure_stops_idempotency', 'source', 2, True, '1', 2, False),
        ('source_idempotency_failure_propagated', 'source', 3, True, '1', 3, False),
        ('migration_clients_sequence', 'clients', 0, True, '1', 3, True),
        ('migration_precheck', 'precheck', 0, False, '1', 1, True),
        ('migration_verify', 'verify', 0, False, '1', 1, True),
        ('migration_rollback', 'rollback', 0, True, '1', 1, True),
        ('migration_not_approval', 'source', 0, False, '1', 0, False),
        ('invalid_migration_mode', 'source', 0, True, 'yes', 0, False),
        ('explicit_legacy_mode', 'clients', 0, True, '0', 3, True),
    ):
        case = output / name
        fixture_repo = case / 'repo'
        fixture_tools = fixture_repo / 'tools'
        fixture_tools.mkdir(parents=True)
        fixture_script = stage_wrapper(fixture_repo)
        # Isolate only the OS home locator. The copied helper's secure path,
        # flock, FD handoff, and CLI re-entry behavior remain unchanged.
        helper = (ROOT / 'tools/ntp-workflow-lock.py').read_text()
        locator = 'return Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".local/state/fds-ntp/CR-P1-NTP-01-01.lock"'
        assert helper.count(locator) == 1
        helper = helper.replace(locator, 'return Path(' + repr(str(case / 'controller.lock')) + ')')
        (fixture_tools / 'ntp-workflow-lock.py').write_text(helper)
        binaries = case / 'bin'
        binaries.mkdir(parents=True)
        for executable in ('git', 'id', 'hostnamectl', 'ansible-playbook'):
            path = binaries / executable
            path.write_text(FAKE.format(python=sys.executable))
            path.chmod(0o700)
        key = case / 'fixture-key'
        key.write_text('fixture only; not an SSH key\n')
        calls_path = case / 'calls.json'
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('ANSIBLE_', 'CR_', 'FIXTURE_', 'FDS_ANSIBLE_ENGINE_'))}
        env.update(PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                   FIXTURE_REPO=str(fixture_repo), FIXTURE_CALLS=str(calls_path),
                   FIXTURE_FAIL_AT=str(fail_at), ANSIBLE_PRIVATE_KEY_FILE=str(key),
                   CR_EVIDENCE_DIR=str(case / 'evidence'))
        if approval:
            env['CR_CHANGE_APPROVED'] = 'CR-P1-NTP-01-01'
        if mode is not None:
            env['CR_NTP_MIGRATE_MAIN'] = mode
        command = [str(fixture_script), action]
        if action == 'rollback':
            command.append('k8s-worker02')
        run = subprocess.run(command, env=env, cwd=ROOT,
                             capture_output=True, text=True, timeout=30)
        calls = json.loads(calls_path.read_text()) if calls_path.exists() else []
        errors = []
        if (run.returncode == 0) != expected_ok or len(calls) != expected_calls:
            errors.append('incorrect exit status or playbook sequence length')
        if calls and action in ('source', 'clients') and not {'--check', '--diff'} <= set(calls[0]):
            errors.append('first run is not dry-run/diff')
        if len(calls) > 1 and '--check' in calls[1]:
            errors.append('apply was not reached')
        if len(calls) > 2 and not {'--check', '--diff', '{"cr_ntp_require_no_change":true}'} <= set(calls[2]):
            errors.append('idempotency pass lacks explicit zero-change check')
        for call in calls:
            has_migration = '{"cr_ntp_migrate_main":true}' in call
            if has_migration != (mode == '1'):
                errors.append('migration mode did not reach every playbook invocation')
        if action == 'rollback' and calls and 'cr_ntp_rollback_host=k8s-worker02' not in calls[0]:
            errors.append('rollback target not preserved')
        (case / 'output.log').write_text(run.stdout + run.stderr)
        results.append(dict(name=name, passed=not errors, errors=errors, rc=run.returncode))
    report = dict(scope='LOCAL/MOCK wrapper only; no managed host execution', results=results,
                  passed=sum(x['passed'] for x in results), total=len(results))
    (output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
