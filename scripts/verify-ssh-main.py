#!/usr/bin/env python3
"""Public CLI fixtures and structured read-only six-node verification."""
import argparse
import datetime
import json
from pathlib import Path
import shlex
import sys

sys.dont_write_bytecode = True
from verification_contract import (NODES, ENGINES, capture, clean_environment, completion_play,
                                   context, digest, runtime_command, source_sha, stage, write_json)

ROOT = Path(__file__).resolve().parents[1]
PHASES = ('version', 'runtime', 'cli_guards', 'localhost_tasks', 'readonly_ssh',
          'hardening_check', 'main_precheck', 'dns_verify')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python216', type=Path, default=Path('/usr/bin/python3'))
    parser.add_argument('--python221', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    if args.plan:
        print(json.dumps({'schema_version': 1, 'engines': ENGINES, 'remote_nodes': NODES,
                          'phases': PHASES, 'collector': 'fds_verification callback',
                          'changes': 'Read-only checks; hardening check mode only. No operational engine switch.'}, indent=2))
        return 0
    out = args.output.resolve()
    if out.is_relative_to(ROOT):
        raise ValueError('Use a new evidence directory outside the source checkout')
    code = source_sha(ROOT)
    out.mkdir(parents=True, exist_ok=False)
    env = clean_environment(ROOT, out)
    env['ANSIBLE_STDOUT_CALLBACK'] = 'default'
    rows = []
    expected_steps = [engine + '_' + phase for engine in ENGINES for phase in PHASES]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    run_id = context(code, ENGINES[0], 'run')['run_id']

    def save(final=False):
        source_matches = False
        if final:
            try:
                source_matches = source_sha(ROOT) == code
            except (ValueError, OSError):
                pass
        complete = (final and source_matches and [r['stage_id'] for r in rows] == expected_steps and
                    all(r['status'] == 'PASS' for r in rows))
        write_json(out / 'VERIFICATION_REPORT.json', {'schema_version': 1, 'code_sha': code,
            'run_id': run_id, 'source_verified_after_run': source_matches if final else None,
            'started_at': started, 'expected_nodes': NODES, 'expected_steps': expected_steps,
            'completed': complete, 'overall': 'PASS_READONLY_SCOPE' if complete else 'REVIEW_REQUIRED',
            'operational_upgrade': 'NOT_PERFORMED', 'scope': 'fixtures and six-node read-only checks', 'steps': rows})
        return complete

    def local(name, command, check=None):
        rc, timeout, stdout, stderr = capture(command, ROOT, env, 600)
        (out / (name + '.stdout.log')).write_bytes(stdout)
        (out / (name + '.stderr.log')).write_bytes(stderr)
        passed = rc == 0 and not timeout
        if passed and check is not None:
            try:
                passed = bool(check(stdout))
            except (OSError, ValueError, KeyError, TypeError):
                passed = False
        rows.append({**context(code, name.split('_', 1)[0], name, run_id=run_id), 'cli_rc': rc, 'timed_out': timeout,
                     'status': 'PASS' if passed else 'REVIEW_REQUIRED',
                     'origin': {'command': [str(x) for x in command], 'kind': 'public CLI',
                         'artifacts': {name + suffix: digest(out / (name + suffix)) for suffix in ('.stdout.log', '.stderr.log')}}})
        save()
        print(name + ': ' + rows[-1]['status'], flush=True)
        return passed

    def guard_report(path):
        report = json.loads(path.read_text(encoding='utf-8'))
        return report['status'] == 'PASS' and report['outcomes'] == {'PASS': 14, 'FAIL': 0, 'ERROR': 0}

    save()
    key = Path.home() / '.ssh/p1_ansible_ed25519'
    known_hosts = Path.home() / '.ssh/known_hosts'
    if not key.is_file() or not known_hosts.is_file():
        (out / 'prerequisite_error.txt').write_text('Existing SSH key or known_hosts is missing. No SSH attempt.\n', encoding='utf-8')
        return 1
    common_args = ' '.join(['-o BatchMode=yes', '-o PreferredAuthentications=publickey', '-o PasswordAuthentication=no',
        '-o KbdInteractiveAuthentication=no', '-o StrictHostKeyChecking=yes',
        '-o ' + shlex.quote('UserKnownHostsFile=' + str(known_hosts)), '-o IdentitiesOnly=yes', '-o IdentityAgent=none',
        '-o ControlMaster=no', '-o ControlPath=none', '-o ControlPersist=no', '-o ConnectTimeout=10'])
    for label, python in zip(ENGINES, (args.python216.absolute(), args.python221.absolute())):
        executable = python.parent / 'ansible-playbook'
        if not local(label + '_version', [executable, '--version'], lambda raw: b'[core ' + label.encode() + b']' in raw):
            continue
        if not local(label + '_runtime', runtime_command(python, ROOT, label)):
            continue
        generated = out / (label + '_generated')
        summary = out / (label + '_cli_guards.json')
        if not local(label + '_cli_guards', [python, ROOT / 'tests/test-ssh-key-guards.py', '--output', summary,
                     '--export-dir', generated, '--ansible-playbook', executable, '--expect-engine', label],
                     lambda _: guard_report(summary)):
            continue
        if not local(label + '_localhost_tasks', [executable, '-i', 'localhost,', '-c', 'local',
                     '-e', json.dumps({'ansible_python_interpreter': str(python)}), generated / 'regression.yml']):
            continue
        variables = json.loads((generated / 'source-vars.json').read_text(encoding='utf-8'))
        variables.update(ssh_guards_file=str(generated / 'ssh-guards.yml'), ansible_ssh_common_args=common_args,
            ansible_connection='ssh', ansible_become=True, ansible_become_method='sudo', ansible_become_user='root',
            ansible_become_flags='-H -S -n', cr_dns_phase='verify')
        execution = generated / 'execution-vars.json'
        write_json(execution, variables)
        prefix = [executable, '-i', ROOT / 'inventory/hosts.yml', '--private-key', key, '-e', '@' + str(execution)]
        for phase, playbook in [('readonly_ssh', 'tests/ssh-server-readonly.yml'),
                                ('hardening_check', 'playbooks/harden_svc_ansible_key.yml'),
                                ('main_precheck', 'playbooks/precheck.yml'),
                                ('dns_verify', 'playbooks/cr-p1-ans-01-01-verify.yml')]:
            name = label + '_' + phase
            metadata = context(code, label, name, run_id=run_id)
            wrapper = generated / (phase + '-scope.json')
            # JSON is valid YAML. The marker is a separate final play for all six nodes.
            write_json(wrapper, [{'import_playbook': str(ROOT / playbook)}, completion_play(metadata)])
            command = prefix + (['--check'] if phase == 'hardening_check' else []) + [wrapper]
            result = stage(command, ROOT, out / name, env, metadata,
                           allowed_changes=(0, 1) if phase == 'hardening_check' else (0,),
                           require_ssh=phase == 'readonly_ssh')
            rows.append(result)
            save()
            print(name + ': ' + result['status'], flush=True)
            if result['status'] != 'PASS':
                break
    return 0 if save(final=True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
