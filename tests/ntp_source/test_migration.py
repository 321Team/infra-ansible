#!/usr/bin/env python3
"""Local migration tests: real file transactions and optional real chronyd parser.

Runs under uid 0 only so the production ownership checks remain unchanged.
Every mutable path is beneath the requested fresh output directory. chronyd is
called only with -p; no daemon, clock, network, SSH, or host service is started.
Ansible integration replaces service and chronyc observations with the existing
fixture action while retaining real module execution, blocks, and rescue.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import traceback
from unittest.mock import patch

import yaml

from test_ntp_source import instrument, VARS

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OBSERVED = (HERE / 'fixtures/observed-chrony.conf').read_bytes()
OBSERVED_SHA = '147346c1b876b87dfad3bd436c62bc137c36723137ed5b647cf376a9f54e66aa'
# Parser fixtures only: these addresses are NOT an operational selection.
SOURCE_UPSTREAMS = ['162.159.200.1', '162.159.200.123', '129.6.15.28']
MODULE = None


def file_state(path):
    """Capture bytes and safety-relevant metadata without following symlinks."""
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    return dict(mode=stat.S_IMODE(value.st_mode), uid=value.st_uid, gid=value.st_gid,
                nlink=value.st_nlink, type=stat.S_IFMT(value.st_mode),
                bytes=path.read_bytes().hex() if stat.S_ISREG(value.st_mode) else None,
                target=os.readlink(path) if stat.S_ISLNK(value.st_mode) else None,
                xattrs={name: os.getxattr(path, name, follow_symlinks=False).hex()
                        for name in os.listxattr(path, follow_symlinks=False)})


class Fixture:
    def __init__(self, directory, chronyd, role='client', existing=False):
        self.root = directory
        directory.mkdir(parents=True)
        self.main = directory / 'chrony.conf'
        self.main.write_bytes(OBSERVED)
        self.main.chmod(0o640)
        self.confdir = directory / 'chrony.d'
        self.confdir.mkdir(mode=0o755)
        self.dropin = self.confdir / '50-cr-p1-ntp-01-01.conf'
        if existing:
            self.dropin.write_bytes(b'# pre-existing managed fragment\nserver 192.0.2.123 iburst\n')
            self.dropin.chmod(0o600)
        self.state = directory / 'state'
        self.baseline = self.state / 'original-ntp-pair.json'
        self.args = dict(action='apply', main_path=str(self.main),
                         dropin_path=str(self.dropin), state_dir=str(self.state),
                         change_id=VARS['cr_ntp_change_id'], inventory_hostname='localhost',
                         role=role, source_ip=VARS['cr_ntp_source_ip'],
                         client_ips=VARS['cr_ntp_client_ips'], chronyd_path=chronyd,
                         source_upstreams=SOURCE_UPSTREAMS)
        self.calls = []

    def pair(self):
        return {name: file_state(getattr(self, name)) for name in ('main', 'dropin')}

    def run(self, action='apply', check=False, **kwargs):
        transaction = MODULE.Transaction(dict(self.args, action=action, **kwargs), check_mode=check)
        result = transaction.run()
        self.calls.append(dict(action=action, check=check, result=result))
        return result

    def expect_failure(self, call, substring=None):
        before = self.pair()
        baseline = file_state(self.baseline)
        try:
            call()
        except Exception as exc:
            text = str(exc)
            if substring:
                assert substring.lower() in text.lower(), text
            self.calls.append(dict(expected_failure=text))
        else:
            raise AssertionError('Expected rejection, but the operation succeeded')
        assert self.pair() == before, 'Rejected operation changed main/dropin bytes or metadata'
        assert file_state(self.baseline) == baseline, 'Rejected operation changed immutable baseline'

    def effective(self):
        done = subprocess.run([self.args['chronyd_path'], '-p', '-f', str(self.main)],
                              capture_output=True, text=True, timeout=15,
                              env=dict(os.environ, LC_ALL='C'))
        (self.root / 'effective.stdout.log').write_text(done.stdout)
        (self.root / 'effective.stderr.log').write_text(done.stderr)
        assert done.returncode == 0, done.stderr
        return done.stdout.splitlines()


def active(lines, directives):
    return [line for line in lines if line.split() and line.split()[0].lower() in directives]


def scenario_candidate(f, role):
    f.args['role'] = role
    unrelated = f.confdir / '99-unrelated.conf'
    unrelated.write_text('pool unrelated.invalid iburst\n')
    unrelated_before = file_state(unrelated)
    before = f.pair()
    result = f.run()
    assert result['changed'] is True
    assert f.main.stat().st_mode & 0o777 == 0o640
    assert f.main.read_bytes().count(('include ' + str(f.dropin)).encode()) == 1
    assert b'confdir ' not in f.main.read_bytes()
    lines = f.effective()
    sources = active(lines, {'server', 'pool', 'peer', 'sourcedir', 'refclock', 'local', 'manual'})
    if role == 'client':
        assert sources == ['server 10.1.93.102 iburst'], sources
        assert not active(lines, {'allow'}), lines
    else:
        assert set(sources) == {'server ' + ip + ' iburst' for ip in SOURCE_UPSTREAMS}, sources
        assert len(sources) == 3
        allows = active(lines, {'allow'})
        assert set(allows) == {'allow ' + ip + '/32' for ip in VARS['cr_ntp_client_ips']}, allows
        assert len(allows) == 5
    assert file_state(unrelated) == unrelated_before
    original = json.loads(f.baseline.read_text())
    assert original['schema_version'] == 2
    assert base64.b64decode(original['main']['content_b64']).hex() == before['main']['bytes']
    assert original['main']['sha256'] == OBSERVED_SHA
    assert original['dropin']['existed'] == (before['dropin'] is not None)
    baseline = file_state(f.baseline)
    installed = f.pair()
    second = f.run()
    assert second['changed'] is False
    assert f.pair() == installed
    assert file_state(f.baseline) == baseline


def scenario_readonly(f, action, check):
    before = f.pair()
    result = f.run(action, check)
    assert result['would_change'] is True, result
    assert result['changed'] is (action == 'apply'), result
    assert f.pair() == before
    assert not f.state.exists(), 'Read-only planning created persistent state'
    assert set(f.root.iterdir()) == {f.main, f.confdir}, 'Planning leaked temporary files'


def scenario_unknown(f, migrated=False):
    if migrated:
        f.run()
    with f.main.open('ab') as stream:
        stream.write(b'pool unreviewed.invalid iburst\n')
    f.expect_failure(f.run, 'drift' if migrated else 'not the observed native main')


def scenario_unsafe(f, target, kind):
    path = getattr(f, target)
    if target == 'state':
        path.mkdir(mode=0o700)
    elif target == 'baseline':
        f.run()
    elif target == 'dropin' and not path.exists():
        path.write_text('# original\n')
    expected = ('Unsafe writable' if kind == 'mode' else
                'Unsafe directory type/owner' if target == 'state' else
                'Unsafe file type/link/owner')
    if kind == 'symlink':
        saved = path.with_name(path.name + '.original')
        path.rename(saved)
        path.symlink_to(saved)
    elif kind == 'hardlink':
        os.link(path, path.with_name(path.name + '.hardlink'))
    elif kind == 'directory':
        path.unlink()
        path.mkdir()
    elif kind == 'owner':
        try:
            os.chown(path, 65534, 65534)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.EPERM):
                raise
            # Some CI user namespaces map only uid 0. Exercise the unchanged
            # ownership guard with a recorded lstat observation in that case.
            lstat = os.lstat
            def nonroot_stat(value, *args, **kwargs):
                info = lstat(value, *args, **kwargs)
                if Path(value) == path:
                    values = list(info)
                    values[4] = 65534
                    return os.stat_result(values)
                return info
            f.calls.append(dict(ownership_fixture='lstat uid simulated; namespace cannot chown nonzero uid'))
            with patch.object(os, 'lstat', nonroot_stat), patch.object(Path, 'lstat', lambda value: nonroot_stat(value)):
                f.expect_failure(f.run, expected)
            return
    elif kind == 'mode':
        path.chmod(0o777 if target == 'state' else 0o666)
    f.expect_failure(f.run, expected)


def scenario_baseline(f, kind):
    if kind == 'legacy':
        f.state.mkdir(mode=0o700)
        path = f.state / 'original-ntp-dropin.json'
        path.write_text('{"schema_version": 1}\n')
        path.chmod(0o600)
    else:
        f.run()
        data = json.loads(f.baseline.read_text())
        if kind == 'schema':
            data['schema_version'] = 1
        elif kind == 'identity':
            data['inventory_hostname'] = 'wrong-host'
        elif kind == 'path':
            data['main_path'] = str(f.root / 'unrelated.conf')
        elif kind == 'hash':
            data['main']['content_b64'] = base64.b64encode(b'tampered\n').decode()
        f.baseline.write_text(json.dumps(data))
    expected = {'legacy': 'Legacy', 'hash': 'checksum/base64'}.get(kind, 'identity/schema')
    f.expect_failure(f.run, expected)
    f.expect_failure(lambda: f.run('rollback'), expected)


def scenario_write_failure(f, target):
    before = f.pair()
    transaction = MODULE.Transaction(dict(f.args), check_mode=False)
    original = transaction.write_file
    injected = []
    def fail_after_write(path, value):
        result = original(path, value)
        if Path(path) == getattr(f, target) and not injected:
            injected.append(str(path))
            raise OSError('INJECTED_AFTER_' + target.upper() + '_WRITE')
        return result
    transaction.write_file = fail_after_write
    try:
        transaction.run()
    except Exception as exc:
        assert 'INJECTED_AFTER_' in str(exc), str(exc)
        f.calls.append(dict(expected_failure=str(exc), injected=injected))
    else:
        raise AssertionError('Injected write failure did not propagate')
    assert injected
    assert f.pair() == before, 'Partial write failure did not restore BOTH files and metadata'
    assert f.baseline.exists(), 'Original pair was not preserved before first write'


def scenario_snapshot(f):
    original = f.pair()
    f.run()
    immutable = file_state(f.baseline)
    installed = f.pair()
    noop = f.run()
    assert noop['changed'] is False
    f.run('restore', snapshot=noop['snapshot'])
    assert f.pair() == installed, 'No-op invocation rescue used original baseline'
    f.run('rollback')
    assert f.pair() == original
    f.dropin.write_text('# second invocation state\nserver 192.0.2.124 iburst\n')
    f.dropin.chmod(0o600)
    invocation = f.pair()
    result = f.run()
    assert result['changed'] is True
    f.run('restore', snapshot=result['snapshot'])
    assert f.pair() == invocation, 'Rescue restored old CR baseline instead of invocation snapshot'
    assert file_state(f.baseline) == immutable
    f.run('rollback')
    assert f.pair() == original, 'Manual rollback did not restore original pair'
    assert file_state(f.baseline) == immutable


def scenario_upstreams(f, values):
    f.args.update(role='source', source_upstreams=values)
    expected = ('Expected 4 octets' if 'pool.ntp.org' in values else
                'unicast public IPv4' if '10.0.0.1' in values else 'exactly three distinct')
    f.expect_failure(lambda: f.run('plan'), expected)
    f.expect_failure(f.run, expected)
    f.expect_failure(lambda: f.run(check=True), expected)


def scenario_source_rollback_unconfigured(f):
    f.args['role'] = 'source'
    original = f.pair()
    applied = f.run()
    f.args['source_upstreams'] = []
    f.run('restore', snapshot=applied['snapshot'])
    assert f.pair() == original
    f.args['source_upstreams'] = SOURCE_UPSTREAMS
    f.run()
    f.args['source_upstreams'] = []
    f.run('rollback')
    assert f.pair() == original


def scenario_xattrs(f, target):
    os.setxattr(getattr(f, target), 'user.ntp_fixture', b'preserve me')
    f.expect_failure(f.run, 'Unsupported file ACL/xattrs')


def scenario_parent_acl(f, target):
    path = f.main.parent if target == 'main' else f.dropin.parent
    acl = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', tag, mode, 0xffffffff)
                                         for tag, mode in ((1, 7), (4, 5), (32, 5)))
    os.setxattr(path, 'system.posix_acl_default', acl)
    f.expect_failure(f.run, 'Default directory ACL')
    assert os.getxattr(path, 'system.posix_acl_default') == acl


def scenario_ancestor_acl(f):
    # Existing config parents have no default ACL. A future state directory
    # would inherit one from their common ancestor unless rejected early.
    operational = f.root / 'operational'
    operational.mkdir()
    f.main = f.main.rename(operational / 'chrony.conf')
    f.confdir = f.confdir.rename(operational / 'chrony.d')
    f.dropin = f.confdir / f.dropin.name
    f.args.update(main_path=str(f.main), dropin_path=str(f.dropin))
    acl = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', tag, mode, 0xffffffff)
                                         for tag, mode in ((1, 7), (4, 5), (32, 5)))
    os.setxattr(f.root, 'system.posix_acl_default', acl)
    f.expect_failure(f.run, 'Default directory ACL')
    assert not f.state.exists(), 'Inherited ACL was rejected only after creating persistent state'


def module_cases():
    for role in ('client', 'source'):
        for existing in (False, True):
            yield f'{role}_candidate_{"existing" if existing else "new"}', existing, lambda f, role=role: scenario_candidate(f, role)
    yield 'plan_no_mutation', True, lambda f: scenario_readonly(f, 'plan', False)
    yield 'check_no_mutation', True, lambda f: scenario_readonly(f, 'apply', True)
    yield 'unknown_main_rejected', True, scenario_unknown
    yield 'migrated_main_drift_rejected', True, lambda f: scenario_unknown(f, True)
    for target in ('main', 'dropin', 'baseline', 'state'):
        kinds = ('symlink', 'owner', 'mode') if target == 'state' else ('symlink', 'hardlink', 'directory', 'owner', 'mode')
        for kind in kinds:
            yield f'{target}_{kind}_rejected', True, lambda f, target=target, kind=kind: scenario_unsafe(f, target, kind)
    for kind in ('legacy', 'schema', 'identity', 'path', 'hash'):
        yield 'baseline_' + kind + '_rejected', True, lambda f, kind=kind: scenario_baseline(f, kind)
    for target in ('dropin', 'main'):
        for existing in (False, True):
            yield f'{target}_write_failure_{"existing" if existing else "new"}', existing, lambda f, target=target: scenario_write_failure(f, target)
    for existing in (False, True):
        yield 'invocation_snapshot_vs_baseline_' + ('existing' if existing else 'new'), existing, scenario_snapshot
    for name, values in (
        ('missing', []), ('two', SOURCE_UPSTREAMS[:2]),
        ('four', SOURCE_UPSTREAMS + ['129.6.15.29']),
        ('duplicate', [SOURCE_UPSTREAMS[0]] * 3),
        ('private', ['10.0.0.1'] + SOURCE_UPSTREAMS[:2]),
        ('hostname', ['pool.ntp.org'] + SOURCE_UPSTREAMS[:2]),
    ):
        yield 'source_upstreams_' + name + '_rejected', True, lambda f, values=values: scenario_upstreams(f, values)
    yield 'source_restore_and_rollback_without_upstream_selection', True, scenario_source_rollback_unconfigured
    for target in ('main', 'dropin'):
        yield target + '_xattr_rejected_without_loss', True, lambda f, target=target: scenario_xattrs(f, target)
        yield target + '_parent_default_acl_rejected', True, lambda f, target=target: scenario_parent_acl(f, target)
    yield 'ancestor_default_acl_rejected_before_state_creation', True, scenario_ancestor_acl


def run_module_case(case, output, chronyd):
    name, existing, body = case
    f = Fixture(output / name, chronyd, existing=existing)
    try:
        body(f)
        result = dict(name=name, passed=True)
    except Exception:
        result = dict(name=name, passed=False, error=traceback.format_exc())
    (f.root / 'calls.json').write_text(json.dumps(f.calls, indent=2, default=str) + '\n')
    (f.root / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def flow_cases():
    yield 'flow_client_apply', dict()
    yield 'flow_source_apply', dict(source=True)
    yield 'flow_source_wrong_selected_rejected', dict(source=True, address='8.8.8.8', failure=True, restarts=2)
    yield 'flow_source_extra_source_rejected', dict(source=True, extra_source=True, failure=True, restarts=2)
    yield 'flow_source_missing_upstream_rejected', dict(source=True, source_missing=True, failure=True, restarts=2)
    yield 'flow_source_no_selected_rejected', dict(source=True, source_no_selected=True, failure=True, restarts=2)
    yield 'flow_source_multiple_selected_rejected', dict(source=True, source_two_selected=True, failure=True, restarts=2)
    yield 'flow_source_offset_rejected', dict(source=True, system_time='0.5', failure=True, restarts=2)
    yield 'flow_client_check', dict(check=True)
    yield 'flow_source_check', dict(source=True, check=True)
    yield 'flow_restart_failure', dict(restart_fail=True, failure=True, restarts=2)
    yield 'flow_wait_failure', dict(wait_fail=True, failure=True, restarts=2)
    yield 'flow_verify_failure', dict(system_time='0.5', failure=True, restarts=2)
    yield 'flow_noop_failure_preserves_installed_pair', dict(seed=True, system_time='0.5', failure=True, restarts=0)
    yield 'flow_new_invocation_failure_preserves_new_snapshot', dict(seed=True, drift=True, wait_fail=True, failure=True, restarts=2)
    yield 'flow_client_targeted_manual_rollback', dict(rollback=True)
    yield 'flow_source_targeted_manual_rollback', dict(source=True, rollback=True)
    yield 'flow_same_pair_idempotent', dict(seed=True, restarts=0)
    yield 'flow_check_rollback_preserves_pair', dict(rollback=True, rollback_check=True)


def run_flow_case(case, output, chronyd, executable):
    name, scenario = case
    f = Fixture(output / name, chronyd, role='source' if scenario.get('source') else 'client', existing=True)
    try:
        original = f.pair()
        if scenario.get('seed'):
            f.run()
            if scenario.get('drift'):
                # A reviewed native layout can be reapplied using the same
                # immutable CR baseline, but rescue belongs to this invocation.
                f.run('rollback')
                f.dropin.write_text('# invocation-specific fragment\nserver 192.0.2.124 iburst\n')
                f.dropin.chmod(0o600)
        before = f.pair()
        saved_baseline = file_state(f.baseline)
        role = f.root / 'roles/ntp_source'
        shutil.copytree(ROOT / 'roles/ntp_source', role)
        for path in (role / 'tasks').glob('*.yml'):
            tasks = yaml.safe_load(path.read_text())
            instrument(tasks, f.root)
            path.write_text(yaml.safe_dump(tasks, sort_keys=False))
        plugins = f.root / 'action_plugins'
        plugins.mkdir()
        shutil.copyfile(HERE / 'fixture_action.py', plugins / 'ntp_fixture.py')
        connections = f.root / 'connection_plugins'
        connections.mkdir()
        shutil.copyfile(HERE / 'fixture_connection.py', connections / 'ntp_unreachable.py')
        library = f.root / 'library'
        shutil.copytree(ROOT / 'library', library)
        variables = dict(VARS, cr_ntp_migrate_main=True,
                         cr_ntp_source_upstreams=SOURCE_UPSTREAMS,
                         cr_ntp_main_config_path=str(f.main), cr_ntp_dropin_path=str(f.dropin),
                         cr_ntp_state_dir=str(f.state), cr_ntp_chronyd_path=chronyd,
                         cr_ntp_phase='apply', cr_ntp_change_approved=VARS['cr_ntp_change_id'],
                         fixture_root=str(f.root), fixture_scenario=scenario,
                         ansible_python_interpreter=shutil.which('python3'),
                         ansible_date_time={'iso8601': '2026-09-18T00:00:00Z'})
        if scenario.get('source'):
            variables['cr_ntp_source_host'] = 'localhost'
        play = [dict(hosts='localhost', connection='local', gather_facts=False,
                     become=False, vars=variables, roles=['ntp_source'])]
        play_path = f.root / 'case.yml'
        play_path.write_text(yaml.safe_dump(play, sort_keys=False))
        config = f.root / 'ansible.cfg'
        config.write_text('[defaults]\nretry_files_enabled=False\nhost_key_checking=True\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ANSIBLE_', 'PYTHON'))}
        env.update(ANSIBLE_CONFIG=str(config), ANSIBLE_NOCOLOR='1', LANG='C.UTF-8', LC_ALL='C.UTF-8',
                   ANSIBLE_LIBRARY=str(library), ANSIBLE_ACTION_PLUGINS=str(plugins))
        env['ANSIBLE_CONNECTION_PLUGINS'] = str(connections)
        command = [executable, '-i', 'localhost,', str(play_path)]
        if scenario.get('check'):
            command.extend(['--check', '--diff'])
        completed = subprocess.run(command, env=env, cwd=f.root, capture_output=True,
                                   text=True, timeout=90)
        (f.root / 'stdout.log').write_text(completed.stdout)
        (f.root / 'stderr.log').write_text(completed.stderr)
        assert completed.returncode == (2 if scenario.get('failure') else 0), (
            f'Unexpected rc {completed.returncode}; inspect stdout.log/stderr.log')
        events_path = f.root / 'events.json'
        events = json.loads(events_path.read_text()) if events_path.exists() else {'restarts': 0, 'events': []}
        expected_restarts = scenario.get('restarts', 0 if scenario.get('check') else 1)
        assert events['restarts'] == expected_restarts, events
        if scenario.get('wait_fail'):
            assert events.get('polls') == 30, events
        if scenario.get('restart_fail'):
            assert 'FIXTURE_SERVICE_FAILURE' in completed.stdout
        if scenario.get('system_time'):
            assert 'Assert current system correction' in completed.stdout
            assert '0.5' in completed.stdout
        if scenario.get('source') and any(scenario.get(key) for key in (
                'address', 'extra_source', 'source_missing', 'source_no_selected', 'source_two_selected')):
            assert 'The migrated source must expose exactly the approved three upstream' in completed.stdout
        if scenario.get('check') or scenario.get('failure'):
            assert f.pair() == before, 'Check/rescue did not preserve invocation bytes and metadata'
        else:
            assert f.main.read_bytes() != OBSERVED
            assert f.run('plan')['changed'] is False
        if scenario.get('check'):
            assert not f.state.exists(), 'Ansible check mode created persistent state'
            assert 'before:' in completed.stdout and 'after:' in completed.stdout, 'Check mode did not expose configuration diff'
            assert not any(e.get('options', {}).get('argv', [])[:2] == ['chronyc', 'waitsync']
                           for e in events['events'])
        else:
            assert f.baseline.exists()
            if saved_baseline:
                assert file_state(f.baseline) == saved_baseline, 'Ansible flow rewrote immutable baseline'
        if scenario.get('rollback'):
            installed = f.pair()
            baseline = file_state(f.baseline)
            rollback = yaml.safe_load((ROOT / 'playbooks/cr-p1-ntp-01-01-rollback.yml').read_text())
            rollback[0]['become'] = False
            rollback[0]['vars'] = dict(variables, cr_ntp_rollback_host='localhost',
                                       cr_ntp_rollback_approved=VARS['cr_ntp_change_id'])
            if scenario.get('source'):
                rollback[0]['vars']['cr_ntp_source_upstreams'] = []
            for key in ('pre_tasks', 'tasks', 'post_tasks'):
                instrument(rollback[0].get(key, []), f.root)
            playbooks = f.root / 'playbooks'
            playbooks.mkdir()
            rollback_path = playbooks / 'rollback.yml'
            rollback_path.write_text(yaml.safe_dump(rollback, sort_keys=False))
            inventory = f.root / 'inventory.ini'
            inventory.write_text('[k8s_nodes]\n'
                                 'unrelated ansible_connection=ntp_unreachable\n'
                                 'localhost ansible_connection=local\n')
            rollback_command = [executable, '-i', str(inventory), str(rollback_path)]
            if scenario.get('rollback_check'):
                rollback_command.append('--check')
            rollback_result = subprocess.run(rollback_command, env=env, cwd=f.root,
                                             capture_output=True, text=True, timeout=90)
            (f.root / 'rollback.stdout.log').write_text(rollback_result.stdout)
            (f.root / 'rollback.stderr.log').write_text(rollback_result.stderr)
            assert rollback_result.returncode == 0, 'Targeted rollback failed; inspect rollback.stdout.log'
            assert 'UNREACHABLE' not in rollback_result.stdout, 'Non-target host attempted managed-host I/O'
            assert 'unrelated' in rollback_result.stdout
            assert f.pair() == (installed if scenario.get('rollback_check') else original)
            assert file_state(f.baseline) == baseline
        result = dict(name=name, passed=True, rc=completed.returncode, restarts=events['restarts'])
    except Exception:
        result = dict(name=name, passed=False, error=traceback.format_exc())
    (f.root / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    global MODULE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chronyd', required=True, type=Path)
    parser.add_argument('--ansible-playbook', default=shutil.which('ansible-playbook'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--suite', choices=['module', 'flow', 'all'], default='all')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('uid 0 is required to exercise unmodified ownership guards in temporary paths')
    assert hashlib.sha256(OBSERVED).hexdigest() == OBSERVED_SHA
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('fds_ntp_migration', ROOT / 'library/fds_ntp_migration.py')
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)
    selected = [case for case in module_cases() if args.suite != 'flow' and (not args.case or case[0] in args.case)]
    # Module scenarios are quick and sequential; uid observations may be
    # patched when this namespace cannot represent a non-root owner.
    results = [run_module_case(case, args.output, str(args.chronyd.resolve())) for case in selected]
    flows = [case for case in flow_cases() if args.suite != 'module' and (not args.case or case[0] in args.case)]
    if flows and not args.ansible_playbook:
        parser.error('--ansible-playbook is required for role integration')
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        results.extend(executor.map(lambda case: run_flow_case(case, args.output, str(args.chronyd.resolve()),
                                                             args.ansible_playbook), flows))
    report = dict(scope='LOCAL: real file transactions and chronyd -p parsing; service/chronyc observations mocked; ownership lstat mocked when uid namespace forbids chown; no host runtime acceptance',
                  parser=str(args.chronyd.resolve()), observed_sha256=OBSERVED_SHA,
                  results=results, passed=sum(x['passed'] for x in results), total=len(results))
    (args.output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    for item in results:
        print(('PASS' if item['passed'] else 'FAIL'), item['name'], item.get('error', ''))
    print(f"{report['passed']}/{report['total']} passed; {args.output / 'RESULTS.json'}")
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
