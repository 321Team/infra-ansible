#!/usr/bin/env python3
"""Run localhost regressions and read-only six-node checks on ansible01."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NODES = {'k8s-control01', 'k8s-control02', 'k8s-control03', 'k8s-worker01', 'k8s-worker02', 'k8s-worker03'}
p = argparse.ArgumentParser()
p.add_argument('--python221', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--plan', action='store_true')
args = p.parse_args()
if args.plan:
    print(json.dumps({'engines': ['system 2.16.19', 'isolated 2.21.3'], 'remote_nodes': sorted(NODES),
        'phases': ['14 public CLI source-guard fixtures', '14 exported localhost task fixtures',
                   'fresh SSH / sudo / original guards / unchanged key file',
                   'corrected hardening playbook --check', 'main precheck', 'main DNS verify'],
        'changes': 'No configuration apply; Ansible temporary transport files and normal access logs may be created.'}, indent=2))
    raise SystemExit(0)
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update(ANSIBLE_CONFIG=str(ROOT/'ansible.cfg'), ANSIBLE_NOCOLOR='1', ANSIBLE_STDOUT_CALLBACK='default',
           PYTHONDONTWRITEBYTECODE='1', ANSIBLE_HOST_KEY_CHECKING='True',
           ANSIBLE_SSH_ARGS='-C -o ControlMaster=no -o ControlPersist=no -o ControlPath=none',
           ANSIBLE_SSH_USETTY='False',
           ANSIBLE_LOCAL_TEMP=str(out.parent/'ansible-local'))
for name in ['PYTHONPATH', 'PR3_REVIEW_MOCK', 'PR3_REVIEW_CASE', 'PR3_REVIEW_TRACE']:
    env.pop(name, None)
rows = []

def run(name, command, remote=False):
    begin = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        r = subprocess.run([str(x) for x in command], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        text = r.stdout + r.stderr
        rc = r.returncode
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
        text = decoded(exc.stdout) + decoded(exc.stderr)
        text += '\nVERIFICATION TIMEOUT\n'
        rc = 124
    except OSError as exc:
        text = str(exc)+'\n'
        rc = 127
    (out/(name+'.txt')).write_text(text)
    row = {'name': name, 'started_at': begin, 'rc': rc, 'command': [str(x) for x in command], 'remote': remote}
    if remote:
        recap = text[text.rfind('PLAY RECAP'):] if 'PLAY RECAP' in text else ''
        nodes = re.findall(r'^(k8s-\S+)\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)\s+skipped=(\d+)\s+rescued=(\d+)\s+ignored=(\d+)', recap, re.M)
        row['recap'] = {n[0]: dict(zip(['ok', 'changed', 'unreachable', 'failed', 'skipped', 'rescued', 'ignored'], map(int, n[1:]))) for n in nodes}
        row['all_six_verified'] = (len(nodes) == 6 and set(row['recap']) == NODES and
            all(x['ok'] > 0 and x['unreachable'] == x['failed'] == x['rescued'] == x['ignored'] == 0 for x in row['recap'].values()))
        row['changed_total'] = sum(x['changed'] for x in row['recap'].values())
        if name.endswith('_readonly_ssh'):
            row['ssh_pass_count'] = text.count('"verdict": "SSH_READONLY_PASS"')
            row['all_six_verified'] &= row['ssh_pass_count'] == 6 and row['changed_total'] == 0
        elif not name.endswith('_hardening_check'):
            row['all_six_verified'] &= row['changed_total'] == 0
    row['status'] = 'PASS' if rc == 0 and (not remote or row['all_six_verified']) else 'REVIEW_REQUIRED'
    rows.append(row)
    (out/'VERIFICATION_REPORT.json').write_text(json.dumps({'overall': 'REVIEW_REQUIRED', 'steps': rows}, indent=2)+'\n')
    print(json.dumps({k: row[k] for k in ['name', 'rc', 'status']}), flush=True)
    return row, text

key = Path.home()/'.ssh/p1_ansible_ed25519'
known_hosts = Path.home()/'.ssh/known_hosts'
if not key.is_file() or not known_hosts.is_file():
    (out/'prerequisite_error.txt').write_text('Existing p1_ansible_ed25519 or known_hosts is missing. No SSH attempt was made.\n')
    raise SystemExit(1)
# A new SSH process must authenticate with the existing key; do not reuse a
# multiplexed session or accept a previously unknown host key.
common_args = ' '.join(['-o BatchMode=yes', '-o PreferredAuthentications=publickey', '-o PasswordAuthentication=no',
    '-o KbdInteractiveAuthentication=no', '-o StrictHostKeyChecking=yes',
    '-o '+shlex.quote('UserKnownHostsFile='+str(known_hosts)), '-o IdentitiesOnly=yes', '-o IdentityAgent=none',
    '-o ControlMaster=no', '-o ControlPath=none', '-o ControlPersist=no', '-o ConnectTimeout=10'])
for label, python in [('2.16.19', Path('/usr/bin/python3')), ('2.21.3', args.python221.absolute())]:
    executable = python.parent/'ansible-playbook'
    version, text = run(label+'_version', [executable, '--version'])
    if version['rc'] or f'[core {label}]' not in text:
        rows[-1]['status'] = 'REVIEW_REQUIRED'
        continue
    generated = out/(label+'_generated')
    step, _ = run(label+'_cli_guards', [python, ROOT/'tests/test-ssh-key-guards.py', '--output', out/(label+'_cli_guards.json'), '--export-dir', generated, '--ansible-playbook', executable, '--expect-engine', label])
    if step['status'] != 'PASS':
        continue
    step, _ = run(label+'_localhost_tasks', [executable, '-i', 'localhost,',
        '-e', json.dumps({'ansible_python_interpreter': str(python)}), generated/'regression.yml'])
    if step['status'] != 'PASS':
        continue
    variables = json.loads((generated/'source-vars.json').read_text())
    variables.update(ssh_guards_file=str(generated/'ssh-guards.yml'), ansible_ssh_common_args=common_args,
        ansible_connection='ssh', ansible_become=True, ansible_become_method='sudo',
        ansible_become_user='root', ansible_become_flags='-H -S -n',
        cr_dns_phase='verify')
    context = generated/'execution-vars.json'
    context.write_text(json.dumps(variables, indent=2)+'\n')
    prefix = [executable, '-i', ROOT/'inventory/hosts.yml', '--private-key', key, '-e', '@'+str(context)]
    step, _ = run(label+'_readonly_ssh', prefix+[ROOT/'tests/ssh-server-readonly.yml'], remote=True)
    if step['status'] != 'PASS':
        continue
    run(label+'_hardening_check', prefix+['--check', ROOT/'playbooks/harden_svc_ansible_key.yml'], remote=True)
    run(label+'_main_precheck', prefix+[ROOT/'playbooks/precheck.yml'], remote=True)
    run(label+'_dns_verify', prefix+[ROOT/'playbooks/cr-p1-ans-01-01-verify.yml'], remote=True)
complete = len(rows) == 14 and all(x['status'] == 'PASS' for x in rows)
(out/'VERIFICATION_REPORT.json').write_text(json.dumps({'overall': 'PASS_READONLY_SCOPE' if complete else 'REVIEW_REQUIRED',
    'operational_upgrade': 'NOT_APPROVED_BY_THIS_RUN', 'scope': 'localhost fixtures and real-node read-only checks; no configuration apply or rollback', 'steps': rows}, indent=2)+'\n')
raise SystemExit(0 if complete else 1)
