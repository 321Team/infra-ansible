#!/usr/bin/env python3
"""Separately reviewed post-egress verification; default is entirely offline.

--verify requires a new explicit window and CR_NTP_FOLLOWUP_APPROVED. It never
replays the onepass pipeline or modifies its original journal/configuration.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
WRAPPER_SHA256 = '0f8b653565f268b1a5a33e3bcd3afc985a3468a1db9669fccec28b5fa4602646'
REMOTE_SHA256 = '839f2b0fec93541b7dfc39404b0897efedfab2253831253c2d4bff67451c5fd9'


def module(name, path, expected=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Source must be a regular file: ' + str(path))
    source = path.read_bytes()
    if expected and hashlib.sha256(source).hexdigest() != expected:
        raise ValueError('Approved dependency bytes differ: ' + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    # Execute the bytes just checked, rather than any ignored cached bytecode.
    exec(compile(source, str(path), 'exec'), value.__dict__)
    return value


W = module('ntp_post_approved_wrapper', ROOT / 'tools/ntp-onepass.py', WRAPPER_SHA256)
R = module('ntp_post_remote', ROOT / 'tools/ntp-post-egress-remote.py', REMOTE_SHA256)
# The unchanged wrapper's dependency loader must also execute current source bytes.
W.load_tool = module


def validate_input(value):
    keys = {'reviewed_followup_sha', 'window_start', 'window_end', 'approval_ref',
            'network_policy_ref', 'recovery_ref'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Followup input must contain exactly the documented six keys')
    if not isinstance(value['reviewed_followup_sha'], str) or not re.fullmatch(r'[a-f0-9]{40}', value['reviewed_followup_sha']):
        raise ValueError('Full independently reviewed followup commit required')
    R.validate_window(value['window_start'], value['window_end'], require_active=False)
    for key in ('approval_ref', 'network_policy_ref', 'recovery_ref'):
        item = value[key]
        if (not isinstance(item, str) or item != item.strip() or not item or len(item) > 2048 or
                '\n' in item or '\r' in item or item.startswith('<') or
                re.match(r'(?i)^(PENDING|UNCONFIRMED|TODO|TBD|NOT[ _]RUN|REPLACE|CHANGE_ME)(\b|_)', item)):
            raise ValueError('Actual followup governance reference required: ' + key)
    for key in ('network_policy_ref', 'recovery_ref'):
        if not Path(value[key]).is_absolute():
            raise ValueError(key + ' must name an existing absolute local file')
    return value


class Followup(W.OnePass):
    def __init__(self, args, repo_root=None):
        args.apply = False
        super().__init__(args, repo_root=repo_root)
        self.preflight_receipts = {}
        self.ref_hashes = {}
        self.followup_remote_hash = None
        self.clock_bindings = {}
        self.summary.update(verify_requested=bool(args.verify), prior_run_id=R.PRIOR_RUN_ID,
                            preflight_completed=[], negative_completed=[], finalize_completed=[],
                            original_journal_replayed=False, configuration_mutation_requested=False,
                            baseline_collector_sha256=R.BASELINE_SOURCE_SHA256)

    def create_evidence(self):
        parent = W.safe_parent(self.args.evidence_parent or W.pwd.getpwuid(os.geteuid()).pw_dir)
        if any(parent == repo or repo in parent.parents for repo in (self.repo, self.rollout_repo)):
            raise ValueError('Evidence must be outside both source checkouts')
        self.root = Path(W.tempfile.mkdtemp(prefix='ntp-post-egress-', dir=parent))
        self.root.chmod(0o700)
        for name in ('controller', 'remote'):
            (self.root / name).mkdir(mode=0o700)
        self.summary.update(run_id='ntp-post-egress-' + uuid.uuid4().hex, started_at=W.now())
        print('EVIDENCE_DIRECTORY=' + str(self.root), flush=True)

    def assert_sources(self):
        bindings = {}
        for label, repo, expected, tree in (
                ('followup', self.repo, self.input['reviewed_followup_sha'], self.wrapper_tree),
                ('rollout', self.rollout_repo, W.ROLLOUT_SHA, W.ROLLOUT_TREE)):
            if not repo.is_absolute() or repo.resolve() != repo or self.git(repo, 'rev-parse', '--show-toplevel') != str(repo):
                raise ValueError('Separate absolute nonsymlink source checkout required')
            head = self.git(repo, 'rev-parse', '--verify', 'HEAD')
            observed = self.git(repo, 'rev-parse', 'HEAD^{tree}')
            dirty = self.git(repo, 'status', '--porcelain', '--untracked-files=all', '--ignore-submodules=none')
            if head != expected or dirty or (tree is not None and observed != tree):
                raise ValueError(label + ' HEAD/tree/clean state differs from reviewed source')
            bindings[label] = {'head': head, 'tree': observed, 'clean': True}
        if self.repo == self.rollout_repo:
            raise ValueError('Followup and approved rollout must be separate checkouts')
        if W.sha256((self.repo / 'tools/ntp-onepass.py').read_bytes()) != WRAPPER_SHA256:
            raise ValueError('Approved wrapper dependency changed')
        if W.sha256((self.repo / 'tools/ntp-onepass-remote.py').read_bytes()) != R.BASE_SHA256:
            raise ValueError('Approved PR32 engine dependency changed')
        if W.sha256((self.repo / 'tools/ntp-post-egress-remote.py').read_bytes()) != REMOTE_SHA256:
            raise ValueError('Pinned followup remote dependency changed')
        self.wrapper_tree = bindings['followup']['tree']
        return bindings

    def reference_hashes(self):
        values = {}
        for key in ('network_policy_ref', 'recovery_ref'):
            path = Path(self.input[key])
            info = path.lstat()
            if (path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022 or info.st_size > 1024 * 1024):
                raise ValueError('Unsafe governance reference: ' + str(path))
            values[key] = W.sha256(path.read_bytes())
        return values

    def load_input(self):
        if not Path(self.args.input).is_absolute():
            raise ValueError('--input must be absolute')
        raw, value = W.read_json_bytes(self.args.input)
        self.input, self.input_hash = validate_input(value), W.sha256(raw)
        self.assert_sources()
        script = Path(__file__).absolute()
        if script != self.repo / 'tools/ntp-post-egress.py' or script.resolve() != script:
            raise ValueError('Execute the tracked script in the reviewed followup checkout')
        self.ref_hashes = self.reference_hashes()
        target = self.root / 'FOLLOWUP_INPUT.json'
        target.write_bytes(raw)
        target.chmod(0o400)
        self.followup_remote_hash = W.sha256((self.repo / 'tools/ntp-post-egress-remote.py').read_bytes())
        self.summary.update(input_sha256=self.input_hash, reviewed_followup_sha=value['reviewed_followup_sha'],
                            reviewed_source_sha=W.ROLLOUT_SHA, approval_ref=value['approval_ref'],
                            approval_reference_supplied_by_operator=True,
                            window_start=value['window_start'], window_end=value['window_end'])
        W.write_json(self.root / 'SOURCE.json', self.assert_sources())
        W.write_json(self.root / 'GOVERNANCE_REFS.json', self.ref_hashes)
        # Reuse the reviewed receipt validator with a fresh gate/run/input binding.
        self.child_input = {'reviewed_source_sha': W.ROLLOUT_SHA, 'public_upstreams': W.UPSTREAMS,
                            'source_policy_ref': W.SOURCE_REF, 'network_policy_ref': value['network_policy_ref'],
                            'recovery_ref': value['recovery_ref']}
        self.child_input_hash = self.input_hash

    def verify_input(self):
        raw, value = W.read_json_bytes(self.root / 'FOLLOWUP_INPUT.json')
        if W.sha256(raw) != self.input_hash or value != self.input or self.reference_hashes() != self.ref_hashes:
            raise ValueError('Bound input or governance references changed')

    def mutation_guard(self):
        self.assert_sources()
        self.verify_input()
        if self.args.verify:
            if os.environ.get('CR_NTP_FOLLOWUP_APPROVED') != W.CHANGE_ID:
                raise ValueError('--verify requires CR_NTP_FOLLOWUP_APPROVED=' + W.CHANGE_ID)
            R.validate_window(self.input['window_start'], self.input['window_end'])

    def prepare(self):
        if not self.args.verify:
            self.load_input()
            self.mutation_guard()
            return
        if os.environ.get('CR_NTP_FOLLOWUP_APPROVED') != W.CHANGE_ID:
            raise ValueError('--verify requires the separate followup approval environment')
        # Preparation configures identity/strict SSH and the shared controller lock.
        # It performs no remote action and cannot call the old execution pipeline.
        super().prepare()
        self.env.pop('CR_CHANGE_APPROVED', None)

    def run_command(self, phase, argv, timeout=60, env=None):
        if self.args.verify and self.input is not None:
            self.mutation_guard()
            end = R.validate_window(self.input['window_start'], self.input['window_end'])[1]
            remaining = (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            if remaining < timeout + 10:
                raise ValueError(phase + ': full bounded command plus cleanup margin does not fit the approved window')
            timeout = min(timeout, max(1, int(remaining - 10)))
        result = super().run_command(phase, argv, timeout=timeout, env=env)
        if self.args.verify and self.input is not None:
            self.mutation_guard()
        return result

    def clock_binding(self, host):
        """Fix a remote deadline from a prior sample, never from request arrival.

        The sample precedes controller receipt. Adding only the receipt-time
        remainder, less 10 s, to that earlier sample includes transport delays.
        A cached binding cannot renew the same host's work window.
        """
        if not self.args.verify or host not in W.HOSTS:
            raise ValueError('Clock query exceeds explicit followup verification scope')
        self.mutation_guard()
        if host in self.clock_bindings:
            return dict(self.clock_bindings[host])
        request = {'schema_version': 1, 'action': 'clock', 'host': host,
                   'followup_run_id': self.summary['run_id'],
                   'window_start': self.input['window_start'], 'window_end': self.input['window_end'],
                   'request_id': uuid.uuid4().hex}
        code = (self.repo / 'tools/ntp-post-egress-remote.py').read_text()
        if W.sha256(code.encode()) != REMOTE_SHA256:
            raise ValueError('Pinned clock-query source bytes changed')
        operation = self.root / 'remote' / ('clock-' + host + '-' + request['request_id'][:10])
        operation.mkdir(mode=0o700)
        payload = ('import json\n_scope = {"__name__": "fds_ntp_post_egress_clock"}\n' +
                   'exec(compile(' + repr(code) + ', "ntp-post-egress-remote.py", "exec"), _scope)\n' +
                   '_result = json.loads(' + repr(json.dumps(request)) + ')\n' +
                   '_result.update(status="OK", changed=False, clock=_scope["clock_snapshot"]())\n' +
                   'print(json.dumps(_result, sort_keys=True))\n')
        (operation / 'stdin.py').write_text(payload)
        W.write_json(operation / 'REQUEST.json', request)
        rawdir = operation / 'ansible-results'
        rawdir.mkdir(mode=0o700)
        command = {'argv': ['/usr/bin/python3', '-I', '-B', '-'], 'stdin': payload, 'stdin_add_newline': False}
        result = self.run_command('clock-' + host, ['ansible', host, '-i', str(self.root / 'inventory.json'),
                    '--become', '-m', 'ansible.builtin.command', '-a', json.dumps(command), '--tree', str(rawdir)], timeout=30)
        received = datetime.datetime.now(datetime.timezone.utc)
        if result['returncode'] != 0 or any(result.get(key) for key in ('timed_out', 'interrupted', 'output_limit')):
            raise W.StateUncertain(host + ': no completed clock observation')
        try:
            _, raw = W.read_json_bytes(rawdir / host)
            if (not isinstance(raw, dict) or raw.get('unreachable') or raw.get('skipped') or
                    type(raw.get('rc')) is not int or raw['rc'] != 0):
                raise ValueError('No completed remote clock command')
            value = json.loads(raw['stdout'], object_pairs_hook=W.unique_object)
            if (not isinstance(value, dict) or set(value) != set(request) | {'status', 'changed', 'clock'} or
                    type(value.get('schema_version')) is not int or
                    any(value.get(k) != v for k, v in request.items()) or
                    value['status'] != 'OK' or value['changed'] is not False):
                raise ValueError('Clock response binding/status mismatch')
            sample = value['clock']
            if (not isinstance(sample, dict) or set(sample) != {'boot_id', 'boottime_ns'} or
                    not isinstance(sample['boot_id'], str) or not re.fullmatch(
                        r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', sample['boot_id']) or
                    type(sample['boottime_ns']) is not int or sample['boottime_ns'] <= 0):
                raise ValueError('Invalid remote boot clock observation')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise W.StateUncertain(host + ': no valid bound clock observation') from exc
        end = R.validate_window(self.input['window_start'], self.input['window_end'], now=received)[1]
        remaining_ns = int((end - received).total_seconds() * 1_000_000_000) - 10_000_000_000
        if remaining_ns <= 0:
            raise ValueError('Clock observation leaves no work-window budget')
        binding = {'boot_id': sample['boot_id'], 'sampled_boottime_ns': sample['boottime_ns'],
                   'deadline_boottime_ns': sample['boottime_ns'] + remaining_ns,
                   'controller_received_at': received.isoformat()}
        W.write_json(operation / 'RESPONSE.json', value)
        W.write_json(operation / 'CLOCK_BINDING.json', binding)
        self.clock_bindings[host] = binding
        W.write_json(self.root / 'CLOCK_BINDINGS.json', self.clock_bindings)
        self.mutation_guard()
        return dict(binding)

    def remote(self, action, host):
        if not self.args.verify or action not in R.ACTIONS or host not in W.HOSTS:
            raise ValueError('Remote action exceeds explicit followup verification scope')
        self.mutation_guard()
        expected = None if action == 'preflight' else self.preflight_receipts[host]
        request = {'schema_version': 1, 'action': action, 'host': host, 'prior_run_id': R.PRIOR_RUN_ID,
                   'followup_run_id': self.summary['run_id'], 'window_start': self.input['window_start'],
                   'window_end': self.input['window_end'], 'expected_preservation': expected,
                   'clock_binding': self.clock_binding(host)}
        code = (self.repo / 'tools/ntp-post-egress-remote.py').read_text()
        base = (self.repo / 'tools/ntp-onepass-remote.py').read_text()
        if W.sha256(code.encode()) != self.followup_remote_hash or W.sha256(base.encode()) != R.BASE_SHA256:
            raise ValueError('Remote source bytes changed')
        operation = self.root / 'remote' / (action + '-' + host + '-' + uuid.uuid4().hex[:10])
        operation.mkdir(mode=0o700)
        payload = ('import json\n_scope = {"__name__": "fds_ntp_post_egress"}\n' +
                   'exec(compile(' + repr(code) + ', "ntp-post-egress-remote.py", "exec"), _scope)\n' +
                   'raise SystemExit(_scope["main"](json.loads(' + repr(json.dumps(request)) + '), ' + repr(base) + '))\n')
        (operation / 'stdin.py').write_text(payload)
        W.write_json(operation / 'REQUEST.json', request)
        rawdir = operation / 'ansible-results'
        rawdir.mkdir(mode=0o700)
        command = {'argv': ['/usr/bin/python3', '-I', '-B', '-'], 'stdin': payload, 'stdin_add_newline': False}
        result = self.run_command(action + '-' + host, ['ansible', host, '-i', str(self.root / 'inventory.json'),
                    '--become', '-m', 'ansible.builtin.command', '-a', json.dumps(command), '--tree', str(rawdir)], timeout=180)
        if any(result.get(key) for key in ('timed_out', 'interrupted', 'output_limit')):
            raise W.StateUncertain(action + '/' + host + ': interrupted observation; preserve original state')
        try:
            _, raw = W.read_json_bytes(rawdir / host)
            if (not isinstance(raw, dict) or raw.get('unreachable') or raw.get('skipped') or
                    type(raw.get('rc')) is not int or raw['rc'] not in (0, 2)):
                raise ValueError('No completed remote command')
            value = json.loads(raw['stdout'], object_pairs_hook=W.unique_object)
            if (not isinstance(value, dict) or type(value.get('schema_version')) is not int or
                    any(value.get(k) != v for k, v in request.items()) or
                    value.get('status') not in ('OK', 'STOP') or (value['status'] == 'OK') != (raw['rc'] == 0) or
                    value.get('changed') is not False):
                raise ValueError('Followup response binding/status mismatch')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise W.StateUncertain(action + '/' + host + ': no valid bound followup response') from exc
        W.write_json(operation / 'RESPONSE.json', value)
        with self.thread_lock:
            self.remote_results.append({'action': action, 'host': host, 'response': value,
                                        'path': str(operation.relative_to(self.root))})
            W.write_json(self.root / 'REMOTE_RESULTS.json', self.remote_results)
        if value.get('preservation_uncertain'):
            raise W.StateUncertain(action + '/' + host + ': original state preservation is uncertain')
        if value['status'] == 'OK':
            if result['returncode'] != 0:
                raise W.StateUncertain(action + '/' + host + ': transport failed despite completed response')
            details = value.get('details', {})
            if not isinstance(details, dict):
                raise W.StateUncertain('Successful followup lacks structured details')
            preservation = details.get('preservation_after')
            if (details.get('configuration_unchanged') is not True or details.get('journal_unchanged') is not True or
                    details.get('preservation_before') != details.get('preservation_after') or
                    not isinstance(preservation, dict) or set(preservation) != {'files', 'kernel', 'journal_sha256'} or
                    not isinstance(preservation.get('files'), dict) or
                    set(preservation['files']) != set(R.PRESERVED_FILES) or
                    preservation.get('kernel') != R.BASELINE[host]['kernel'] or
                    preservation.get('journal_sha256') != R.BASELINE[host]['journal_sha256'] or
                    (expected is not None and preservation != expected) or
                    value.get('journal_sha256_after') != R.BASELINE[host]['journal_sha256']):
                raise W.StateUncertain('Successful followup lacks complete preservation evidence')
            for name, actual in preservation['files'].items():
                if not isinstance(actual, dict) or actual.get('path') != name or type(actual.get('exists')) is not bool:
                    raise W.StateUncertain('Malformed preserved file observation: ' + name)
                if not actual['exists']:
                    if set(actual) != {'path', 'exists'}:
                        raise W.StateUncertain('Malformed absent file observation: ' + name)
                elif (set(actual) != {'path', 'exists', 'uid', 'gid', 'mode', 'sha256'} or
                        type(actual['uid']) is not int or actual['uid'] != 0 or
                        type(actual['gid']) is not int or actual['gid'] < 0 or
                        not isinstance(actual['mode'], str) or not re.fullmatch(r'0o[0-7]{1,4}', actual['mode']) or
                        int(actual['mode'], 8) & 0o022 or not isinstance(actual['sha256'], str) or
                        not re.fullmatch(r'[a-f0-9]{64}', actual['sha256'])):
                    raise W.StateUncertain('Malformed protected file observation: ' + name)
            for name, baseline in R.BASELINE[host]['files'].items():
                actual = preservation['files'][name]
                if not isinstance(actual, dict) or any(actual.get(key) != item for key, item in baseline.items()):
                    raise W.StateUncertain('Successful followup contains configuration drift: ' + name)
            observation = details.get('observation')
            if not isinstance(observation, dict):
                raise W.StateUncertain('Successful followup lacks structured observation')
            if action == 'verify':
                packet = observation.get('negative_ipv4_probe')
                if (not isinstance(packet, dict) or packet.get('pass') is not True or
                        packet.get('destination') != '192.0.2.123' or packet.get('port') != 123 or
                        packet.get('bytes') != 48 or type(packet.get('counter_before')) is not int or
                        type(packet.get('counter_after')) is not int or packet['counter_before'] < 0 or
                        packet['counter_after'] <= packet['counter_before']):
                    raise W.StateUncertain('Successful negative probe lacks submitted packet and DROP-counter proof')
            if action == 'sample':
                # Preserve compatibility with the approved six-round sampler.
                value['details'].update(observation)
        self.mutation_guard()
        return value

    def post_egress_gates(self):
        self.mutation_guard()
        end = R.validate_window(self.input['window_start'], self.input['window_end'])[1]
        remaining = (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if remaining < 1810:
            raise ValueError('Window must allow both bounded 900-second positive gates; obtain a new approved window')
        super().post_egress_gates()

    def execute_pipeline(self):
        if not self.args.verify:
            self.summary['status'] = 'FOLLOWUP_OFFLINE_PREPARED_NOT_EXECUTED'
            return
        for host in W.HOSTS:
            value = self.require_ok('preflight', host)
            self.preflight_receipts[host] = value['details']['preservation_after']
            self.summary['preflight_completed'].append(host)
        W.write_json(self.root / 'PREFLIGHT_PRESERVATION.json', self.preflight_receipts)
        for host in W.HOSTS:
            self.require_ok('verify', host)
            self.summary['negative_completed'].append(host)
        self.post_egress_gates()
        self.sample_all()
        for host in W.HOSTS:
            self.require_ok('finalize', host)
            self.summary['finalize_completed'].append(host)
        self.summary['status'] = 'POST_EGRESS_VERIFIED_REVIEW_REQUIRED'

    def run_child(self):
        raise ValueError('Full rollout replay is unavailable in followup')

    def rollback_confirmed(self, action, host):
        raise ValueError('Followup never rolls back existing configuration or journal')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollout-repo', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--evidence-parent', type=Path)
    parser.add_argument('--verify', action='store_true', help='Run separately approved probes within the supplied new window')
    args = parser.parse_args()
    if not args.rollout_repo.is_absolute():
        parser.error('--rollout-repo must be an absolute fixed approved checkout')
    os.umask(0o077)
    controller = Followup(args)

    def interrupted(number, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for process in controller.active_processes.copy().values():
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        raise W.OnePassInterrupted('Interrupted by signal ' + str(number))

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    return controller.run()


if __name__ == '__main__':
    raise SystemExit(main())
