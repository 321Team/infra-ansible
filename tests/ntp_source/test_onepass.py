#!/usr/bin/env python3
"""Local failure-boundary tests for the one-command NTP controller.

Remote observations, Ansible execution and controller identity are fixtures.
These tests do not contact hosts, alter firewall/chrony or use real SSH keys.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import traceback
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = None


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(repo, *arguments):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('GIT_')}
    result = subprocess.run(['git', '-C', str(repo), *arguments],
                            env=environment, capture_output=True, text=True,
                            timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def expect_failure(function, contains=None):
    try:
        function()
    except (Exception, KeyboardInterrupt) as exc:
        if contains:
            assert contains.lower() in str(exc).lower(), str(exc)
        return str(exc)
    raise AssertionError('Expected the unsafe continuation to be rejected')


class PipelineFixture:
    """Replace only external actions; retain production stage decisions."""

    def __init__(self, directory, apply=True, remote_failure=None,
                 uncertain=False, child_failure=False, post_failure=False,
                 sample_failure=False, drift_before=None):
        self.directory = directory
        self.events = []
        self.remote_failure = remote_failure
        self.uncertain = uncertain
        self.child_failure = child_failure
        self.post_failure = post_failure
        self.sample_failure = sample_failure
        self.drift_before = drift_before
        self.guard_count = 0
        self.wrapper = directory / 'wrapper'
        self.wrapper.mkdir()
        self.rollout = directory / 'rollout'
        self.rollout.mkdir()
        self.evidence = directory / 'evidence'
        self.evidence.mkdir(mode=0o700)
        self.input_path = directory / 'input.json'
        self.input_path.write_text('{}\n')
        self.input_path.chmod(0o600)
        args = argparse.Namespace(rollout_repo=self.rollout, input=self.input_path,
                                  evidence_parent=self.evidence, apply=apply)
        self.controller = CONTROLLER.OnePass(args, repo_root=self.wrapper)
        self.controller.create_evidence()

    def remote(self, action, host):
        self.events.append((action, host))
        if (action, host) == self.remote_failure:
            if self.uncertain:
                raise CONTROLLER.StateUncertain('Fixture: remote response lost')
            return {'status': 'STOP', 'action': action, 'host': host,
                    'errors': ['Fixture: confirmed command failure']}
        return {'status': 'OK', 'action': action, 'host': host, 'errors': []}

    def child(self):
        self.events.append(('rollout', None))
        if self.child_failure:
            raise ValueError('Fixture: rollout returned partial success')

    def post_gates(self):
        self.events.append(('post_gates', None))
        if self.post_failure:
            raise ValueError('Fixture: final network gate failed')

    def samples(self):
        self.events.append(('samples', None))
        if self.sample_failure:
            raise ValueError('Fixture: later tracking sample failed')

    def assert_sources(self):
        self.guard_count += 1
        if self.drift_before is not None and self.guard_count >= self.drift_before:
            raise ValueError('Fixture: checkout drift detected')

    @contextlib.contextmanager
    def external_fixtures(self):
        with contextlib.ExitStack() as stack:
            for method, replacement in (
                ('remote', self.remote),
                ('run_child', self.child),
                ('post_egress_gates', self.post_gates),
                ('sample_all', self.samples),
                ('write_preparation', lambda: self.events.append(('preparation', None))),
                ('assert_sources', self.assert_sources),
                ('verify_input', lambda: None),
            ):
                stack.enter_context(patch.object(self.controller, method, replacement))
            yield

    def execute(self, fails=False):
        with self.external_fixtures():
            error = expect_failure(self.controller.execute_pipeline) if fails else None
            if not fails:
                self.controller.execute_pipeline()
        return {'events': self.events, 'error': error,
                'summary': self.controller.summary}


def snapshot_failure(directory):
    hosts = list(CONTROLLER.HOSTS)
    fixture = PipelineFixture(directory, remote_failure=('snapshot', hosts[2]))
    details = fixture.execute(fails=True)
    assert all(action == 'snapshot' for action, host in fixture.events), fixture.events
    assert ('snapshot', hosts[2]) in fixture.events
    return details


def dry_run_has_no_mutation(directory):
    fixture = PipelineFixture(directory, apply=False)
    details = fixture.execute()
    snapshots = {host for action, host in fixture.events if action == 'snapshot'}
    assert snapshots == set(CONTROLLER.HOSTS), fixture.events
    assert not any(action in {'ingress', 'egress', 'rollout', 'rollback_ingress',
                              'rollback_egress', 'post_gates', 'samples'}
                   for action, host in fixture.events), fixture.events
    return details


def ingress_failure(directory, uncertain):
    fixture = PipelineFixture(directory, remote_failure=('ingress', CONTROLLER.SOURCE),
                              uncertain=uncertain)
    details = fixture.execute(fails=True)
    assert ('ingress', CONTROLLER.SOURCE) in fixture.events, fixture.events
    assert ('rollout', None) not in fixture.events
    assert not any(action == 'egress' for action, host in fixture.events)
    rollback = [('rollback_ingress', CONTROLLER.SOURCE)]
    observed = [event for event in fixture.events if event[0].startswith('rollback_')]
    assert observed == ([] if uncertain else rollback), fixture.events
    return details


def partial_rollout_preserves_shared_rules(directory):
    fixture = PipelineFixture(directory, child_failure=True)
    details = fixture.execute(fails=True)
    assert ('rollout', None) in fixture.events
    assert ('ingress', CONTROLLER.SOURCE) in fixture.events
    assert not any(action == 'egress' or action.startswith('rollback_')
                   for action, host in fixture.events), fixture.events
    return details


def egress_failure(directory, uncertain):
    hosts = list(CONTROLLER.HOSTS)
    fixture = PipelineFixture(directory, remote_failure=('egress', hosts[2]),
                              uncertain=uncertain)
    details = fixture.execute(fails=True)
    assert [host for action, host in fixture.events if action == 'egress'] == hosts[:3]
    observed = [event for event in fixture.events if event[0].startswith('rollback_')]
    assert observed == ([] if uncertain else [('rollback_egress', hosts[2])]), fixture.events
    assert not any(action in {'post_gates', 'samples'} for action, host in fixture.events)
    return details


def final_gate_failure_preserves_success(directory, which):
    fixture = PipelineFixture(directory, post_failure=which == 'post',
                              sample_failure=which == 'sample')
    details = fixture.execute(fails=True)
    assert {host for action, host in fixture.events if action == 'egress'} == set(CONTROLLER.HOSTS)
    assert not any(action.startswith('rollback_') for action, host in fixture.events)
    assert (('samples', None) in fixture.events) == (which == 'sample')
    return details


def success_keeps_final_acceptance_separate(directory):
    fixture = PipelineFixture(directory)
    details = fixture.execute()
    events = fixture.events
    assert [host for action, host in events if action == 'egress'] == list(CONTROLLER.HOSTS)
    assert events.index(('rollout', None)) < min(i for i, event in enumerate(events) if event[0] == 'egress')
    assert ('post_gates', None) in events and ('samples', None) in events
    assert events.index(('post_gates', None)) < events.index(('samples', None))
    assert not any(action.startswith('rollback_') for action, host in events)
    # A successful controller run cannot replace reboot/sync-loss acceptance.
    assert fixture.controller.summary.get('runtime_acceptance') != 'PASS'
    return details


def drift_stops_next_mutation(directory):
    fixture = PipelineFixture(directory, drift_before=1)
    details = fixture.execute(fails=True)
    assert 'drift' in details['error'], details
    assert not any(action in {'ingress', 'rollout', 'egress'}
                   for action, host in fixture.events), fixture.events
    return details


class SourceFixture:
    """Real local Git checkouts; approved constants point only at local fixtures."""

    def __init__(self, directory):
        self.directory = directory
        self.wrapper = directory / 'wrapper'
        self.rollout = directory / 'rollout'
        for repo, marker in ((self.wrapper, 'wrapper'), (self.rollout, 'approved rollout')):
            (repo / 'tools').mkdir(parents=True)
            (repo / 'README').write_text(marker + '\n')
            filename = 'ntp-onepass.py' if repo == self.wrapper else 'ntp-rollout.py'
            shutil.copyfile(ROOT / 'tools' / filename, repo / 'tools' / filename)
            if repo == self.wrapper:
                shutil.copyfile(ROOT / 'tools/ntp-onepass-remote.py', repo / 'tools/ntp-onepass-remote.py')
            git(repo, 'init', '-q')
            git(repo, 'add', '.')
            git(repo, '-c', 'user.name=Local Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'Offline fixture')
        self.wrapper_head = git(self.wrapper, 'rev-parse', 'HEAD')
        self.rollout_head = git(self.rollout, 'rev-parse', 'HEAD')
        self.rollout_tree = git(self.rollout, 'rev-parse', 'HEAD^{tree}')
        self.evidence = directory / 'evidence'
        self.evidence.mkdir(mode=0o700)
        self.input_path = directory / 'input.json'
        self.value = {'reviewed_wrapper_sha': self.wrapper_head,
                      'reviewed_source_sha': self.rollout_head,
                      'public_upstreams': CONTROLLER.UPSTREAMS,
                      'source_policy_ref': CONTROLLER.SOURCE_REF,
                      'network_policy_ref': 'fixture:verified-network-transition-record',
                      'recovery_ref': 'fixture:verified-recovery-record'}
        CONTROLLER.write_json(self.input_path, self.value)
        self.args = argparse.Namespace(rollout_repo=self.rollout, input=self.input_path,
                                       evidence_parent=self.evidence, apply=True)
        self.controller = CONTROLLER.OnePass(self.args, repo_root=self.wrapper)
        self.controller.create_evidence()

    @contextlib.contextmanager
    def binding(self):
        with patch.object(CONTROLLER, 'ROLLOUT_SHA', self.rollout_head), \
                patch.object(CONTROLLER, 'ROLLOUT_TREE', self.rollout_tree), \
                patch.object(CONTROLLER, '__file__', str(self.wrapper / 'tools/ntp-onepass.py')):
            yield


def git_binding(directory, scenario):
    fixture = SourceFixture(directory)
    controller = fixture.controller
    with fixture.binding():
        controller.load_input()
        initial = controller.assert_sources()
        assert initial['wrapper']['head'] != initial['rollout']['head']
        if scenario in ('wrapper_tracked', 'rollout_tracked'):
            repo = fixture.wrapper if scenario.startswith('wrapper') else fixture.rollout
            (repo / 'README').write_text('changed after binding\n')
            error = expect_failure(controller.mutation_guard, 'clean state')
        elif scenario in ('wrapper_untracked', 'rollout_untracked'):
            repo = fixture.wrapper if scenario.startswith('wrapper') else fixture.rollout
            (repo / 'unreviewed.py').write_text('raise SystemExit(99)\n')
            error = expect_failure(controller.mutation_guard, 'clean state')
        elif scenario == 'wrong_wrapper_sha':
            controller.input['reviewed_wrapper_sha'] = fixture.rollout_head
            error = expect_failure(controller.assert_sources, 'wrapper')
        elif scenario == 'substituted_rollout':
            controller.rollout_repo = fixture.wrapper
            error = expect_failure(controller.assert_sources, 'rollout')
        elif scenario == 'bound_input_tampered':
            altered = dict(fixture.value, recovery_ref='fixture:unreviewed-new-record')
            CONTROLLER.write_json(controller.root / 'ONEPASS_INPUT.json', altered)
            error = expect_failure(controller.mutation_guard, 'input changed')
        elif scenario == 'wrong_script_path':
            with patch.object(CONTROLLER, '__file__', str(directory / 'unreviewed-copy.py')):
                error = expect_failure(controller.verify_script_path, 'actual script')
        elif scenario == 'git_environment':
            with patch.dict(os.environ, GIT_DIR=str(fixture.wrapper / '.git'),
                            GIT_WORK_TREE=str(fixture.wrapper), PYTHONPATH=str(directory),
                            ANSIBLE_CONFIG=str(directory / 'untrusted.cfg')):
                isolated = CONTROLLER.OnePass(fixture.args, repo_root=fixture.wrapper)
            isolated.root = controller.root
            isolated.input = dict(fixture.value)
            isolated.input_hash = controller.input_hash
            assert isolated.assert_sources() == initial
            assert not any(key.startswith('GIT_') for key in isolated.env)
            assert 'ANSIBLE_CONFIG' not in isolated.env and 'PYTHONPATH' not in isolated.env
            assert isolated.env['ANSIBLE_NOCOLOR'] == '1'
            error = None
        else:
            raise AssertionError(scenario)
    return {'initial_bindings': initial, 'rejection': error}


def child_fixture(directory):
    fixture = PipelineFixture(directory)
    controller = fixture.controller
    tools = fixture.rollout / 'tools'
    tools.mkdir()
    shutil.copyfile(ROOT / 'tools/ntp-rollout.py', tools / 'ntp-rollout.py')
    child = controller.root / 'child' / 'ansible-ntp-rollout-fixture'
    (child / 'gates').mkdir(parents=True)
    (child / 'wrapper').mkdir()
    controller.child_input = {'reviewed_source_sha': CONTROLLER.ROLLOUT_SHA,
                              'public_upstreams': CONTROLLER.UPSTREAMS,
                              'source_policy_ref': CONTROLLER.SOURCE_REF,
                              'network_policy_ref': 'fixture:actual-preparation',
                              'recovery_ref': 'fixture:actual-recovery'}
    CONTROLLER.write_json(child / 'RUNTIME_INPUT.json', controller.child_input)
    controller.child_input_hash = CONTROLLER.sha256((child / 'RUNTIME_INPUT.json').read_bytes())
    CONTROLLER.write_json(child / 'SOURCE.json', {'head': CONTROLLER.ROLLOUT_SHA,
                                                'tree': CONTROLLER.ROLLOUT_TREE, 'clean': True})
    result = {'status': 'ROLLOUT_COMPLETED_REVIEW_REQUIRED', 'apply_requested': True,
              'source_applied': True, 'source_phase_started': True, 'clients_started': True,
              'wrapper_finalize': 'COMPLETED', 'reviewed_source_sha': CONTROLLER.ROLLOUT_SHA,
              'input_sha256': controller.child_input_hash, 'run_id': child.name,
              'source_checkout': str(fixture.rollout)}
    CONTROLLER.write_json(child / 'RESULT.json', result)
    CONTROLLER.write_json(child / 'COMMANDS.json', [
        {'phase': phase, 'returncode': 0, 'timed_out': False, 'interrupted': False}
        for phase in ('precheck', 'diagnose', 'source', 'pathcheck', 'clients', 'verify', 'finalize')])
    for gate in ('diagnose', 'pathcheck'):
        for host, ip in CONTROLLER.HOSTS.items():
            targets = CONTROLLER.UPSTREAMS if gate == 'diagnose' and host == CONTROLLER.SOURCE else (
                [CONTROLLER.HOSTS[CONTROLLER.SOURCE]] if gate == 'pathcheck' and host != CONTROLLER.SOURCE else [])
            checks = {key: True for key in ('host_identity', 'chrony_version', 'service_contract',
                                            'no_competing_service', 'effective_parse')}
            if gate == 'diagnose':
                checks['migration_plan'] = True
            elif host == CONTROLLER.SOURCE:
                checks['source_runtime_acl_listener'] = True
            value = {'schema_version': 1, 'gate': gate, 'run_id': child.name,
                     'source_head': CONTROLLER.ROLLOUT_SHA, 'input_sha256': controller.child_input_hash,
                     'inventory_hostname': host, 'ansible_host': ip, 'gate_pass': True, 'errors': [],
                     'probes': [{'target_address': target, 'target_port': 123, 'returncode': 0,
                                 'outer_timeout': False, 'sample_accepted': True, 'offset_seconds': 0.001,
                                 'gate_pass': True} for target in targets],
                     'observations': {'checks': checks,
                                      'service_properties': {'LoadState': 'loaded', 'ActiveState': 'active',
                                                             'MainPID': '456'},
                                      'expanded_exec_argv': ['/usr/sbin/chronyd', '-F', '2'],
                                      'effective_config': {'returncode': 0}}}
            CONTROLLER.write_json(child / 'gates' / (gate + '--' + host + '.json'), value)
    return fixture, child, result


def child_validation(directory, scenario):
    fixture, child, result = child_fixture(directory)
    controller = fixture.controller
    process = {'returncode': 0, 'timed_out': False, 'interrupted': False, 'output_limit': False}
    if scenario == 'valid':
        controller.validate_child(child, process)
        value = json.loads((controller.root / 'CHILD_VALIDATION.json').read_text())
        assert value['status'] == 'COMPLETE_ROLLOUT_VALIDATED'
        return value
    if scenario == 'process_timeout':
        process['timed_out'] = True
    elif scenario == 'partial_source':
        result['source_applied'] = None
        CONTROLLER.write_json(child / 'RESULT.json', result)
    elif scenario == 'finalization_failed':
        result['wrapper_finalize'] = 'FAILED_RETAINED'
        CONTROLLER.write_json(child / 'RESULT.json', result)
    elif scenario == 'wrong_tree':
        CONTROLLER.write_json(child / 'SOURCE.json', {'head': CONTROLLER.ROLLOUT_SHA,
                                                    'tree': '0' * 40, 'clean': True})
    elif scenario == 'child_input_changed':
        CONTROLLER.write_json(child / 'RUNTIME_INPUT.json', dict(controller.child_input, recovery_ref='other'))
    elif scenario == 'missing_verify_command':
        commands = json.loads((child / 'COMMANDS.json').read_text())
        CONTROLLER.write_json(child / 'COMMANDS.json', [row for row in commands if row['phase'] != 'verify'])
    elif scenario == 'source_drift_marker':
        CONTROLLER.write_json(child / 'SOURCE_BINDING_INVALID.json', {'dirty': True})
    else:
        path = child / 'gates' / 'pathcheck--k8s-worker01.json'
        receipt = json.loads(path.read_text())
        if scenario == 'stale_receipt':
            receipt['run_id'] = 'previous-run'
        elif scenario == 'offset_over_100ms':
            receipt['probes'][0]['offset_seconds'] = 0.101
        else:
            raise AssertionError(scenario)
        CONTROLLER.write_json(path, receipt)
    error = expect_failure(lambda: controller.validate_child(child, process))
    assert not (controller.root / 'CHILD_VALIDATION.json').exists()
    return {'rejected': scenario, 'error': error}


def inherited_lock(directory):
    fixture = PipelineFixture(directory)
    controller = fixture.controller
    lock = load_module('onepass_lock_local_fixture', ROOT / 'tools/ntp-workflow-lock.py')
    lock_path = directory / 'local-controller.lock'
    descriptor = lock.acquire_lock(path=lock_path)
    controller.lock_fd = descriptor
    controller.env[lock.FD_ENV] = str(descriptor)
    program = '''import importlib.util,os,sys
spec=importlib.util.spec_from_file_location('lock',sys.argv[1]);lock=importlib.util.module_from_spec(spec);spec.loader.exec_module(lock)
fd=lock.acquire_lock(inherited_fd=os.environ[lock.FD_ENV],path=sys.argv[2])
try:
    second=lock.acquire_lock(path=sys.argv[2])
except ValueError:
    print('INHERITED_AND_EXCLUSIVE')
else:
    os.close(second);raise SystemExit('lock was not exclusive')
os.close(fd)
'''
    try:
        record = controller.run_command('local-lock-child', [sys.executable, '-I', '-B', '-c', program,
                                         str(ROOT / 'tools/ntp-workflow-lock.py'), str(lock_path)])
        assert record['returncode'] == 0, record
        assert 'INHERITED_AND_EXCLUSIVE' in record['stdout'], record
        expect_failure(lambda: lock.acquire_lock(path=lock_path), 'Another NTP controller')
    finally:
        os.close(descriptor)
        controller.lock_fd = None
    os.close(lock.acquire_lock(path=lock_path))
    return {'child': record, 'parent_retained_until_close': True}


def unresolved_remote_journal(directory, state):
    fixture = PipelineFixture(directory)
    controller = fixture.controller
    (fixture.wrapper / 'tools').mkdir()
    engine = ROOT / 'tools/ntp-onepass-remote.py'
    shutil.copyfile(engine, fixture.wrapper / 'tools/ntp-onepass-remote.py')
    controller.remote_source_hash = CONTROLLER.sha256(engine.read_bytes())

    def command(phase, argv, timeout):
        directory = Path(argv[argv.index('--tree') + 1])
        response = {'schema_version': 1, 'action': 'egress',
                    'run_id': controller.summary['run_id'], 'host': CONTROLLER.SOURCE,
                    'status': 'STOP', 'journal_receipt': {'operations': [{'state': state}]}}
        CONTROLLER.write_json(directory / CONTROLLER.SOURCE,
                              {'rc': 2, 'stdout': json.dumps(response), 'failed': True})
        return {'returncode': 2, 'timed_out': False, 'interrupted': False, 'output_limit': False}

    with patch.object(controller, 'run_command', command), \
            patch.object(controller, 'mutation_guard', lambda: None):
        try:
            controller.remote('egress', CONTROLLER.SOURCE)
        except CONTROLLER.StateUncertain as exc:
            error = str(exc)
        else:
            raise AssertionError('Unresolved journal must not become a confirmed STOP rollback')
    responses = list((controller.root / 'remote').glob('*/RESPONSE.json'))
    assert len(responses) == 1, responses
    assert json.loads(responses[0].read_text())['journal_receipt']['operations'][0]['state'] == state
    return {'journal_state': state, 'classification': 'StateUncertain', 'error': error,
            'original_response_retained': True}


def samples_keep_minimum_interval(directory):
    all_results = []
    for duration in (0, 72):
        part = directory / ('duration-' + str(duration))
        part.mkdir()
        fixture = PipelineFixture(part)
        controller = fixture.controller
        clock = {'value': 1000.0}
        mutex = threading.Lock()
        calls = []

        def monotonic():
            with mutex:
                return clock['value']

        def sleep(seconds):
            with mutex:
                clock['value'] += seconds

        def require_ok(action, host):
            assert action == 'sample'
            with mutex:
                calls.append(host)
                clock['value'] += duration / 6
            return {'status': 'OK', 'host': host, 'details': {'pass': True, 'offset_seconds': 0.001}}

        with patch.object(controller, 'require_ok', require_ok), \
                patch.object(controller, 'mutation_guard', lambda: None), \
                patch.object(CONTROLLER.time, 'monotonic', monotonic), \
                patch.object(CONTROLLER.time, 'sleep', sleep):
            controller.sample_all()
        result = json.loads((controller.root / 'SAMPLES.json').read_text())
        assert result['status'] == 'PASSED' and len(result['samples']) == 6
        starts = [sample['started_monotonic'] for sample in result['samples']]
        ends = [sample['completed_monotonic'] for sample in result['samples']]
        assert all(b - a >= 60 for a, b in zip(starts, starts[1:])), starts
        assert all(start - end >= 60 for end, start in zip(ends, starts[1:])), (starts, ends)
        assert starts[-1] - starts[0] >= 300
        assert len(calls) == 36
        assert all(set(sample['hosts']) == set(CONTROLLER.HOSTS) for sample in result['samples'])
        all_results.append({'fixture_duration': duration, 'starts': starts, 'ends': ends})
    return all_results


def cases():
    yield 'snapshot_failure_blocks_every_mutation', snapshot_failure
    yield 'dry_run_only_collects_six_hosts', dry_run_has_no_mutation
    yield 'confirmed_ingress_failure_recovers_owned_delta', lambda d: ingress_failure(d, False)
    yield 'uncertain_ingress_preserves_state_and_stops', lambda d: ingress_failure(d, True)
    yield 'partial_rollout_preserves_shared_ingress_and_successful_hosts', partial_rollout_preserves_shared_rules
    yield 'confirmed_egress_failure_recovers_only_failing_host', lambda d: egress_failure(d, False)
    yield 'uncertain_egress_preserves_state_and_stops_later_hosts', lambda d: egress_failure(d, True)
    yield 'post_gate_failure_keeps_successful_host_policies', lambda d: final_gate_failure_preserves_success(d, 'post')
    yield 'sample_failure_keeps_successful_host_policies', lambda d: final_gate_failure_preserves_success(d, 'sample')
    yield 'success_does_not_claim_final_acceptance', success_keeps_final_acceptance_separate
    yield 'source_drift_stops_before_next_mutation', drift_stops_next_mutation
    for scenario in ('wrapper_tracked', 'rollout_tracked', 'wrapper_untracked', 'rollout_untracked',
                     'wrong_wrapper_sha', 'substituted_rollout', 'bound_input_tampered',
                     'wrong_script_path', 'git_environment'):
        yield 'source_' + scenario, lambda d, scenario=scenario: git_binding(d, scenario)
    for scenario in ('valid', 'process_timeout', 'partial_source', 'finalization_failed', 'wrong_tree',
                     'child_input_changed', 'missing_verify_command', 'source_drift_marker',
                     'stale_receipt', 'offset_over_100ms'):
        yield 'child_' + scenario, lambda d, scenario=scenario: child_validation(d, scenario)
    yield 'lock_inherited_by_child_and_retained_by_parent', inherited_lock
    for state in ('PREPARED', 'REMOVE_PREPARED', 'UNCERTAIN'):
        yield 'remote_unresolved_journal_' + state.lower(), lambda d, state=state: unresolved_remote_journal(d, state)
    yield 'six_samples_keep_60_second_minimum_for_fast_and_slow_observations', samples_keep_minimum_interval


def main():
    global CONTROLLER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--case', action='append', default=[])
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    source_files = [ROOT / 'tools/ntp-onepass.py', ROOT / 'tools/ntp-onepass-remote.py', ROOT / 'tools/ntp-rollout.py',
                    ROOT / 'tools/ntp-workflow-lock.py', Path(__file__).resolve()]
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in source_files}
    CONTROLLER = load_module('ntp_onepass_controller_test', ROOT / 'tools/ntp-onepass.py')
    selected = [(name, body) for name, body in cases() if not args.case or name in args.case]
    if not selected:
        parser.error('No matching cases')
    results = []
    for name, body in selected:
        directory = args.output / name
        directory.mkdir()
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                details = body(directory)
            result = {'name': name, 'passed': True, 'details': details}
        except Exception:
            result = {'name': name, 'passed': False, 'error': traceback.format_exc()}
        (directory / 'test.stdout.log').write_text(stdout.getvalue())
        (directory / 'TEST_RESULT.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
        results.append(result)
        print('PASS' if result['passed'] else 'FAIL', name)
        if not result['passed']:
            print(result['error'])
    report = {'scope': __doc__, 'results': results,
              'passed': sum(result['passed'] for result in results), 'total': len(results),
              'source_sha256': source_hashes,
              'source_unchanged_during_run': all(hashlib.sha256(path.read_bytes()).hexdigest() ==
                                               source_hashes[str(path.relative_to(ROOT))]
                                               for path in source_files)}
    (args.output / 'RESULTS.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(f"{report['passed']}/{report['total']} PASS (LOCAL/MOCK)")
    return 0 if report['passed'] == report['total'] and report['source_unchanged_during_run'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
