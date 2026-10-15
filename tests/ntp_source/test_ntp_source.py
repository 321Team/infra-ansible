#!/usr/bin/env python3
"""Run PR24 role regression fixtures with actual Ansible task control flow.

Requires ansible-core, PyYAML and Jinja2. Runs only on localhost in a fresh
temporary directory. command/systemd tasks are replaced with a no-I/O action;
file/copy/slurp/stat/template/assert/include/rescue use real Ansible modules.
Template validation is a stand-in, not a test of installed chronyd grammar.
No service, NTP, SSH, production path, or clock operation is executed.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
VARS = yaml.safe_load((ROOT / 'inventory/group_vars/all.yml').read_text())


def instrument(tasks, directory):
    """Keep role conditions/blocks intact; replace only external host I/O."""
    for task in tasks:
        for block in ('block', 'rescue', 'always'):
            if block in task:
                instrument(task[block], directory)
        for action in ('command', 'systemd'):
            key = 'ansible.builtin.' + action
            if key in task:
                task['ntp_fixture'] = dict(kind=action, options=task.pop(key))
        if 'ansible.builtin.slurp' in task:
            args = task['ansible.builtin.slurp']
            if args['src'] == '/etc/chrony.conf':
                args['src'] = str(directory / 'chrony.conf')
        if 'ansible.builtin.template' in task:
            args = task['ansible.builtin.template']
            assert args['validate'] == 'chronyd -p -f %s'
            args['validate'] = str(directory / 'validate-fixture') + ' %s'
        # Support unprivileged local runs while exercising real metadata I/O.
        for module in ('file', 'copy', 'template'):
            args = task.get('ansible.builtin.' + module, {})
            for field, value in (('owner', os.getuid()), ('group', os.getgid())):
                if args.get(field) == 'root':
                    args[field] = str(value)
        if task.get('name') == 'Require a protected regular baseline file':
            conditions = task['ansible.builtin.assert']['that']
            conditions[conditions.index('cr_ntp_original_stat.stat.uid == 0')] = (
                f'cr_ntp_original_stat.stat.uid == {os.getuid()}')
        if task.get('name') == 'Refuse an unsafe rollback state directory before mutation or read':
            conditions = task['ansible.builtin.assert']['that']
            for index, condition in enumerate(conditions):
                conditions[index] = condition.replace(
                    'cr_ntp_state_dir_stat.stat.uid | default(-1) == 0',
                    f'cr_ntp_state_dir_stat.stat.uid | default(-1) == {os.getuid()}')


def snapshot(path):
    if not path.exists():
        return None
    stat = path.stat()
    return (path.read_bytes(), stat.st_mode & 0o7777, stat.st_uid, stat.st_gid)


def run_case(case, output, executable):
    name, spec = case
    directory = output / name
    directory.mkdir()
    role = directory / 'roles/ntp_source'
    shutil.copytree(ROOT / 'roles/ntp_source', role)
    for path in (role / 'tasks').glob('*.yml'):
        tasks = yaml.safe_load(path.read_text())
        instrument(tasks, directory)
        path.write_text(yaml.safe_dump(tasks, sort_keys=False))
    plugins = directory / 'action_plugins'
    plugins.mkdir()
    shutil.copyfile(HERE / 'fixture_action.py', plugins / 'ntp_fixture.py')
    validate = directory / 'validate-fixture'
    validate.write_text('#!/bin/sh\nexit ' + ('1' if spec.get('invalid_template') else '0') + '\n')
    validate.chmod(0o700)
    confdir = directory / 'chrony.d'
    confdir.mkdir()
    # Real chronyd include DIR/*.conf requires a match even before the new
    # managed file exists. Keep the positive include-layout fixture valid.
    (confdir / '00-fixture.conf').write_text('# fixture baseline\n')
    dropin = confdir / '50-cr-p1-ntp-01-01.conf'
    state_dir = directory / 'state'
    main = spec.get('layout', 'confdir {confdir}\n').format(confdir=confdir)
    (directory / 'chrony.conf').write_text(main)
    variables = dict(VARS, cr_ntp_dropin_path=str(dropin), cr_ntp_state_dir=str(state_dir),
                     cr_ntp_phase=spec.get('phase', 'apply'),
                     cr_ntp_change_approved=VARS['cr_ntp_change_id'],
                     cr_ntp_require_no_change=spec.get('no_change', False),
                     fixture_root=str(directory), fixture_scenario=spec,
                     ansible_python_interpreter=shutil.which('python3'),
                     ansible_facts={'date_time': {'iso8601': '2026-09-18T00:00:00Z'}})
    if spec.get('source'):
        variables['cr_ntp_source_host'] = 'localhost'
    template_name = 'chrony-source-allow.conf.j2' if spec.get('source') else 'chrony-client-source.conf.j2'
    desired = Environment(keep_trailing_newline=True, trim_blocks=True).from_string(
        (role / 'templates' / template_name).read_text()).render(**variables)
    if spec.get('existing'):
        dropin.write_text(desired if spec['existing'] == 'desired' else 'server 192.0.2.123 iburst\n')
        dropin.chmod(0o644 if spec['existing'] == 'desired' else 0o640)
    before = snapshot(dropin)
    baseline = state_dir / 'original-ntp-dropin.json'
    if spec.get('stale_baseline'):
        state_dir.mkdir(mode=0o700)
        baseline.write_text('{"change_id":"other-change"}\n')
        baseline.chmod(0o600)
    saved_baseline = snapshot(baseline)
    play = [dict(hosts='localhost', connection='local', gather_facts=False,
                 become=False, vars=variables, roles=['ntp_source'])]
    play_path = directory / 'case.yml'
    play_path.write_text(yaml.safe_dump(play, sort_keys=False))
    config = directory / 'ansible.cfg'
    config.write_text('[defaults]\nretry_files_enabled=False\nhost_key_checking=True\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ANSIBLE_', 'PYTHON'))}
    env.update(ANSIBLE_CONFIG=str(config), ANSIBLE_NOCOLOR='1')
    command = [executable, '-i', 'localhost,', str(play_path)]
    if spec.get('check'):
        command.extend(['--check', '--diff'])
    completed = subprocess.run(command, env=env, cwd=directory, capture_output=True,
                               text=True, timeout=90)
    (directory / 'stdout.log').write_text(completed.stdout)
    (directory / 'stderr.log').write_text(completed.stderr)
    first_rc = completed.returncode
    first_baseline = snapshot(baseline)
    if first_rc == 0 and spec.get('repeat'):
        play[0]['vars']['ansible_facts']['date_time']['iso8601'] = '2026-09-18T00:01:00Z'
        play_path.write_text(yaml.safe_dump(play, sort_keys=False))
        second = subprocess.run(command, env=env, cwd=directory, capture_output=True,
                                text=True, timeout=90)
        (directory / 'second.stdout.log').write_text(second.stdout)
        (directory / 'second.stderr.log').write_text(second.stderr)
    else:
        second = None
    if first_rc == 0 and spec.get('manual'):
        rollback = [dict(hosts='localhost', connection='local', gather_facts=False,
                         become=False, vars=variables, tasks=[
            {'name': 'Read baseline', 'ansible.builtin.include_tasks': str(role / 'tasks/_read_original.yml')},
            {'name': 'Restore baseline', 'ansible.builtin.include_tasks': str(role / 'tasks/_restore_dropin.yml'),
             'vars': {'cr_ntp_restore_state': '{{ cr_ntp_original_state }}'}}])]
        rollback_path = directory / 'rollback.yml'
        rollback_path.write_text(yaml.safe_dump(rollback, sort_keys=False))
        completed = subprocess.run([executable, '-i', 'localhost,', str(rollback_path)],
                                   env=env, cwd=directory, capture_output=True, text=True, timeout=90)
        (directory / 'rollback.stdout.log').write_text(completed.stdout)
        (directory / 'rollback.stderr.log').write_text(completed.stderr)
    events = json.loads((directory / 'events.json').read_text()) if (directory / 'events.json').exists() else {'restarts': 0, 'events': []}
    errors = []
    if second is not None:
        if second.returncode != 0 or 'changed=0 ' not in second.stdout:
            errors.append('second real apply did not succeed with changed=0')
        if snapshot(baseline) != first_baseline:
            errors.append('second apply rewrote the immutable baseline')
    if spec.get('manual') and first_rc != 0:
        errors.append('manual rollback prerequisite apply failed')
    if (completed.returncode == 0) != spec.get('pass', True):
        errors.append(f'unexpected rc={completed.returncode}')
    if completed.returncode not in (0, 2):
        errors.append(f'engine/infrastructure failure rc={completed.returncode}')
    if events['restarts'] != spec.get('restarts', 0):
        errors.append(f'unexpected restarts={events["restarts"]}')
    if spec.get('preserve', True) and snapshot(dropin) != before:
        errors.append('drop-in bytes/metadata changed unexpectedly')
    if not spec.get('preserve', True) and (not dropin.exists() or dropin.read_text() != desired):
        errors.append('desired bytes not installed')
    if spec.get('check') or spec.get('phase') in ('precheck', 'verify'):
        if baseline.exists():
            errors.append('read-only phase created a baseline')
    elif spec.get('baseline_created', True):
        if not baseline.exists():
            errors.append('apply did not preserve a baseline')
        elif saved_baseline is not None:
            if snapshot(baseline) != saved_baseline:
                errors.append('existing baseline changed')
        else:
            original = json.loads(baseline.read_text())
            expected_bytes = before[0] if before else b''
            if (original['dropin_existed'] != bool(before) or
                    base64.b64decode(original['dropin_content_b64']) != expected_bytes):
                errors.append('baseline differs from original file')
    if spec.get('check') and any(x.get('options', {}).get('argv', [None, None])[1:2] == ['waitsync'] for x in events['events']):
        errors.append('check-mode ran waitsync')
    if spec.get('check') and spec.get('drift') and 'after:' not in completed.stdout:
        errors.append('dry-run did not expose predicted diff')
    if spec.get('wait_fail') and events.get('polls') != 30:
        errors.append('bounded wait failure was not exercised')
    if spec.get('restarts') == 1 and events.get('polls') != 3:
        errors.append('delayed convergence success was not exercised')
    if spec.get('restore_fail') and 'FIXTURE_SERVICE_FAILURE' not in completed.stdout:
        errors.append('restore failure not visible')
    failure_tasks = []
    last_task = ''
    for line in completed.stdout.splitlines():
        if line.startswith('TASK ['):
            last_task = line.split(']', 1)[0]
        if line.startswith('fatal:'):
            failure_tasks.append(last_task)
    expected_failure = spec.get('failure_task')
    if expected_failure and not any(expected_failure in x for x in failure_tasks):
        errors.append('expected failure task was not reached: ' + expected_failure)
    return dict(name=name, passed=not errors, errors=errors, rc=completed.returncode,
                restarts=events['restarts'], polls=events.get('polls'), failure_tasks=failure_tasks)


def cases():
    yield 'dry_run_drift', dict(check=True, drift=True, existing='old')
    yield 'apply_new_delayed_sync', dict(restarts=1, preserve=False)
    yield 'apply_existing_delayed_sync', dict(existing='old', drift=True, restarts=1, preserve=False)
    yield 'source_apply', dict(source=True, restarts=1, preserve=False)
    yield 'second_real_apply_idempotent', dict(existing='old', repeat=True, restarts=1, preserve=False)
    yield 'manual_rollback_absent_baseline', dict(manual=True, restarts=2)
    yield 'manual_rollback_existing_baseline', dict(existing='old', manual=True, restarts=2)
    yield 'no_op_apply', dict(existing='desired')
    yield 'idempotency_pass', dict(existing='desired', check=True, no_change=True)
    yield 'idempotency_reject_drift', dict(existing='old', check=True, no_change=True, drift=True, **{'pass': False})
    yield 'wait_failure_remove_new', dict(wait_fail=True, restarts=2, **{'pass': False})
    yield 'wait_failure_restore_existing', dict(existing='old', wait_fail=True, restarts=2, **{'pass': False})
    yield 'restart_failure_restore', dict(existing='old', restart_fail=True, restarts=2, **{'pass': False})
    yield 'rollback_service_failure', dict(wait_fail=True, restore_fail=True, restarts=2, **{'pass': False})
    yield 'postverify_failure_restore', dict(existing='old', system_time='0.5', restarts=2, **{'pass': False})
    yield 'no_op_failure_no_restore', dict(existing='desired', system_time='0.5', **{'pass': False})
    yield 'stale_baseline_no_mutation', dict(existing='old', stale_baseline=True, **{'pass': False})
    yield 'invalid_template_no_mutation', dict(existing='old', invalid_template=True, **{'pass': False})
    for name, layout, valid in (
        ('confdir', 'confdir {confdir}\n', True),
        ('include', 'include {confdir}/*.conf\n', True),
        ('case_and_space', '  CoNfDiR {confdir}/  \n', True),
        ('hash_comment', '# includedir {confdir}/\n', False),
        ('bang_comment', '!confdir {confdir}\n', False),
        ('semicolon_comment', ';include {confdir}/*.conf\n', False),
        ('percent_comment', '%confdir {confdir}\n', False),
        ('unhandled_layout', 'confdir /another/path\n', False),
        ('active_pool', 'confdir {confdir}\nPOOL example.invalid iburst\n', False),
        ('active_peer', 'confdir {confdir}\npeer 192.0.2.1\n', False),
        ('active_sourcedir', 'confdir {confdir}\nsourcedir /run/chrony-dhcp\n', False),
        ('commented_competitors', 'confdir {confdir}\n# pool example.invalid\n!sourcedir /run/chrony-dhcp\n', True),
    ):
        yield 'layout_' + name, dict(layout=layout, phase='precheck', **{'pass': valid})
    for name, changes, valid in (
        ('valid_with_header_separator', {}, True),
        ('boundary', {'system_time': '0.100000'}, True),
        ('over_boundary', {'system_time': '0.100001'}, False),
        ('500ms', {'system_time': '0.500000'}, False),
        ('negative_500ms', {'system_time': '-0.500000'}, False),
        ('missing', {'missing_system': True}, False),
        ('duplicate', {'duplicate_system': True}, False),
        ('nan', {'system_time': 'NaN'}, False),
        ('inf', {'system_time': 'inf'}, False),
        ('overflow', {'system_time': '1e9999'}, False),
        ('malformed', {'system_time': '1.2.3'}, False),
        ('bad_last', {'last_offset': '+'}, False),
        ('last_over_threshold', {'last_offset': '0.5'}, False),
        ('unsynced', {'leap': 'Not synchronised'}, False),
        ('wrong_source', {'address': '192.0.2.123'}, False),
        ('regex_impostor', {'address': '10x1x93x102'}, False),
        ('two_sources', {'extra_source': True}, False),
        ('unresolved_extra_source', {'unresolved_source': True}, False),
    ):
        yield 'verify_' + name, dict(phase='verify', **changes, **{'pass': valid})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ansible-playbook', default=shutil.which('ansible-playbook'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if not args.ansible_playbook:
        parser.error('ansible-playbook is required')
    output = (args.output or Path(tempfile.mkdtemp(prefix='ntp-role-tests-'))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected = [(n, c) for n, c in cases() if not args.case or n in args.case]
    for name, spec in selected:
        if spec.get('pass', True):
            continue
        if name.startswith('layout_'):
            spec['failure_task'] = ('Stop on unhandled competing sources' if 'active_' in name
                                    else 'Stop on unexpected chrony.conf layout')
        elif name.startswith('verify_'):
            spec['failure_task'] = (
                'Assert tracking fields were found' if name in {
                    'verify_missing', 'verify_duplicate', 'verify_nan', 'verify_inf',
                    'verify_malformed', 'verify_bad_last'} else
                'Reject non-finite tracking numbers' if name == 'verify_overflow' else
                'Assert leap status is Normal' if name == 'verify_unsynced' else
                'Assert the approved source is selected' if name in {'verify_wrong_source', 'verify_regex_impostor'} else
                'Assert no other source is configured' if name in {'verify_two_sources', 'verify_unresolved_extra_source'} else
                'Assert current system correction and last offset meet the threshold')
        else:
            spec['failure_task'] = {
                'idempotency_reject_drift': 'Require zero predicted changes',
                'wait_failure_remove_new': 'Wait at most 300 seconds',
                'wait_failure_restore_existing': 'Wait at most 300 seconds',
                'restart_failure_restore': 'Restart chronyd',
                'rollback_service_failure': 'Restart chronyd after restoring',
                'postverify_failure_restore': 'Assert current system correction',
                'no_op_failure_no_restore': 'Assert current system correction',
                'stale_baseline_no_mutation': 'Validate restore state identity',
                'invalid_template_no_mutation': 'Render the managed NTP drop-in',
            }[name]
    if not selected:
        parser.error('no matching cases')
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        results = list(executor.map(lambda case: run_case(case, output, args.ansible_playbook), selected))
    report = dict(scope='LOCAL/MOCK; host commands and chronyd parser replaced; no runtime acceptance',
                  ansible_playbook=args.ansible_playbook, results=results,
                  passed=sum(x['passed'] for x in results), total=len(results))
    (output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    for result in results:
        print(('PASS' if result['passed'] else 'FAIL'), result['name'], result['errors'])
    print(f"{report['passed']}/{report['total']} passed; {output / 'RESULTS.json'}")
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
