#!/usr/bin/env python3
"""Focused local tests for rollout ordering, receipts, finalization and locking.

External controller identity, Ansible and host observations are fixtures.
No production host, SSH, NTP service, packet or real-controller lock is used.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import selectors
import signal
import stat
import subprocess
import sys
import tarfile
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LOCK = load_module('ntp_workflow_lock_test', ROOT / 'tools/ntp-workflow-lock.py')
ROLLOUT = None
UPSTREAMS = ['162.159.200.1', '162.159.200.123', '194.58.200.20']  # Offline fixtures: TWO providers, never contacted.


def rejected(function, contains=None):
    try:
        function()
    except (OSError, ValueError) as exc:
        if contains:
            assert contains.lower() in str(exc).lower(), str(exc)
        return str(exc)
    raise AssertionError('Expected rejection')


def read_ready(process, expected='READY', timeout=10):
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout), 'Child did not reach readiness barrier'
        line = process.stdout.readline().strip()
        assert line == expected, (line, process.poll())
    finally:
        selector.close()


def lock_exclusive(directory):
    path = directory / 'shared/controller.lock'
    first = LOCK.acquire_lock(path=path)
    try:
        rejected(lambda: LOCK.acquire_lock(path=path), 'Another NTP controller')
    finally:
        os.close(first)
    inode = path.stat().st_ino
    next_fd = LOCK.acquire_lock(path=path)
    os.close(next_fd)
    assert path.stat().st_ino == inode, 'Lock file must not be removed on release'


def lock_inherited(directory):
    path = directory / 'controller.lock'
    first = LOCK.acquire_lock(path=path)
    inherited = LOCK.acquire_lock(inherited_fd=first, path=path)
    os.close(first)
    try:
        rejected(lambda: LOCK.acquire_lock(path=path), 'Another NTP controller')
    finally:
        os.close(inherited)
    os.close(LOCK.acquire_lock(path=path))


def lock_reject_other_descriptor(directory):
    first_path, second_path = directory / 'first.lock', directory / 'second.lock'
    first = LOCK.acquire_lock(path=first_path)
    second = LOCK.acquire_lock(path=second_path)
    try:
        rejected(lambda: LOCK.acquire_lock(inherited_fd=second, path=first_path), 'does not name')
        rejected(lambda: LOCK.acquire_lock(inherited_fd='not-an-fd', path=first_path), 'Invalid inherited')
    finally:
        os.close(first)
        os.close(second)


def lock_path_is_not_environment_controlled(directory):
    with patch.dict(os.environ, HOME=str(directory / 'home-one')):
        first = LOCK.default_lock_path()
    with patch.dict(os.environ, HOME=str(directory / 'home-two'), CR_EVIDENCE_DIR=str(directory / 'other-evidence')):
        second = LOCK.default_lock_path()
    assert first == second


def lock_unsafe(directory, kind):
    path = directory / 'controller.lock'
    fd = LOCK.acquire_lock(path=path)
    os.close(fd)
    if kind == 'symlink':
        target = directory / 'original.lock'
        path.rename(target)
        path.symlink_to(target)
    elif kind == 'hardlink':
        os.link(path, directory / 'alias.lock')
    elif kind == 'mode':
        path.chmod(0o666)
    elif kind == 'parent':
        directory.chmod(0o777)
    rejected(lambda: LOCK.acquire_lock(path=path))


def lock_cross_process_lifetime(directory):
    path = directory / 'controller.lock'
    fd = LOCK.acquire_lock(path=path)
    program = '''import importlib.util,os,sys
s=importlib.util.spec_from_file_location('lock',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
d=m.acquire_lock(inherited_fd=int(sys.argv[2]),path=sys.argv[3]);print('READY',flush=True)
sys.stdin.readline();os.close(d)
'''
    child = subprocess.Popen([sys.executable, '-c', program, str(ROOT/'tools/ntp-workflow-lock.py'), str(fd), str(path)],
                             pass_fds=(fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        read_ready(child)
        os.close(fd)
        fd = None
        rejected(lambda: LOCK.acquire_lock(path=path), 'Another NTP controller')
        stdout, stderr = child.communicate('\n', timeout=10)
        assert child.returncode == 0, stderr
        os.close(LOCK.acquire_lock(path=path))
    finally:
        if fd is not None:
            os.close(fd)
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)


def lock_cases():
    yield 'lock_exclusive_and_released', lock_exclusive
    yield 'lock_inherited_fd_retains_ownership', lock_inherited
    yield 'lock_wrong_or_invalid_fd_rejected', lock_reject_other_descriptor
    yield 'lock_home_and_evidence_cannot_split_namespace', lock_path_is_not_environment_controlled
    for kind in ('symlink', 'hardlink', 'mode', 'parent'):
        yield 'lock_' + kind + '_rejected', lambda d, kind=kind: lock_unsafe(d, kind)
    yield 'lock_lasts_until_last_inherited_process_exits', lock_cross_process_lifetime


def git(repo, *arguments):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    result = subprocess.run(['git', '-C', str(repo), *arguments], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class RolloutFixture:
    def __init__(self, directory, scenario):
        self.directory, self.scenario = directory, scenario
        self.repo = directory / 'repo'
        self.repo.mkdir()
        shutil.copytree(ROOT / 'module_utils', self.repo / 'module_utils')
        self.upstreams = scenario.get('upstreams', UPSTREAMS)
        shutil.copyfile(ROOT / '.gitignore', self.repo / '.gitignore')
        (self.repo / 'tools').mkdir()
        for name in ('render-ntp-egress.py', 'ntp-workflow-lock.py', 'ntp-rollout.py'):
            shutil.copyfile(ROOT / 'tools' / name, self.repo / 'tools' / name)
        self.lock_path = directory / 'controller.lock'
        helper_path = self.repo / 'tools/ntp-workflow-lock.py'
        helper = helper_path.read_text()
        locator = 'return Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".local/state/fds-ntp/CR-P1-NTP-01-01.lock"'
        assert helper.count(locator) == 1
        helper_path.write_text(helper.replace(locator, 'return Path(' + repr(str(self.lock_path)) + ')'))
        (self.repo / 'README').write_text('Local orchestration fixture; no hosts contacted.\n')
        git(self.repo, 'init', '-q')
        git(self.repo, 'add', '.')
        git(self.repo, '-c', 'user.name=Local Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
        self.head = git(self.repo, 'rev-parse', 'HEAD')
        self.foreign = directory / 'foreign-clean-repo'
        if scenario.get('git_environment'):
            shutil.copytree(self.repo, self.foreign)
        self.runtime_input = directory / 'runtime-input.json'
        data = dict(reviewed_source_sha=self.head, public_upstreams=self.upstreams,
                    source_policy_ref='fixture:source-policy', network_policy_ref='fixture:network-policy',
                    recovery_ref='fixture:recovery')
        if scenario.get('bad_input') == 'upstreams':
            data['public_upstreams'] = []
        if 'invalid_upstreams' in scenario:
            data['public_upstreams'] = scenario['invalid_upstreams']
        if scenario.get('bad_input') == 'head':
            data['reviewed_source_sha'] = 'f' * 40
        self.runtime_input.write_text(json.dumps(data))
        self.runtime_input.chmod(0o600)
        self.key = directory / 'fixture-key'
        self.key.write_text('Fixture only; not an SSH key\n')
        self.key.chmod(0o600)
        self.parent = directory / 'evidence'
        self.parent.mkdir(mode=0o700)
        self.calls = []
        self.instance = None

    def inventory(self):
        hosts = dict(ROLLOUT.HOSTS)
        if self.scenario.get('bad_inventory') == 'missing':
            del hosts['k8s-worker03']
        values = {host: dict(ansible_host=address, cr_ntp_source_upstreams=self.upstreams,
                             cr_ntp_migrate_main=True) for host, address in hosts.items()}
        if self.scenario.get('bad_inventory') == 'upstreams':
            values['k8s-worker01']['cr_ntp_source_upstreams'] = UPSTREAMS[:2]
        if self.scenario.get('bad_inventory') == 'address':
            values['k8s-worker01']['ansible_host'] = '192.0.2.99'
        return {'k8s_nodes': {'hosts': list(hosts)}, '_meta': {'hostvars': values}}

    def receipts(self, rollout, gate):
        for host, address in ROLLOUT.HOSTS.items():
            targets = self.upstreams if gate == 'diagnose' and host == ROLLOUT.SOURCE else (
                [ROLLOUT.HOSTS[ROLLOUT.SOURCE]] if gate == 'pathcheck' and host != ROLLOUT.SOURCE else [])
            value = dict(schema_version=1, gate=gate, run_id=rollout.summary['run_id'],
                         source_head=self.head, input_sha256=rollout.input_hash,
                         inventory_hostname=host, ansible_host=address, gate_pass=True,
                         probes=[dict(target_address=target, gate_pass=True, sample_accepted=True,
                                      offset_seconds=0.0001, returncode=0, target_port=123, outer_timeout=False,
                                      stdout='', stderr='') for target in targets],
                         observations={'checks': {name: True for name in ('host_identity', 'chrony_version',
                                       'service_contract', 'no_competing_service', 'effective_parse')},
                                       'service_properties': {'LoadState': 'loaded', 'ActiveState': 'active', 'MainPID': '123'},
                                       'expanded_exec_argv': ['/usr/sbin/chronyd', '-F', '2'],
                                       'effective_config': {'returncode': 0, 'stdout': '', 'stderr': ''}}, errors=[])
            if gate == 'diagnose': value['observations']['checks']['migration_plan'] = True
            elif host == ROLLOUT.SOURCE: value['observations']['checks']['source_runtime_acl_listener'] = True
            selected = self.scenario.get('gate_host', 'k8s-worker01')
            corrupt = self.scenario.get('receipt') if gate == self.scenario.get('gate', 'pathcheck') and host == selected else None
            if corrupt == 'missing':
                continue
            if corrupt == 'stale_run': value['run_id'] = 'old-run'
            if corrupt == 'wrong_head': value['source_head'] = 'f' * 40
            if corrupt == 'wrong_input': value['input_sha256'] = '0' * 64
            if corrupt == 'wrong_host': value['inventory_hostname'] = 'k8s-worker03'
            if corrupt == 'wrong_ip': value['ansible_host'] = '192.0.2.99'
            if corrupt == 'schema': value['schema_version'] = 99
            if corrupt == 'errors': value['errors'] = ['probe failed']
            if corrupt == 'observations': value['observations'] = {}
            if corrupt == 'failed': value['gate_pass'] = False
            if corrupt == 'partial_probes': value['probes'] = []
            if corrupt == 'wrong_target': value['probes'][0]['target_address'] = '192.0.2.123'
            if corrupt == 'sample_rejected': value['probes'][0]['sample_accepted'] = False
            if corrupt == 'bad_offset': value['probes'][0]['offset_seconds'] = 0.5
            if corrupt == 'nan_offset': value['probes'][0]['offset_seconds'] = 'NaN'
            if corrupt == 'probe_rc': value['probes'][0]['returncode'] = 1
            if corrupt == 'probe_timeout': value['probes'][0]['outer_timeout'] = True
            if corrupt == 'typed_check_missing': del value['observations']['checks']['host_identity']
            if corrupt == 'typed_check_false': value['observations']['checks']['service_contract'] = False
            path = rollout.root / 'gates' / (gate + '--' + host + '.json')
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            if corrupt == 'unexpected_host':
                (path.parent / (gate + '--unreviewed.json')).write_text(json.dumps(value))
            if corrupt == 'duplicate_probe':
                value['probes'] += value['probes']
                path.write_text(json.dumps(value))

    def build(self):
        fixture = self
        class InstrumentedRollout(ROLLOUT.Rollout):
            def run_command(self, phase, argv, timeout):
                fixture.calls.append(dict(phase=phase, argv=[str(item) for item in argv]))
                stdout = ''
                if phase == 'identity-host': stdout = 'ansible01\n'
                elif phase == 'identity-user': stdout = 'server01_ansible\n'
                elif phase == 'locale': stdout = 'UTF-8\n'
                elif phase.startswith('engine-'): stdout = 'ansible [core 2.16.19]\n'
                elif phase == 'inventory': stdout = json.dumps(fixture.inventory())
                elif phase in ('diagnose', 'pathcheck'): fixture.receipts(self, phase)
                if phase in ('precheck', 'source', 'clients', 'verify'):
                    (self.root / 'wrapper/SOURCE_HEAD').write_text(fixture.head + '\n')
                    (self.root / 'wrapper' / (phase + '.log')).write_text('LOCAL FIXTURE ' + phase + '\n')
                if phase == 'finalize':
                    wrapper = self.root / 'wrapper'
                    (wrapper / 'SHA256SUMS').write_text(''.join(
                        hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
                        for path in sorted(wrapper.iterdir()) if path.is_file() and path.name != 'SHA256SUMS'))
                if phase == fixture.scenario.get('exception_phase'):
                    raise RuntimeError('INJECTED_EXCEPTION_' + phase)
                if phase == fixture.scenario.get('sleep_phase'):
                    program = '''import json,os,pathlib,signal,subprocess,sys
child=subprocess.Popen([sys.executable,'-c','import signal;signal.pause()'])
pathlib.Path(sys.argv[1]).write_text(json.dumps({'leader':os.getpid(),'descendant':child.pid}))
print('CHILD_GROUP_READY',flush=True)
signal.pause()
'''
                    return super().run_command(phase, [sys.executable, '-c', program,
                                               str(fixture.directory/'child-ready.json')], timeout)
                if phase == fixture.scenario.get('input_mutation_phase'):
                    path = self.root / 'ANSIBLE_VARS.json'
                    path.chmod(0o600)
                    path.write_text('{"mutated": true}\n')
                if phase == fixture.scenario.get('dirty_phase'):
                    with (fixture.repo / 'README').open('a') as stream:
                        stream.write('Unreviewed source change\n')
                if phase == fixture.scenario.get('head_change_phase'):
                    with (fixture.repo / 'README').open('a') as stream:
                        stream.write('Later commit\n')
                    git(fixture.repo, 'add', 'README')
                    git(fixture.repo, '-c', 'user.name=Local Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Later')
                rc = 2 if phase == fixture.scenario.get('fail_phase') else 0
                program = 'import sys;sys.stdout.write(sys.argv[1]);sys.exit(int(sys.argv[2]))'
                return super().run_command(phase, [sys.executable, '-c', program, stdout, str(rc)], timeout)

        args = argparse.Namespace(runtime_input=self.runtime_input, apply=not self.scenario.get('diagnose_only'),
                                  evidence_parent=self.parent)
        self.instance = InstrumentedRollout(args, repo_root=self.repo)
        if self.scenario.get('initial_dirty'):
            (self.repo / 'README').write_text('dirty\n')
        return self.instance

    @contextlib.contextmanager
    def environment(self):
        clean = {key: value for key, value in os.environ.items()
                 if not key.startswith(('ANSIBLE_', 'CR_', 'GIT_'))}
        clean['ANSIBLE_PRIVATE_KEY_FILE'] = str(self.key)
        if not self.scenario.get('unapproved'):
            clean['CR_CHANGE_APPROVED'] = ROLLOUT.CHANGE_ID
        if self.scenario.get('git_environment'):
            clean.update(GIT_DIR=str(self.foreign/'.git'), GIT_WORK_TREE=str(self.foreign))
        with patch.dict(os.environ, clean, clear=True):
            yield

    def check_evidence(self, rollout):
        assert (rollout.root / 'RESULT.json').exists()
        archive = rollout.root.with_suffix('.tar.gz')
        assert archive.exists(), 'No archive retained'
        expected = Path(str(archive) + '.sha256').read_text().split()[0]
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
        manifest = rollout.root / 'SHA256SUMS'
        manifested = set()
        for line in manifest.read_text().splitlines():
            digest, name = line.split('  ', 1)
            manifested.add(name)
            assert hashlib.sha256((rollout.root / name).read_bytes()).hexdigest() == digest
        expected_files = {str(path.relative_to(rollout.root)) for path in rollout.root.rglob('*')
                          if path.is_file() and path != manifest}
        assert manifested == expected_files, 'Recursive checksum omits retained evidence files'
        with tarfile.open(archive, 'r:gz') as stream:
            assert rollout.root.name + '/RESULT.json' in stream.getnames()
        os.close(LOCK.acquire_lock(path=self.lock_path))


def orchestration_case(directory, scenario):
    fixture = RolloutFixture(directory, scenario)
    with fixture.environment():
        rollout = fixture.build()
        rc = rollout.run()
    phases = [item['phase'] for item in fixture.calls]
    (directory / 'fixture-calls.json').write_text(json.dumps(fixture.calls, indent=2) + '\n')
    fixture.check_evidence(rollout)
    success = not any(scenario.get(key) for key in ('bad_input', 'bad_inventory', 'receipt', 'fail_phase', 'invalid_upstreams',
                    'exception_phase', 'input_mutation_phase', 'dirty_phase', 'head_change_phase', 'initial_dirty', 'unapproved'))
    assert (rc == 0) == success, (rc, rollout.summary)
    attempted = [p for p in phases if p in ('precheck', 'diagnose', 'source', 'pathcheck', 'clients', 'verify')]
    if success:
        assert attempted == (['precheck', 'diagnose'] if scenario.get('diagnose_only') else
                             ['precheck', 'diagnose', 'source', 'pathcheck', 'clients', 'verify']), attempted
        assert rollout.summary['source_applied'] is (not scenario.get('diagnose_only', False))
        assert rollout.summary['clients_started'] is (not scenario.get('diagnose_only', False))
    else:
        assert rollout.summary.get('error') or rollout.summary.get('wrapper_finalize') == 'FAILED_RETAINED'
        if 'invalid_upstreams' in scenario or scenario.get('bad_input') or scenario.get('bad_inventory') or scenario.get('initial_dirty') or scenario.get('unapproved'):
            assert not attempted, attempted
            if scenario.get('initial_dirty') or scenario.get('bad_input') == 'head':
                assert 'HEAD/tree/clean' in rollout.summary['error']
        elif scenario.get('receipt'):
            gate = scenario.get('gate', 'pathcheck')
            assert attempted[-1] == gate, attempted
            assert 'clients' not in attempted
        elif scenario.get('fail_phase') in attempted:
            assert attempted[-1] == scenario['fail_phase'], attempted
            if scenario['fail_phase'] == 'source':
                assert rollout.summary['source_phase_started'] is True
                assert rollout.summary['source_applied'] is None, 'Partial source phase must remain unknown'
        elif scenario.get('input_mutation_phase'):
            assert (phases[-1] if scenario['input_mutation_phase'] == 'finalize' else attempted[-1]) == scenario['input_mutation_phase'], attempted
        elif scenario.get('dirty_phase') or scenario.get('head_change_phase'):
            assert attempted[-1] == (scenario.get('dirty_phase') or scenario['head_change_phase']), attempted
    if rollout.controller_ready and rollout.source_bound and not any(scenario.get(key) for key in ('dirty_phase', 'head_change_phase', 'input_mutation_phase')):
        assert phases[-1] == 'finalize', phases
    return dict(rc=rc, phases=phases, summary=rollout.summary,
                archive=str(rollout.root.with_suffix('.tar.gz')))


def orchestration_cases():
    yield 'diagnose_only_never_applies', {'diagnose_only': True}
    yield 'full_gated_rollout_order', {}
    yield 'full_two_source_gated_rollout_order', {'upstreams': UPSTREAMS[::2]}
    for name, values in [('nist_boulder', ['132.163.96.1', UPSTREAMS[0]]),
                         ('nist_maryland', ['129.6.15.28', UPSTREAMS[0]]),
                         ('unknown_public', ['8.8.8.8', UPSTREAMS[0]]),
                         ('one', UPSTREAMS[:1]), ('four', UPSTREAMS + [UPSTREAMS[0]]),
                         ('duplicate', [UPSTREAMS[0], UPSTREAMS[0]]),
                         ('dns', ['ntp.example.org', UPSTREAMS[0]]),
                         ('wrong_type', '162.159.200.1')]:
        yield 'input_' + name + '_rejected_before_host_phases', {'invalid_upstreams': values}
    yield 'missing_upstreams_prevents_apply', {'bad_input': 'upstreams'}
    yield 'wrong_reviewed_head_prevents_apply', {'bad_input': 'head'}
    yield 'dirty_checkout_prevents_apply', {'initial_dirty': True}
    yield 'apply_requires_existing_approval', {'unapproved': True}
    yield 'git_environment_cannot_redirect_source', {'git_environment': True}
    yield 'dirty_real_checkout_rejected_despite_clean_foreign_git', {'git_environment': True, 'initial_dirty': True}
    for kind in ('missing', 'address', 'upstreams'):
        yield 'inventory_' + kind + '_prevents_apply', {'bad_inventory': kind}
    for phase in ('precheck', 'diagnose', 'source', 'pathcheck', 'clients', 'verify', 'finalize'):
        yield phase + '_failure_stops_and_retains_evidence', {'fail_phase': phase}
    for host in ('k8s-control02', 'k8s-control03', 'k8s-worker01', 'k8s-worker02', 'k8s-worker03'):
        yield 'pathcheck_failed_' + host, {'receipt': 'failed', 'gate_host': host}
    for corrupt in ('missing', 'stale_run', 'wrong_head', 'wrong_input', 'wrong_host', 'wrong_ip', 'schema',
                    'errors', 'observations', 'partial_probes', 'wrong_target', 'sample_rejected',
                    'bad_offset', 'nan_offset', 'probe_rc', 'probe_timeout', 'unexpected_host', 'duplicate_probe',
                    'typed_check_missing', 'typed_check_false'):
        yield 'pathcheck_receipt_' + corrupt, {'receipt': corrupt}
    yield 'diagnose_partial_public_responses_prevents_source', {'receipt': 'partial_probes', 'gate': 'diagnose', 'gate_host': 'k8s-control01'}
    yield 'bound_input_mutation_stops_before_clients', {'input_mutation_phase': 'pathcheck'}
    yield 'bound_input_mutation_during_finalize_fails', {'input_mutation_phase': 'finalize'}
    yield 'dirty_during_source_stops_before_clients', {'dirty_phase': 'source'}
    yield 'head_change_during_source_preserves_original_binding', {'head_change_phase': 'source'}
    yield 'unexpected_exception_finalizes', {'exception_phase': 'diagnose'}


def package_failure_releases_lock(directory):
    fixture = RolloutFixture(directory, {'diagnose_only': True})
    with fixture.environment():
        rollout = fixture.build()
        with patch.object(rollout, 'package', side_effect=OSError('INJECTED_ARCHIVE_WRITE_FAILURE')):
            try:
                rollout.run()
            except OSError as exc:
                assert 'INJECTED_ARCHIVE' in str(exc)
            else:
                raise AssertionError('Archive failure did not propagate')
    assert rollout.root.exists() and list((rollout.root/'controller').glob('*.log'))
    assert rollout.lock_fd is None, 'Archive failure leaked workflow lock descriptor'
    os.close(LOCK.acquire_lock(path=fixture.lock_path))
    return {'raw_evidence_retained': str(rollout.root), 'archive_expected': False}


def stopped(pid):
    path = Path('/proc') / str(pid) / 'stat'
    return not path.exists() or path.read_text().rsplit(')', 1)[1].strip().split()[0] == 'Z'


def signal_worker(directory):
    global ROLLOUT
    ROLLOUT = load_module('ntp_rollout_signal_test', ROOT/'tools/ntp-rollout.py')
    fixture = RolloutFixture(directory, {'sleep_phase': 'precheck'})
    with fixture.environment():
        rollout = fixture.build()
        argv = [str(ROOT/'tools/ntp-rollout.py'), '--runtime-input', str(fixture.runtime_input),
                '--apply', '--evidence-parent', str(fixture.parent)]
        with patch.object(ROLLOUT, 'Rollout', lambda args: rollout), patch.object(sys, 'argv', argv):
            code = ROLLOUT.main()  # The production CLI installs the real signal handlers.
    (directory/'worker-result.json').write_text(json.dumps({'rc': code, 'root': str(rollout.root),
                                                           'summary': rollout.summary}) + '\n')
    return code


def signal_case(directory, number):
    with (directory/'worker.stdout.log').open('w') as stdout, (directory/'worker.stderr.log').open('w') as stderr:
        worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--signal-worker', str(directory)],
                                  stdout=stdout, stderr=stderr, start_new_session=True)
        ready = directory/'child-ready.json'
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and worker.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert ready.exists(), 'Signal fixture did not reach child-process readiness'
            processes = json.loads(ready.read_text())
            os.kill(worker.pid, number)
            worker.wait(timeout=15)
            assert worker.returncode != 0
            assert all(stopped(pid) for pid in processes.values()), processes
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
    result = json.loads((directory/'worker-result.json').read_text())
    assert result['rc'] != 0 and 'Interrupted by signal' in result['summary']['error']
    root = Path(result['root'])
    records = json.loads((root/'COMMANDS.json').read_text())
    assert any(row['phase'] == 'precheck' and row['interrupted'] is True for row in records)
    assert records[-1]['phase'] == 'finalize'
    RolloutFixture.check_evidence(argparse.Namespace(lock_path=directory/'controller.lock'),
                                 argparse.Namespace(root=root))
    return dict(signal=number, processes=processes, summary=result['summary'])


def command_timeout_case(directory):
    fixture = RolloutFixture(directory, {})
    with fixture.environment():
        rollout = fixture.build()
        rollout.create_evidence()
        rollout.lock_fd = LOCK.acquire_lock(path=fixture.lock_path)
        ready = directory/'timeout-ready.json'
        program = '''import json,os,pathlib,signal,subprocess,sys
child=subprocess.Popen([sys.executable,'-c','import signal;signal.pause()'])
pathlib.Path(sys.argv[1]).write_text(json.dumps({'leader':os.getpid(),'descendant':child.pid}))
print('READY',flush=True);signal.pause()
'''
        try:
            record = ROLLOUT.Rollout.run_command(rollout, 'timeout-child', [sys.executable, '-c', program, str(ready)], 1)
            assert record['timed_out'] is True and record['returncode'] != 0
            processes = json.loads(ready.read_text())
            assert all(stopped(pid) for pid in processes.values())
            assert 'READY' in record['stdout']
        finally:
            os.close(rollout.lock_fd)
            rollout.lock_fd = None
    os.close(LOCK.acquire_lock(path=fixture.lock_path))
    return dict(record=record, processes=processes)


def run_case(name, body, output):
    directory = output / name
    directory.mkdir(parents=True)
    try:
        details = body(directory)
        result = dict(name=name, passed=True, details=details)
    except Exception:
        result = dict(name=name, passed=False, error=traceback.format_exc())
    (directory / 'RESULT.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
    return result


def main():
    global ROLLOUT
    if len(sys.argv) == 3 and sys.argv[1] == '--signal-worker':
        return signal_worker(Path(sys.argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--suite', choices=['lock', 'orchestration', 'all'], default='all')
    parser.add_argument('--case', action='append', default=[])
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = list(lock_cases()) if args.suite != 'orchestration' else []
    if args.suite != 'lock':
        ROLLOUT = load_module('ntp_rollout_test', ROOT / 'tools/ntp-rollout.py')
        cases.extend((name, lambda directory, scenario=scenario: orchestration_case(directory, scenario))
                     for name, scenario in orchestration_cases())
        cases.extend([('package_failure_retains_logs_and_releases_lock', package_failure_releases_lock),
                      ('sigint_stops_child_group_finalizes_and_unlocks', lambda d: signal_case(d, signal.SIGINT)),
                      ('sigterm_stops_child_group_finalizes_and_unlocks', lambda d: signal_case(d, signal.SIGTERM)),
                      ('timeout_stops_child_group_and_preserves_output', command_timeout_case)])
    selected = [(name, body) for name, body in cases if not args.case or name in args.case]
    if not selected:
        parser.error('No matching cases')
    results = [run_case(name, body, args.output) for name, body in selected]
    report = dict(scope=__doc__, results=results, passed=sum(item['passed'] for item in results), total=len(results))
    (args.output / 'RESULTS.json').write_text(json.dumps(report, indent=2) + '\n')
    for item in results:
        print('PASS' if item['passed'] else 'FAIL', item['name'], item.get('error', ''))
    print(f"{report['passed']}/{report['total']} PASS")
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
