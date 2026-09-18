#!/usr/bin/env python3
"""Actual Ansible module_utils transport and unsupported-provider early guards.

Run locally only. Invalid provider inputs must fail before any managed-host
observation or transaction; no SSH, NTP packet, daemon or clock change occurs.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ansible-playbook', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(ROOT / 'library', directory / 'library')
    shutil.copytree(ROOT / 'module_utils', directory / 'module_utils')
    settings = dict(source_upstreams=['162.159.200.1', '129.6.15.28'])
    probe = dict(settings, gate='diagnose', run_id='fixture-transport',
                 source_head='a' * 40, input_sha256='b' * 64,
                 inventory_hostname='k8s-control01', ansible_host='10.1.93.102',
                 migration_plan={'validated': True})
    migration = dict(settings, action='apply', main_path=str(directory / 'must-not-exist.conf'),
                     dropin_path=str(directory / 'must-not-exist.d/ntp.conf'),
                     state_dir=str(directory / 'must-not-exist-state'),
                     role='source', inventory_hostname='k8s-control01',
                     source_ip='10.1.93.102',
                     client_ips=['10.1.93.103', '10.1.93.104', '10.1.93.105', '10.1.93.107', '10.1.93.108'],
                     change_id='CR-P1-NTP-01-01')
    tasks = []
    for name, params in [('fds_ntp_probe', probe), ('fds_ntp_migration', migration)]:
        tasks += [{'name': 'Exercise actual ' + name + ' transport', name: params,
                   'register': 'guard_result', 'ignore_errors': True},
                  {'name': 'Require provider guard after successful dependency transport',
                   'ansible.builtin.assert': {'that': ['guard_result is failed',
                       'not guard_result.changed',
                       "'Unsupported iburst upstream: 129.6.15.28' in guard_result.msg"]}}]
    play = [dict(hosts='localhost', connection='local', gather_facts=False, become=False,
                 vars={'ansible_python_interpreter': shutil.which('python3')}, tasks=tasks)]
    (directory / 'case.yml').write_text(yaml.safe_dump(play, sort_keys=False))
    config = directory / 'ansible.cfg'
    config.write_text('[defaults]\nretry_files_enabled=False\n')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('ANSIBLE_', 'PYTHON'))}
    env.update(ANSIBLE_CONFIG=str(config), ANSIBLE_LIBRARY=str(directory / 'library'),
               ANSIBLE_MODULE_UTILS=str(directory / 'module_utils'), ANSIBLE_NOCOLOR='1',
               LC_ALL='C.UTF-8', LANG='C.UTF-8')
    process = subprocess.run([args.ansible_playbook, '-i', 'localhost,', str(directory / 'case.yml')],
                             env=env, cwd=directory, capture_output=True, text=True, timeout=60)
    (directory / 'stdout.log').write_text(process.stdout)
    (directory / 'stderr.log').write_text(process.stderr)
    passed = process.returncode == 0 and not list(directory.glob('must-not-exist*'))
    result = dict(passed=passed, total=2, passed_cases=2 if passed else 0,
                  modules=['fds_ntp_probe', 'fds_ntp_migration'], returncode=process.returncode,
                  scope=__doc__)
    (directory / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
