#!/usr/bin/env python3
"""One invocation of the reviewed NTP rollout with bounded firewall preparation.

Default mode only collects snapshots. --apply requires the reviewed wrapper and
unchanged approved rollout checkout, real policy/recovery references, and the
existing CR_CHANGE_APPROVED setting. Final acceptance remains a separate review.
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid

sys.dont_write_bytecode = True
CHANGE_ID = 'CR-P1-NTP-01-01'
ROLLOUT_SHA = 'eb08dc8c4ae3505dace39e76a11ef57be75e96ce'
ROLLOUT_TREE = 'a3f0f5529dd249c9b0a48d2a8dde17997208df4d'
HOSTS = {'k8s-control01': '10.1.93.102', 'k8s-control02': '10.1.93.103',
         'k8s-control03': '10.1.93.104', 'k8s-worker01': '10.1.93.105',
         'k8s-worker02': '10.1.93.107', 'k8s-worker03': '10.1.93.108'}
SOURCE = 'k8s-control01'
UPSTREAMS = ['162.159.200.1', '162.159.200.123']
SOURCE_REF = 'https://github.com/321Team/fds-project-baseline/issues/10#issuecomment-5740306915'
KEY = Path('/home/server01_ansible/.ssh/p1_ansible_ed25519')
KNOWN_HOSTS = Path('/home/server01_ansible/.ssh/known_hosts')
JSON_LIMIT = 8 * 1024 * 1024
LOG_LIMIT = 64 * 1024 * 1024
MUTATIONS = {'ingress', 'egress', 'rollback_ingress', 'rollback_egress'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json_bytes(path):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_size > JSON_LIMIT):
        raise ValueError('Unsafe bounded JSON file: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError('File changed while opening')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(JSON_LIMIT + 1)
    finally:
        os.close(fd)
    if len(raw) > JSON_LIMIT:
        raise ValueError('JSON exceeds limit')
    return raw, json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)


def write_json(path, value):
    path = Path(path)
    # All destinations are under a fresh mode-0700 evidence directory.
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
    temporary.chmod(0o600)
    os.replace(temporary, path)


def safe_parent(path):
    path = Path(path).absolute()
    for item in [path] + list(path.parents):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()):
            raise ValueError('Unsafe directory: ' + str(item))
        if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            raise ValueError('Writable directory: ' + str(item))
    return path


def clean_env():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('ANSIBLE_', 'GIT_', 'PYTHON', 'CR_NTP_'))
           and k not in ('CR_CHANGE_APPROVED', 'CR_EVIDENCE_DIR', 'SSH_ASKPASS', 'SSH_ASKPASS_REQUIRE')}
    env.update(LANG='C.UTF-8', LC_ALL='C.UTF-8', PYTHONDONTWRITEBYTECODE='1', ANSIBLE_NOCOLOR='1')
    return env


def load_tool(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StateUncertain(Exception):
    """A remote response cannot prove the complete outcome; preserve journals."""


class OnePassInterrupted(Exception):
    pass


class OnePass:
    def __init__(self, args, repo_root=None):
        self.args = args
        self.repo = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
        self.rollout_repo = Path(args.rollout_repo).absolute()
        self.root = None
        self.lock_fd = None
        self.input = None
        self.input_hash = None
        self.wrapper_tree = None
        self.records = []
        self.active_processes = {}
        self.thread_lock = threading.Lock()
        self.env = clean_env()
        self.summary = {'schema_version': 1, 'change_id': CHANGE_ID, 'status': 'INITIALIZING',
                        'apply_requested': bool(args.apply), 'child_started': False,
                        'ingress_ready': False, 'egress_completed': [],
                        'runtime_acceptance': 'REVIEW_REQUIRED',
                        'ipv6_negative': 'NOT_RUN', 'reboot_resync': 'NOT_RUN',
                        'sync_loss_injection': 'NOT_RUN'}
        self.remote_results = []
        self.post_gate_root = None

    def create_evidence(self):
        parent = safe_parent(self.args.evidence_parent or pwd.getpwuid(os.geteuid()).pw_dir)
        if any(parent == repo or repo in parent.parents for repo in (self.repo, self.rollout_repo)):
            raise ValueError('Evidence must be outside both source checkouts')
        self.root = Path(tempfile.mkdtemp(prefix='ntp-onepass-', dir=parent))
        self.root.chmod(0o700)
        for name in ('controller', 'remote', 'child'):
            (self.root / name).mkdir(mode=0o700)
        self.summary.update(run_id='ntp-onepass-' + uuid.uuid4().hex, started_at=now())
        print('EVIDENCE_DIRECTORY=' + str(self.root), flush=True)

    @staticmethod
    def stop_process(process):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

    def run_command(self, phase, argv, timeout=60, env=None):
        stem = re.sub(r'[^A-Za-z0-9_-]', '_', phase) + '-' + uuid.uuid4().hex[:10]
        out = self.root / 'controller' / (stem + '.stdout.log')
        err = self.root / 'controller' / (stem + '.stderr.log')
        started = time.monotonic()
        process = None
        timed_out = interrupted = output_limit = False
        print('STAGE=' + phase, flush=True)
        try:
            with out.open('xb') as stdout, err.open('xb') as stderr:
                process = subprocess.Popen(argv, cwd=self.root, env=env or self.env,
                                           stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                           start_new_session=True,
                                           pass_fds=(self.lock_fd,) if self.lock_fd is not None else ())
                with self.thread_lock:
                    self.active_processes[process.pid] = process
                while process.poll() is None:
                    if time.monotonic() - started > timeout:
                        timed_out = True
                        self.stop_process(process)
                        break
                    if out.stat().st_size + err.stat().st_size > LOG_LIMIT:
                        output_limit = True
                        self.stop_process(process)
                        break
                    time.sleep(0.1)
        except BaseException:
            interrupted = True
            if process is not None:
                self.stop_process(process)
            raise
        finally:
            with self.thread_lock:
                if process is not None:
                    self.active_processes.pop(process.pid, None)
                # stdin code is retained separately, never copied into argv metadata.
                recorded = list(map(str, argv))
                if '-a' in recorded:
                    recorded[recorded.index('-a') + 1] = '<retained remote command JSON>'
                record = {'phase': phase, 'argv': recorded,
                          'returncode': process.returncode if process else None,
                          'timed_out': timed_out, 'interrupted': interrupted, 'output_limit': output_limit,
                          'elapsed_seconds': round(time.monotonic() - started, 3),
                          'stdout_file': str(out.relative_to(self.root)),
                          'stderr_file': str(err.relative_to(self.root))}
                self.records.append(record)
                write_json(self.root / 'COMMANDS.json', self.records)
        return dict(record, stdout=out.read_bytes()[:JSON_LIMIT].decode('utf-8', errors='replace'),
                    stderr=err.read_bytes()[:JSON_LIMIT].decode('utf-8', errors='replace'))

    def command_ok(self, phase, argv, timeout=60, env=None):
        result = self.run_command(phase, argv, timeout, env)
        if result['returncode'] != 0 or any(result.get(k) for k in ('timed_out', 'interrupted', 'output_limit')):
            raise ValueError(phase + ' failed; retained logs identify the cause')
        return result

    def git(self, repo, *args):
        result = subprocess.run(['git', '-C', str(repo)] + list(args), env=self.env,
                                capture_output=True, text=True, timeout=20, check=False)
        if result.returncode:
            raise ValueError('Git verification failed: ' + str(repo))
        return result.stdout.strip()

    def assert_sources(self):
        bindings = {}
        for label, repo, expected, tree in (
                ('wrapper', self.repo, self.input['reviewed_wrapper_sha'], self.wrapper_tree),
                ('rollout', self.rollout_repo, ROLLOUT_SHA, ROLLOUT_TREE)):
            if not repo.is_absolute() or repo.resolve() != repo:
                raise ValueError('Source path must be absolute and without symlinks')
            if self.git(repo, 'rev-parse', '--show-toplevel') != str(repo):
                raise ValueError('Source must be its own Git checkout')
            head = self.git(repo, 'rev-parse', '--verify', 'HEAD')
            observed_tree = self.git(repo, 'rev-parse', 'HEAD^{tree}')
            dirty = self.git(repo, 'status', '--porcelain', '--untracked-files=all', '--ignore-submodules=none')
            if head != expected or dirty or (tree is not None and observed_tree != tree):
                raise ValueError(label + ' HEAD/tree/clean state differs from the reviewed source')
            bindings[label] = {'head': head, 'tree': observed_tree, 'clean': True}
        if self.repo == self.rollout_repo:
            raise ValueError('Wrapper and fixed approved rollout must be separate checkouts')
        self.wrapper_tree = bindings['wrapper']['tree']
        return bindings

    def verify_script_path(self):
        path = Path(__file__).absolute()
        if path != self.repo / 'tools/ntp-onepass.py' or path.resolve() != path:
            raise ValueError('Execute the actual script from the reviewed wrapper checkout')
        if self.git(self.repo, 'ls-files', '--error-unmatch', 'tools/ntp-onepass.py') != 'tools/ntp-onepass.py':
            raise ValueError('Controller script is not tracked by the reviewed source')

    def load_input(self):
        raw, value = read_json_bytes(Path(self.args.input))
        expected = {'reviewed_wrapper_sha', 'reviewed_source_sha', 'public_upstreams',
                    'source_policy_ref', 'network_policy_ref', 'recovery_ref'}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError('One-pass input must contain exactly the documented six keys')
        if not isinstance(value['reviewed_wrapper_sha'], str) or not re.fullmatch(r'[0-9a-f]{40}', value['reviewed_wrapper_sha']):
            raise ValueError('reviewed_wrapper_sha must be the full independently reviewed wrapper HEAD')
        if value['reviewed_source_sha'] != ROLLOUT_SHA or value['public_upstreams'] != UPSTREAMS or value['source_policy_ref'] != SOURCE_REF:
            raise ValueError('Approved source, upstream pair or decision differs from the fixed scope')
        for key in ('network_policy_ref', 'recovery_ref'):
            item = value[key]
            if (not isinstance(item, str) or not item.strip() or item != item.strip() or len(item) > 2048
                    or '\n' in item or '\r' in item or item.startswith('<')
                    or item == SOURCE_REF
                    or re.match(r'(?i)^(PENDING|UNCONFIRMED|TODO|TBD|NOT[ _]RUN|REPLACE|CHANGE_ME)(\b|_)', item)):
                raise ValueError('Actual existing preparation/governance reference required: ' + key)
        self.input = value
        self.input_hash = sha256(raw)
        self.assert_sources()
        self.verify_script_path()
        target = self.root / 'ONEPASS_INPUT.json'
        target.write_bytes(raw)
        target.chmod(0o400)
        self.summary.update(input_sha256=self.input_hash, reviewed_wrapper_sha=value['reviewed_wrapper_sha'],
                            reviewed_source_sha=ROLLOUT_SHA)
        write_json(self.root / 'SOURCE.json', self.assert_sources())

    def verify_input(self):
        raw, value = read_json_bytes(self.root / 'ONEPASS_INPUT.json')
        if sha256(raw) != self.input_hash or value != self.input:
            raise ValueError('Bound one-pass input changed during execution')

    def mutation_guard(self):
        self.assert_sources()
        self.verify_input()

    def prepare(self):
        self.load_input()
        if self.command_ok('identity-host', ['hostnamectl', '--static'])['stdout'].strip() != 'ansible01':
            raise ValueError('Run only on ansible01')
        if self.command_ok('identity-user', ['id', '-un'])['stdout'].strip() != 'server01_ansible':
            raise ValueError('Run only as server01_ansible')
        for executable in ('ansible', 'ansible-playbook', 'ansible-inventory'):
            output = self.command_ok('version-' + executable, [executable, '--version'])['stdout']
            if not re.search(r'\[core 2[.]16[.]19\]', output.splitlines()[0] if output else ''):
                raise ValueError('Use the existing Ansible core 2.16.19 environment')
        for item in (KEY, KNOWN_HOSTS):
            info = item.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022 or not os.access(item, os.R_OK):
                raise ValueError('Existing SSH identity/known-host file is unsafe or unavailable')
        for address in HOSTS.values():
            self.command_ok('known-host-' + address, ['ssh-keygen', '-F', address, '-f', str(KNOWN_HOSTS)])
        if self.args.apply and os.environ.get('CR_CHANGE_APPROVED') != CHANGE_ID:
            raise ValueError('--apply requires existing CR_CHANGE_APPROVED=' + CHANGE_ID)
        # Acquire before the first host snapshot; release only after packaging.
        lock = load_tool('ntp_onepass_lock', self.rollout_repo / 'tools/ntp-workflow-lock.py')
        self.lock_fd = lock.acquire_lock()
        self.env[lock.FD_ENV] = str(self.lock_fd)
        config = self.root / 'ansible-onepass.cfg'
        config.write_text('[defaults]\nhost_key_checking=True\nretry_files_enabled=False\nforks=3\n'
                          'timeout=10\nstdout_callback=default\n[ssh_connection]\npipelining=True\n')
        config.chmod(0o600)
        self.env['ANSIBLE_CONFIG'] = str(config)
        self.env['ANSIBLE_PRIVATE_KEY_FILE'] = str(KEY)
        if self.args.apply:
            self.env['CR_CHANGE_APPROVED'] = CHANGE_ID
        ssh = ' '.join(['-o BatchMode=yes', '-o PreferredAuthentications=publickey',
                        '-o PasswordAuthentication=no', '-o KbdInteractiveAuthentication=no',
                        '-o StrictHostKeyChecking=yes', '-o IdentitiesOnly=yes', '-o IdentityAgent=none',
                        '-o GlobalKnownHostsFile=/dev/null', '-o UserKnownHostsFile=' + shlex.quote(str(KNOWN_HOSTS)),
                        '-o ControlMaster=no', '-o ControlPath=none', '-o ControlPersist=no',
                        '-o ConnectTimeout=10', '-o ServerAliveInterval=10', '-o ServerAliveCountMax=2'])
        variables = {'ansible_user': 'svc_ansible', 'ansible_connection': 'ssh',
                     'ansible_ssh_executable': '/usr/bin/ssh', 'ansible_python_interpreter': '/usr/bin/python3',
                     'ansible_ssh_private_key_file': str(KEY), 'ansible_ssh_common_args': ssh,
                     'ansible_ssh_args': '-o ControlMaster=no -o ControlPersist=no',
                     'ansible_become': True, 'ansible_become_method': 'sudo',
                     'ansible_become_user': 'root', 'ansible_become_flags': '-H -S -n'}
        write_json(self.root / 'inventory.json', {'all': {'children': {'k8s_nodes': {
            'hosts': {h: {'ansible_host': ip} for h, ip in HOSTS.items()}}}, 'vars': variables}})
        inventory = self.command_ok('approved-inventory', ['ansible-inventory', '-i',
                       str(self.rollout_repo / 'inventory/hosts.yml'), '--list'])
        data = json.loads(inventory['stdout'], object_pairs_hook=unique_object)
        for host, address in HOSTS.items():
            values = data.get('_meta', {}).get('hostvars', {}).get(host, {})
            if values.get('ansible_host') != address or values.get('ansible_user') != 'svc_ansible':
                raise ValueError('Approved inventory identity mismatch: ' + host)
        engine_path = self.repo / 'tools/ntp-onepass-remote.py'
        if engine_path.is_symlink() or not engine_path.is_file():
            raise ValueError('Remote engine must be a regular tracked source file')
        self.remote_source_hash = sha256(engine_path.read_bytes())
        self.mutation_guard()

    def remote(self, action, host):
        if host not in HOSTS or action not in MUTATIONS | {'snapshot', 'verify', 'sample'}:
            raise ValueError('Unsupported remote scope')
        self.mutation_guard()
        request = {'schema_version': 1, 'action': action, 'run_id': self.summary['run_id'], 'host': host}
        operation = self.root / 'remote' / (action + '-' + host + '-' + uuid.uuid4().hex[:10])
        operation.mkdir(mode=0o700)
        code = (self.repo / 'tools/ntp-onepass-remote.py').read_text(encoding='utf-8')
        if sha256(code.encode('utf-8')) != self.remote_source_hash:
            raise ValueError('Remote engine differs from the bound reviewed source')
        payload = ('import json\n_scope = {"__name__": "fds_onepass_remote"}\n'
                   + 'exec(compile(' + repr(code) + ', "ntp-onepass-remote.py", "exec"), _scope)\n'
                   + 'raise SystemExit(_scope["main"](json.loads(' + repr(json.dumps(request)) + ')))\n')
        (operation / 'stdin.py').write_text(payload)
        command = {'argv': ['/usr/bin/python3', '-I', '-B', '-'], 'stdin': payload, 'stdin_add_newline': False}
        write_json(operation / 'REQUEST.json', request)
        rawdir = operation / 'ansible-results'
        rawdir.mkdir(mode=0o700)
        result = self.run_command(action + '-' + host, ['ansible', host, '-i', str(self.root / 'inventory.json'),
                    '--become', '-m', 'ansible.builtin.command', '-a', json.dumps(command), '--tree', str(rawdir)],
                    timeout=360 if action == 'snapshot' else 180)
        if any(result.get(k) for k in ('timed_out', 'interrupted', 'output_limit')):
            raise StateUncertain(action + '/' + host + ': transport interrupted; preserve journals')
        try:
            _, raw = read_json_bytes(rawdir / host)
            if (not isinstance(raw, dict) or raw.get('unreachable') or raw.get('skipped')
                    or type(raw.get('rc')) is not int or raw['rc'] not in (0, 2)):
                raise ValueError('No completed remote command')
            value = json.loads(raw['stdout'], object_pairs_hook=unique_object)
            if (not isinstance(value, dict) or value.get('schema_version') != 1 or
                    any(value.get(key) != item for key, item in request.items()) or
                    value.get('status') not in ('OK', 'STOP') or
                    (value['status'] == 'OK') != (raw['rc'] == 0)):
                raise ValueError('Remote response binding/status mismatch')
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise StateUncertain(action + '/' + host + ': no valid bound response; preserve journals') from exc
        write_json(operation / 'RESPONSE.json', value)
        receipt = value.get('journal_receipt', {})
        if isinstance(receipt, dict) and any(isinstance(op, dict) and op.get('state') in ('PREPARED', 'REMOVE_PREPARED', 'UNCERTAIN')
                                            for op in receipt.get('operations', [])):
            raise StateUncertain(action + '/' + host + ': journal contains unresolved mutation intent; preserve it')
        with self.thread_lock:
            self.remote_results.append({'action': action, 'host': host, 'response': value,
                                        'path': str(operation.relative_to(self.root))})
            write_json(self.root / 'REMOTE_RESULTS.json', self.remote_results)
        self.mutation_guard()
        return value

    def require_ok(self, action, host):
        result = self.remote(action, host)
        if result['status'] != 'OK':
            raise ValueError(action + '/' + host + ': remote STOP; see retained response')
        return result

    def rollback_confirmed(self, action, host):
        self.summary['scoped_rollback'] = {'action': action, 'host': host, 'status': 'STARTED'}
        try:
            result = self.remote(action, host)
            self.summary['scoped_rollback']['status'] = result['status']
        except Exception as exc:
            self.summary['scoped_rollback'].update(status='REVIEW_REQUIRED', error=str(exc))
            if isinstance(exc, (StateUncertain, OnePassInterrupted)):
                self.summary['uncertain'] = True

    def write_preparation(self):
        preparation = {'schema_version': 1, 'run_id': self.summary['run_id'],
                       'prepared_at': now(), 'source': self.input,
                       'operator_supplied_governance_refs': {
                           'network_policy_ref': self.input['network_policy_ref'],
                           'recovery_ref': self.input['recovery_ref']},
                       'approval_generated': False, 'ingress': 'VERIFIED',
                       'egress': 'DEFERRED_UNTIL_COMPLETE_ROLLOUT',
                       'remote_evidence': 'REMOTE_RESULTS.json',
                       'scope': 'control01 ingress + six-host NTP-only egress; existing non-NTP rules retained'}
        write_json(self.root / 'PREPARATION.json', preparation)
        recovery = {'schema_version': 1, 'run_id': self.summary['run_id'],
                    'actual_recovery_reference': self.input['recovery_ref'],
                    'snapshots': 'REMOTE_RESULTS.json',
                    'journal': 'Remote engine retains exact owned additions per host and run_id',
                    'rules': ['Before child starts, confirmed ingress failure rolls back only owned additions.',
                              'A partial rollout preserves source/client successes and shared ingress.',
                              'Confirmed egress failure rolls back only that host owned additions.',
                              'Uncertain transport, journal or source binding never triggers broad rollback.',
                              'Restore original permitted NTP route before explicit chrony baseline rollback.'],
                    'full_runtime_recovery_test': 'NOT_RUN'}
        write_json(self.root / 'RECOVERY.json', recovery)
        # Bind actual freshly generated records while retaining the external policy
        # and recovery references above. A path is evidence, never an approval.
        child_input = {key: value for key, value in self.input.items() if key != 'reviewed_wrapper_sha'}
        child_input['network_policy_ref'] = str(self.root / 'PREPARATION.json')
        child_input['recovery_ref'] = str(self.root / 'RECOVERY.json')
        write_json(self.root / 'RUNTIME_INPUT.json', child_input)
        (self.root / 'RUNTIME_INPUT.json').chmod(0o400)
        self.child_input = child_input
        self.child_input_hash = sha256((self.root / 'RUNTIME_INPUT.json').read_bytes())

    def validate_child(self, child_root, record):
        child_root = Path(child_root)
        if record['returncode'] != 0 or any(record.get(k) for k in ('timed_out', 'interrupted', 'output_limit')):
            raise ValueError('Approved rollout failed or was interrupted; egress was not started')
        _, result = read_json_bytes(child_root / 'RESULT.json')
        _, source = read_json_bytes(child_root / 'SOURCE.json')
        raw, child_input = read_json_bytes(child_root / 'RUNTIME_INPUT.json')
        if (result.get('status') != 'ROLLOUT_COMPLETED_REVIEW_REQUIRED' or
                result.get('apply_requested') is not True or result.get('source_applied') is not True or
                result.get('source_phase_started') is not True or result.get('clients_started') is not True or
                result.get('wrapper_finalize') != 'COMPLETED' or result.get('error') or
                result.get('reviewed_source_sha') != ROLLOUT_SHA or
                result.get('input_sha256') != self.child_input_hash or
                result.get('run_id') != child_root.name or
                result.get('source_checkout') != str(self.rollout_repo) or
                source != {'head': ROLLOUT_SHA, 'tree': ROLLOUT_TREE, 'clean': True} or
                sha256(raw) != self.child_input_hash or child_input != self.child_input or
                (child_root / 'SOURCE_BINDING_INVALID.json').exists() or
                (child_root / 'wrapper/SOURCE_BINDING_INVALID').exists()):
            raise ValueError('Child success/source/input binding is incomplete; egress was not started')
        _, commands = read_json_bytes(child_root / 'COMMANDS.json')
        if not isinstance(commands, list):
            raise ValueError('Child command records are missing')
        for phase in ('precheck', 'diagnose', 'source', 'pathcheck', 'clients', 'verify', 'finalize'):
            found = [item for item in commands if isinstance(item, dict) and item.get('phase') == phase]
            if len(found) != 1 or found[0].get('returncode') != 0 or any(found[0].get(k) for k in ('timed_out', 'interrupted')):
                raise ValueError('Child phase did not complete successfully: ' + phase)
        helper = load_tool('ntp_onepass_approved_rollout', self.rollout_repo / 'tools/ntp-rollout.py')
        # Validation must not overwrite the original child evidence/manifest.
        helper.write_json = lambda path, value: write_json(self.root / ('CHILD_' + Path(path).name), value)
        validator = helper.Rollout(argparse.Namespace(apply=True), repo_root=self.rollout_repo)
        validator.root = child_root
        validator.input = self.child_input
        validator.input_hash = self.child_input_hash
        validator.summary['run_id'] = child_root.name
        for gate in ('diagnose', 'pathcheck'):
            validator.validate_receipts(gate)
        write_json(self.root / 'CHILD_VALIDATION.json', {'status': 'COMPLETE_ROLLOUT_VALIDATED',
                   'child_directory': str(child_root), 'result_sha256': sha256((child_root / 'RESULT.json').read_bytes()),
                   'input_sha256': self.child_input_hash})

    def run_child(self):
        self.mutation_guard()
        raw, value = read_json_bytes(self.root / 'RUNTIME_INPUT.json')
        if sha256(raw) != self.child_input_hash or value != self.child_input:
            raise ValueError('Generated runtime input changed before child invocation')
        parent = self.root / 'child'
        if list(parent.iterdir()):
            raise ValueError('Child evidence parent must be fresh')
        self.summary['child_started'] = True
        record = self.run_command('approved-rollout', [sys.executable, '-I', '-B',
                    str(self.rollout_repo / 'tools/ntp-rollout.py'), '--apply', '--runtime-input',
                    str(self.root / 'RUNTIME_INPUT.json'), '--evidence-parent', str(parent)], timeout=5400)
        self.mutation_guard()
        if any(record.get(k) for k in ('timed_out', 'interrupted', 'output_limit')):
            raise StateUncertain('Approved rollout did not return a complete outcome; preserve all host states')
        directories = [path for path in parent.iterdir() if path.is_dir() and not path.is_symlink()]
        if len(directories) != 1 or not directories[0].name.startswith('ansible-ntp-rollout-'):
            raise ValueError('Child evidence location ambiguous; egress was not started')
        self.validate_child(directories[0], record)
        self.summary['child_status'] = 'COMPLETE_ROLLOUT_VALIDATED'

    def post_egress_gates(self):
        self.mutation_guard()
        gate_root = self.root / 'post-egress'
        gate_root.mkdir(mode=0o700)
        (gate_root / 'gates').mkdir(mode=0o700)
        run_id = self.summary['run_id'] + '-post'
        variables = {'cr_ntp_migrate_main': True, 'cr_ntp_source_upstreams': UPSTREAMS,
                     'cr_ntp_probe_evidence_dir': str(gate_root / 'gates'), 'cr_ntp_probe_run_id': run_id,
                     'cr_ntp_probe_source_head': ROLLOUT_SHA, 'cr_ntp_probe_input_sha256': self.child_input_hash}
        write_json(gate_root / 'ANSIBLE_VARS.json', variables)
        bound = sha256((gate_root / 'ANSIBLE_VARS.json').read_bytes())
        helper = load_tool('ntp_onepass_postgate', self.rollout_repo / 'tools/ntp-rollout.py')
        validator = helper.Rollout(argparse.Namespace(apply=False), repo_root=self.rollout_repo)
        validator.root, validator.input, validator.input_hash = gate_root, self.child_input, self.child_input_hash
        validator.summary['run_id'] = run_id
        environment = dict(self.env, ANSIBLE_CONFIG=str(self.rollout_repo / 'ansible.cfg'))
        for gate in ('diagnose', 'pathcheck'):
            self.mutation_guard()
            if sha256((gate_root / 'ANSIBLE_VARS.json').read_bytes()) != bound:
                raise ValueError('Post-egress probe inputs changed')
            self.command_ok('post-egress-' + gate, ['ansible-playbook', '-i',
                    str(self.rollout_repo / 'inventory/hosts.yml'), '-e', '@' + str(gate_root / 'ANSIBLE_VARS.json'),
                    str(self.rollout_repo / 'playbooks' / ('cr-p1-ntp-01-01-' + gate + '.yml'))],
                    timeout=900, env=environment)
            self.mutation_guard()
            validator.validate_receipts(gate)
        self.summary['post_egress_positive_gates'] = 'PASSED'

    def sample_all(self):
        samples = []
        first = time.monotonic()
        previous_completed = None
        for index in range(6):
            # Wait after all prior host observations complete. Batch-start spacing
            # alone could sample a slow host then a fast host less than 60s apart.
            target = first if previous_completed is None else previous_completed + 60
            while time.monotonic() < target:
                time.sleep(min(0.5, target - time.monotonic()))
            self.mutation_guard()
            started = time.monotonic()
            values = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                futures = {pool.submit(self.require_ok, 'sample', host): host for host in HOSTS}
                for future in concurrent.futures.as_completed(futures):
                    value = future.result()
                    if value.get('details', {}).get('pass') is not True:
                        raise ValueError('Sample lacks an explicit successful source/offset observation')
                    values[futures[future]] = value
            previous_completed = time.monotonic()
            samples.append({'sample': index + 1, 'observed_at': now(),
                            'started_monotonic': started, 'completed_monotonic': previous_completed,
                            'batch_elapsed_seconds': previous_completed - started, 'hosts': values})
            write_json(self.root / 'SAMPLES.json', {'interval_seconds_minimum': 60, 'required_samples': 6,
                                                  'samples': samples, 'status': 'COLLECTING' if index < 5 else 'PASSED'})
        self.summary['time_samples'] = 'SIX_PASSED_60S_MINIMUM_INTERVAL'

    def execute_pipeline(self):
        for host in HOSTS:
            self.require_ok('snapshot', host)
        if not self.args.apply:
            self.summary['status'] = 'SNAPSHOTS_COLLECTED_NOT_APPLIED'
            return
        self.mutation_guard()
        result = self.remote('ingress', SOURCE)
        if result['status'] != 'OK':
            self.rollback_confirmed('rollback_ingress', SOURCE)
            raise ValueError('Ingress preparation stopped; approved rollout was not started')
        self.summary['ingress_ready'] = True
        self.write_preparation()
        self.run_child()
        for host in HOSTS:
            self.mutation_guard()
            result = self.remote('egress', host)
            if result['status'] != 'OK':
                self.rollback_confirmed('rollback_egress', host)
                raise ValueError('Egress failed on ' + host + '; later hosts were not modified')
            self.summary['egress_completed'].append(host)
        for host in HOSTS:
            self.require_ok('verify', host)
        self.post_egress_gates()
        self.sample_all()
        self.summary['status'] = 'ONEPASS_COMPLETED_REVIEW_REQUIRED'

    def package(self):
        self.summary['ended_at'] = now()
        write_json(self.root / 'RESULT.json', self.summary)
        write_json(self.root / 'COMMANDS.json', self.records)
        files = []
        for path in sorted(self.root.rglob('*')):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('Unexpected evidence entry')
            if path.is_file() and path != self.root / 'SHA256SUMS':
                files.append(path)
        (self.root / 'SHA256SUMS').write_text(''.join(sha256(p.read_bytes()) + '  ' + str(p.relative_to(self.root)) + '\n' for p in files))
        archive = self.root.with_suffix('.tar.gz')
        with tarfile.open(archive, 'w:gz', dereference=False) as stream:
            stream.add(self.root, arcname=self.root.name, recursive=True)
        archive.chmod(0o600)
        sidecar = Path(str(archive) + '.sha256')
        sidecar.write_text(sha256(archive.read_bytes()) + '  ' + archive.name + '\n')
        sidecar.chmod(0o600)
        print('STATUS=' + self.summary['status'] + '\nHOME_EVIDENCE=' + str(archive) + '\nSHA256_SIDECAR=' + str(sidecar), flush=True)

    def run(self):
        rc = 1
        try:
            self.create_evidence()
            self.prepare()
            self.execute_pipeline()
            self.mutation_guard()
            rc = 0
        except (Exception, KeyboardInterrupt) as exc:
            self.summary.update(status='STOPPED_REVIEW_REQUIRED', error=str(exc) or type(exc).__name__,
                                uncertain=bool(self.summary.get('uncertain')) or isinstance(exc, (StateUncertain, OnePassInterrupted, KeyboardInterrupt)))
        finally:
            with self.thread_lock:
                active = list(self.active_processes.values())
            for process in active:
                self.stop_process(process)
            try:
                if self.root is not None:
                    self.package()
            finally:
                if self.lock_fd is not None:
                    os.close(self.lock_fd)
                    self.lock_fd = None
        return rc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollout-repo', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--evidence-parent', type=Path)
    parser.add_argument('--apply', action='store_true', help='Apply the independently reviewed wrapper scope')
    args = parser.parse_args()
    if not args.rollout_repo.is_absolute():
        parser.error('--rollout-repo must be an absolute path to the fixed approved checkout')
    os.umask(0o077)

    controller = OnePass(args)

    def interrupted(number, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        # Stop worker groups before ThreadPoolExecutor waits for its futures.
        # Copy without acquiring a lock: a signal may interrupt the lock owner.
        for process in controller.active_processes.copy().values():
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        raise OnePassInterrupted('Interrupted by signal ' + str(number))

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        return controller.run()
    except Exception as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
