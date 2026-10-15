#!/usr/bin/env python3
"""Exercise egress recovery source on localhost; never run operational plays."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

def fixture_environment(binary, out):
    env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
               ANSIBLE_CONFIG=str(out / 'ansible.cfg'), ANSIBLE_NOCOLOR='1')
    # The fixture's --ansible-bin selects its engine. Do not inherit a caller's
    # operational opt-in and silently run recap inventory with another engine.
    for key in ('FDS_ANSIBLE_ENGINE_DIR', 'FDS_ANSIBLE_ENGINE_VERSION'):
        env.pop(key, None)
    return env


def recap_command(repo, path, fn):
    # Extract only the pure recap function; sourcing the operational wrapper
    # would run host/account/key checks and dispatch an action.
    return ['bash', '-c', 'set -Eeuo pipefail\nrepo_root="$1"\n'
            'source "$repo_root/scripts/lib/ansible-engine.sh"\n'
            'fds_engine_init\n' + fn + '\nassert_idempotent "$2"',
            'fixture', repo, path]


def main():
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ansible-bin', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo, binary, out = args.repo.resolve(), args.ansible_bin.resolve(), args.output.resolve()
    if out.exists() or out.is_relative_to(repo):
        parser.error('Use a new output directory outside the checkout')
    out.mkdir(parents=True)
    env = fixture_environment(binary, out)
    (out / 'ansible.cfg').write_text('[defaults]\nroles_path=' + str(repo / 'roles') + '\n')
    apply = yaml.safe_load((repo / 'roles/egress_proxy/tasks/main.yml').read_text())
    rollback = yaml.safe_load((repo / 'playbooks/cr-p1-mon-01-01-rollback.yml').read_text())[-1]
    baseline_tasks = yaml.safe_load((repo / 'roles/egress_proxy/tasks/validate-baseline.yml').read_text())
    results = []

    def finish(error=None):
        record = {'status': 'PASS' if not error and all(r['passed'] for r in results) else 'FAIL',
                  'scope': 'localhost CLI/task tests and interruption model; no Squid/firewalld/SSH runtime',
                  'source_commit': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
                  'source_dirty': bool(subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'])),
                  'cases': results}
        if error:
            record['error'] = error
        (out / 'RESULTS.json').write_text(json.dumps(record, indent=2) + '\n')
        (out / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                                             for p in sorted(out.iterdir()) if p.is_file()))
        print(json.dumps(record, indent=2))
        return 0 if record['status'] == 'PASS' else 1

    def task(tasks, name):
        matches = [t for t in tasks if t.get('name') == name]
        assert len(matches) == 1, name
        return copy.deepcopy(matches[0])

    def run(name, command, expected=0):
        p = subprocess.run(list(map(str, command)), cwd=repo, env=env, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        (out / (name + '.log')).write_text(p.stdout)
        results.append({'case': name, 'expected_rc': expected, 'actual_rc': p.returncode,
                        'passed': p.returncode == expected})
        return p

    def play(name, tasks, variables, expected=0):
        path = out / (name + '.yml')
        path.write_text(yaml.safe_dump([{'name': name, 'hosts': 'localhost',
            'connection': 'local', 'gather_facts': False,
            'vars': dict(variables, ansible_python_interpreter=str(binary / 'python')),
            'tasks': tasks}], sort_keys=False))
        return run(name, [binary / 'ansible-playbook', '-i', 'localhost,', path], expected)

    for phase in ['precheck', 'apply', 'verify', 'rollback']:
        run('syntax-' + phase, [binary / 'ansible-playbook', '--syntax-check', '-i', 'localhost,',
                              repo / f'playbooks/cr-p1-mon-01-01-{phase}.yml'])
    run('bash-syntax', ['bash', '-n', repo / 'scripts/cr-p1-mon-01-01-run.sh'])
    runner = (repo / 'scripts/cr-p1-mon-01-01-run.sh').read_text()
    fn = runner[runner.index('assert_idempotent() {'):runner.index('\nrequire_change_approval()')]
    good = 'egress-proxy01 : ok=40 changed=0 unreachable=0 failed=0 skipped=3 rescued=0 ignored=0\n'
    local = 'localhost : ok=1 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0\n'
    for name, content, rc in [('one-proxy', good + local, 0), ('changed-proxy', good.replace('changed=0', 'changed=1'), 1),
                              ('localhost-only', local, 1), ('wrong-target', good.replace('egress-proxy01', 'k8s-worker01'), 1),
                              ('extra-target', good + good.replace('egress-proxy01', 'k8s-worker01'), 1)]:
        path = out / (name + '.recap'); path.write_text(content)
        run(name, recap_command(repo, path, fn), rc)

    ready = play('localhost-cli-preflight', [{'name': 'Require working localhost task execution',
                  'ansible.builtin.assert': {'that': [True]}}], {})
    if ready.returncode:
        return finish('Localhost CLI preflight failed; behavioral cases NOT RUN. Inspect the original log before classifying the cause.')

    state = out / 'state'; state.mkdir()
    original = state / 'original-squid.conf'; original.write_text('ORIGINAL A\n')
    current = out / 'current.conf'; current.write_text('CURRENT B\n')
    variables = {'cr_mon_phase': 'apply', 'cr_mon_state_dir': str(state),
                 'cr_mon_change_id': 'CR-P1-MON-01-01',
                 'cr_mon_baseline_file': {'stat': {'exists': False}},
                 'cr_mon_squid_conf_before': {'stat': {'exists': True}}}
    backup = task(apply, 'Preserve original squid configuration once')
    backup['ansible.builtin.copy']['src'] = str(current)
    for key in ['owner', 'group']: backup['ansible.builtin.copy'].pop(key)
    guards = [task(apply, 'Inspect the original configuration backup before any state writes'),
              task(apply, 'Refuse an orphan backup or a non-regular baseline')]
    play('orphan-refused-before-copy', guards + [backup], variables, 2)
    results.append({'case': 'orphan-bytes-preserved', 'passed': original.read_text() == 'ORIGINAL A\n'})
    play('copy-defence-preserves-existing', [backup], variables)
    results.append({'case': 'copy-defence-bytes-preserved', 'passed': original.read_text() == 'ORIGINAL A\n'})
    original.unlink()
    play('fresh-baseline-can-backup', guards + [backup], variables)
    results.append({'case': 'fresh-backup-bytes-match', 'passed': original.read_bytes() == current.read_bytes()})

    baseline = {'change_id': variables['cr_mon_change_id'], 'inventory_hostname': 'localhost',
        'squid_preinstalled': True, 'squid_conf_preexisted': True,
        'squid_service_active_state': 'active', 'squid_service_enabled_state': 'enabled',
        'squid_conf_owner': 'root', 'squid_conf_group': 'root', 'squid_conf_mode': '0644',
        'firewalld_default_zone': 'public', 'proxy_port': 3128, 'proxy_allowed_clients': ['10.1.93.105'],
        'firewalld_permanent_rules_before': [], 'firewalld_runtime_rules_before': []}
    cases = [('complete', baseline, 0), ('missing-rule-history',
              {k: v for k, v in baseline.items() if not k.startswith('firewalld_') or k == 'firewalld_default_zone'}, 2)]
    for field, value in [('firewalld_permanent_rules_before', None), ('firewalld_runtime_rules_before', {}),
                         ('squid_preinstalled', 'false'), ('proxy_port', True), ('proxy_allowed_clients', {}),
                         ('squid_conf_mode', 'bad'), ('inventory_hostname', 'other')]:
        cases.append(('invalid-' + field, dict(baseline, **{field: value}), 2))
    for name, snapshot, rc in cases:
        play('baseline-' + name, baseline_tasks, dict(variables, cr_mon_baseline=snapshot,
             cr_mon_backup_stat={'exists': True, 'isreg': True}), rc)

    # Exercise each source call site with real stat results, including symlinks.
    # Retain include vars/when so missing parameter wiring cannot pass unnoticed.
    routes = [
        ('apply', apply, 'Inspect the original configuration backup before any state writes',
         'Validate the complete existing baseline before re-apply'),
        ('rollback', rollback['pre_tasks'], 'Inspect the original configuration backup before rollback',
         'Validate the complete baseline before rollback changes')]
    for route, source, inspect_name, include_name in routes:
        include = task(source, include_name)
        include['ansible.builtin.include_tasks'] = str(repo / 'roles/egress_proxy/tasks/validate-baseline.yml')
        for name, preexisted, kind, rc in [
            ('regular', True, 'file', 0), ('missing', True, 'absent', 2),
            ('symlink', True, 'symlink', 2), ('directory', True, 'directory', 2),
            ('originally-absent', False, 'absent', 0), ('unexpected', False, 'file', 2)]:
            if original.is_dir() and not original.is_symlink():
                original.rmdir()
            else:
                original.unlink(missing_ok=True)
            if kind == 'file':
                original.write_text('ORIGINAL A\n')
            elif kind == 'symlink':
                original.symlink_to(current)
            elif kind == 'directory':
                original.mkdir()
            snapshot = dict(baseline, squid_conf_preexisted=preexisted)
            play('backup-' + route + '-' + name, [task(source, inspect_name), include],
                 dict(variables, cr_mon_baseline_file={'stat': {'exists': True}},
                      cr_mon_existing_baseline=snapshot, cr_mon_original_state=snapshot), rc)

    rule = 'rule family="ipv4" source address="10.1.93.105" port port="3128" protocol="tcp" accept'
    preserved = dict(baseline, firewalld_permanent_rules_before=[rule], firewalld_runtime_rules_before=[rule])
    post = task(rollback['tasks'], 'Verify every original firewall rule is still present')
    for name, after, rc in [('original-kept', [rule], 0), ('original-lost', [], 2), ('unrelated-added', [rule, 'other-rule'], 0)]:
        play(name, [post], dict(variables, cr_mon_original_state=preserved,
             cr_mon_firewalld_permanent_rules_after={'stdout_lines': after},
             cr_mon_firewalld_runtime_rules_after={'stdout_lines': after}), rc)

    # Interrupt after any restoration mutation: the first mutation must already
    # have removed the old marker. The process state here is a model, not Squid.
    invalidation = task(rollback['tasks'], 'Invalidate managed configuration marker before rollback changes')
    results.append({'case': 'invalidation-before-first-rollback-change',
                    'passed': rollback['tasks'][0] == invalidation})
    marker = state / 'active-config.sha1'; marker.write_text('managed-config-hash')
    play('invalidate-before-interruption', [invalidation], variables)
    results.append({'case': 'interrupted-rollback-has-no-stale-marker', 'passed': not marker.exists()})
    reload_task = task(apply, 'Reload squid when it was already running and the config differs from the marker')
    model = dict(variables, cr_mon_squid_service_before={'stdout_lines': ['loaded', 'active']},
                 cr_mon_squid_active_marker={'stat': {'exists': marker.exists()}},
                 cr_mon_squid_active_marker_file={'content': base64.b64encode(b'managed-config-hash').decode()},
                 cr_mon_squid_conf_deployed={'stat': {'checksum': 'managed-config-hash'}})
    play('reapply-selects-reload-after-interruption', [{'name': 'Require reload in the interrupted rollback model',
          'ansible.builtin.assert': {'that': reload_task['when']}}], model)
    return finish()


if __name__ == '__main__':
    sys.exit(main())
