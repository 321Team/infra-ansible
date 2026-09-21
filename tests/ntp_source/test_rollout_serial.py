#!/usr/bin/env python3
"""Focused local proof: the third client fails, restores its pair, stops the batch.

Uses the real client playbook's host selection/serial/any_errors_fatal and role
with local file transactions and chronyd -p. Host services and chronyc are
fixtures. No SSH, UDP, daemon, or production configuration is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import traceback

import yaml

from test_migration import Fixture, ROOT, HERE, VARS, SOURCE_UPSTREAMS
from test_ntp_source import instrument

HOSTS = ['k8s-control02', 'k8s-control03', 'k8s-worker01', 'k8s-worker02', 'k8s-worker03']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ansible-playbook', required=True)
    parser.add_argument('--chronyd', required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(name='five_clients_third_failure_restores_and_stops', passed=False,
                  scope='LOCAL Ansible/files/parser; service and chronyc mocked; no host/network acceptance')
    try:
        role = output / 'roles/ntp_source'
        shutil.copytree(ROOT / 'roles/ntp_source', role)
        for path in (role / 'tasks').glob('*.yml'):
            tasks = yaml.safe_load(path.read_text())
            instrument(tasks, output)
            path.write_text(yaml.safe_dump(tasks, sort_keys=False))
        shutil.copytree(ROOT / 'module_utils', output / 'module_utils')
        library = output / 'library'
        shutil.copytree(ROOT / 'library', library)
        plugins = output / 'action_plugins'
        plugins.mkdir()
        shutil.copyfile(HERE / 'fixture_action.py', plugins / 'ntp_fixture.py')
        fixtures, before, hostvars = {}, {}, {}
        for index, host in enumerate(HOSTS):
            f = Fixture(output / host, args.chronyd, existing=True)
            fixtures[host], before[host] = f, f.pair()
            hostvars[host] = dict(ansible_connection='local',
                                  ansible_python_interpreter=shutil.which('python3'),
                                  cr_ntp_main_config_path=str(f.main), cr_ntp_dropin_path=str(f.dropin),
                                  cr_ntp_state_dir=str(f.state), cr_ntp_chronyd_path=args.chronyd,
                                  fixture_root=str(f.root), fixture_scenario={'restart_fail': index == 2})
        inventory = {'all': {'vars': dict(VARS, cr_ntp_migrate_main=True,
                                           cr_ntp_source_upstreams=SOURCE_UPSTREAMS,
                                           cr_ntp_change_approved=VARS['cr_ntp_change_id'],
                                           ansible_date_time={'iso8601': '2026-09-18T00:00:00Z'}),
                             'children': {'k8s_nodes': {'children': {
                                 'k8s_controlplane': {'hosts': {h: hostvars[h] for h in HOSTS[:2]}},
                                 'k8s_workers': {'hosts': {h: hostvars[h] for h in HOSTS[2:]}}
                             }}}}}
        inventory_path = output / 'inventory.yml'
        inventory_path.write_text(yaml.safe_dump(inventory, sort_keys=False))
        source = ROOT / 'playbooks/cr-p1-ntp-01-01-apply-clients.yml'
        play = yaml.safe_load(source.read_text())
        assert play[0]['serial'] == 1 and play[0]['any_errors_fatal'] is True
        assert play[0]['hosts'] == 'k8s-control02:k8s-control03:k8s_workers'
        play[0].update(gather_facts=False, become=False)
        play_path = output / 'clients.yml'
        play_path.write_text(yaml.safe_dump(play, sort_keys=False))
        config = output / 'ansible.cfg'
        config.write_text('[defaults]\nretry_files_enabled=False\nhost_key_checking=True\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ANSIBLE_', 'PYTHON'))}
        env.update(ANSIBLE_CONFIG=str(config), ANSIBLE_NOCOLOR='1', LANG='C.UTF-8', LC_ALL='C.UTF-8',
                   ANSIBLE_LIBRARY=str(library), ANSIBLE_ACTION_PLUGINS=str(plugins),
                   ANSIBLE_MODULE_UTILS=str(output / 'module_utils'))
        command = [args.ansible_playbook, '-i', str(inventory_path), str(play_path)]
        process = subprocess.run(command, env=env, cwd=output, capture_output=True, text=True, timeout=120)
        (output / 'stdout.log').write_text(process.stdout)
        (output / 'stderr.log').write_text(process.stderr)
        assert process.returncode == 2, process.returncode
        assert 'FIXTURE_SERVICE_FAILURE' in process.stdout
        hosts = {}
        for index, host in enumerate(HOSTS):
            f = fixtures[host]
            events_path = f.root / 'events.json'
            events = json.loads(events_path.read_text()) if events_path.exists() else {'restarts': 0, 'events': []}
            if index < 2:
                assert f.pair() != before[host] and f.baseline.exists(), host
                assert events['restarts'] == 1, (host, events)
            elif index == 2:
                assert f.pair() == before[host] and f.baseline.exists(), host
                assert events['restarts'] == 2, (host, events)
            else:
                assert f.pair() == before[host] and not f.state.exists(), host
                assert not events['events'], (host, events)
            hosts[host] = dict(restarts=events['restarts'], observed_commands=len(events['events']),
                               pair_matches_before=f.pair() == before[host], baseline=f.baseline.exists())
        result.update(passed=True, rc=process.returncode, hosts=hosts,
                      playbook_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                      migration_module_sha256=hashlib.sha256((library/'fds_ntp_migration.py').read_bytes()).hexdigest())
    except Exception:
        result['error'] = traceback.format_exc()
    (output / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
