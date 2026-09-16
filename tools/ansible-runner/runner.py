"""Dedicated-user controller. Container data never determines host commands."""
import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ACCOUNT, ARCHIVE, BASE, BASE_ID, GID, HOST_PATH, REPO,
                    RUNNER_BYTES, RUNNER_SHA, RUNNER_URL, UID, URL, VERIFY_HOME,
                    VERSION, digest, image_id, manifest, now, packet,
                    read_regular, require, write)

ROOT = Path(__file__).resolve().parent
MODES = ('prepare', 'registration-check', 'serve')
STATES = {'prepare': 'PASS_PREPARE', 'registration-check': 'PASS_REGISTRATION_CHECK',
          'serve': 'SESSION_ENDED_REQUIRES_CI_REVIEW'}
ISOLATION_KEYS = {'uid-gid', 'cap-effective-zero', 'cap-bounding-zero', 'no-new-privileges',
                  'seccomp', 'selinux-container-domain', 'network-only-loopback', 'root-readonly',
                  'socket-mount-readonly', 'memory4g', 'pids512', 'cpu2',
                  'direct-network-blocked-1.1.1.1', 'direct-network-blocked-10.1.93.102'}
PROBE_ALLOW = ('https://api.github.com/', 'https://github.com/', 'https://pypi.org/simple/ansible-core/',
               'https://files.pythonhosted.org/')
PROBE_DENY = ('10.1.93.102', '169.254.169.254', 'example.com', 'github.com.evil.invalid')


def podman_command(kind, image, run, name, mode):
    require(kind in ('proxy', 'runner') and mode in MODES, 'Invalid container kind/mode')
    image = image_id(image)
    command = ['podman', 'run', '--cidfile', str(run / (kind + '.cid')), '--name', name + '-' + kind,
               '--pull=never', '--userns=keep-id:uid=1000,gid=1000', '--user', '1000:1000',
               '--cap-drop=ALL', '--security-opt=no-new-privileges', '--read-only',
               '--read-only-tmpfs=false', '--log-driver=none', '--stop-timeout=15']
    if kind == 'proxy':
        return command + ['--network=pasta', '--cpus=0.25', '--memory=256m', '--memory-swap=256m',
                          '--pids-limit=128', '--volume', str(run / 'proxy') + ':/proxy:rw,z',
                          '--workdir=/proxy', '--entrypoint=/usr/local/bin/python3', '-d',
                          image, '-I', '-B', '/opt/fds/proxy.py']
    return command + ['--network=none', '--cpus=2', '--memory=4g', '--memory-swap=4g',
                      '--pids-limit=512', '--volume', str(run / 'session') + ':/session:rw,Z',
                      '--volume', str(run / 'proxy') + ':/proxy:ro,z',
                      '--env', 'FDS_RUNNER_NAME=' + name, '-i', image, mode]


def clean_result(value, mode, name):
    """Allowlist fields; untrusted jobs cannot export native logs or arbitrary strings."""
    require(type(value) is dict and value.get('mode') == mode, 'Missing/mismatched container result')
    allowed = {'FAIL', 'PASS_PREPARE_CONTAINER', 'PASS_REGISTRATION_CHECK', 'SESSION_ENDED'}
    out = {'mode': mode, 'status': value.get('status') if value.get('status') in allowed else 'FAIL'}
    for key in ('listener_version_matches', 'job_finished_observed'):
        out[key] = value.get(key) is True
    for key in ('configure_rc', 'remove_rc', 'listener_rc'):
        v = value.get(key)
        out[key] = v if type(v) is int and -255 <= v <= 255 else None
    v = value.get('reported_job_result')
    out['reported_job_result'] = v if v in ('Succeeded', 'Failed', 'Canceled', 'Skipped') else None
    identity = value.get('runner', {})
    if isinstance(identity, dict) and identity.get('gitHubUrl') == URL and identity.get('agentName') == name:
        identifier = identity.get('agentId')
        if type(identifier) is int and 0 < identifier < 2**53:
            out['runner'] = {'agentId': identifier, 'agentName': name, 'gitHubUrl': URL}
    out['github_actions_verdict'] = 'NOT_RUN' if mode != 'serve' else 'VERIFY_RUN_AND_ARTIFACT'
    return out


def container_ok(mode, value, rc, state, checks, probe=None):
    if (type(rc) is not int or rc != 0 or state.get('Status') != 'exited'
            or type(state.get('ExitCode')) is not int or state['ExitCode'] != 0
            or state.get('OOMKilled') is not False or not value.get('listener_version_matches')
            or set(checks) != ISOLATION_KEYS or not all(v is True for v in checks.values())):
        return False
    if mode == 'prepare':
        return value.get('status') == 'PASS_PREPARE_CONTAINER' and probe is True
    if 'runner' not in value or value.get('configure_rc') != 0:
        return False
    if mode == 'registration-check':
        return value.get('status') == 'PASS_REGISTRATION_CHECK' and value.get('remove_rc') == 0
    return (value.get('status') == 'SESSION_ENDED' and value.get('listener_rc') == 0
            and value.get('job_finished_observed') is True)


def clean_probe(value):
    rows = value.get('results', [])
    require(type(rows) is list and len(rows) == 8, 'Network probe count differs')
    result = []
    for row, target in zip(rows, PROBE_ALLOW + PROBE_DENY):
        require(type(row) is dict and row.get('target') == target, 'Network probe target differs')
        if target in PROBE_ALLOW:
            code = row.get('status')
            good = row.get('tls_http_reached') is True and type(code) is int and 200 <= code < 500
            result.append({'target': target, 'status': code if type(code) is int else None, 'passed': good})
        else:
            result.append({'target': target, 'passed': row.get('denied') is True})
    return {'passed': value.get('passed') is True and all(x['passed'] for x in result), 'results': result}


def prepared_image(path, bundle):
    path = Path(path)
    require(path.parent.name == 'evidence' and path.name == 'PREPARED.json'
            and path.parent.parent.parent == VERIFY_HOME
            and re.fullmatch('ansible-actions-[0-9a-f]{32}', path.parent.parent.name)
            and not any(p.is_symlink() for p in (path, *path.parents)), 'Invalid prepared artifact path')
    value = json.loads(read_regular(path, owner=UID))
    require(value.get('status') == 'PASS_PREPARE' and value.get('bundle_sha256') == bundle
            and value.get('repository') == REPO and value.get('runner_version') == VERSION
            and value.get('container_cleanup') == 'REMOVED', 'Prepared artifact binding differs')
    return image_id(value['image_id'])


class Controller:
    def __init__(self, run, mode, bundle):
        self.run, self.mode, self.bundle = run, mode, bundle
        self.evidence = run / 'evidence'
        self.private = run / 'private'
        self.name = 'ansible-ci-' + uuid.uuid4().hex
        self.commands = []

    def command(self, label, args, timeout=120, payload=None):
        require(payload is None or label == 'container', 'Secret input destination differs')
        print('STAGE=' + label, flush=True)
        item = {'stage': label, 'command': args, 'rc': None}
        self.commands.append(item)
        with (self.private / (label + '.log')).open('wb') as log:
            process = subprocess.Popen(args, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + timeout
            try:
                first = True
                while True:
                    try:
                        process.communicate(input=payload if first else None, timeout=min(30, max(0.1, deadline-time.monotonic())))
                        break
                    except subprocess.TimeoutExpired:
                        first = False
                        require(time.monotonic() < deadline, 'Stage timeout: ' + label)
                        print('WAIT=' + label, flush=True)
                item['rc'] = process.returncode
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        return item['rc']

    def output(self, label, args, maximum=1024*1024):
        require(self.command(label, args) == 0, 'Command failed: ' + label)
        return read_regular(self.private / (label + '.log'), maximum).decode('utf-8')

    def inspect_image(self, image):
        items = json.loads(self.output('image-inspect', ['podman', 'image', 'inspect', image]))
        require(type(items) is list and len(items) == 1, 'Image inspect count differs')
        value = items[0]
        require(image_id(value['Id']) == image_id(image) and value.get('Architecture') == 'amd64'
                and value.get('Os') == 'linux' and value.get('Config', {}).get('Labels', {}).get('io.fds.bundle') == self.bundle,
                'Image ID/platform/bundle label differs')
        return {'id': image_id(image), 'bundle_sha256': self.bundle, 'architecture': 'amd64', 'os': 'linux'}

    def build(self):
        base = json.loads(self.output('base-inspect', ['podman', 'image', 'inspect', BASE]))
        require(len(base) == 1 and image_id(base[0]['Id']) == BASE_ID
                and base[0].get('Architecture') == 'amd64' and base[0].get('Os') == 'linux',
                'Pinned r3 base image is absent or differs')
        context = self.run / 'build'
        context.mkdir(mode=0o700)
        archive = context / 'runner.tar.gz'
        print('STAGE=runner-download', flush=True)
        with urllib.request.urlopen(RUNNER_URL, timeout=60) as source, archive.open('xb') as out:
            require(source.geturl().startswith('https://'), 'Runner redirect must use HTTPS')
            count = 0
            last_update = time.monotonic()
            while True:
                data = source.read(1024*1024)
                if not data:
                    break
                count += len(data)
                require(count <= RUNNER_BYTES, 'Runner download size exceeded')
                out.write(data)
                if time.monotonic() - last_update >= 30:
                    print('WAIT=runner-download bytes=' + str(count), flush=True)
                    last_update = time.monotonic()
        require(count == RUNNER_BYTES and digest(archive) == RUNNER_SHA, 'Runner archive checksum/size mismatch')
        write(self.evidence / 'RUNNER_DOWNLOAD.json', {'url': RUNNER_URL, 'version': VERSION,
              'sha256': RUNNER_SHA, 'bytes': count, 'base': BASE, 'base_image_id': BASE_ID})
        for name in ('common.py', 'proxy.py', 'container.py'):
            shutil.copyfile(ROOT / name, context / name)
        shutil.copyfile(ROOT / 'build/Containerfile', context / 'Containerfile')
        command = ['podman', 'build', '--pull=never', '--network=none', '--build-arg', 'BASE_IMAGE=' + BASE,
                   '--label', 'io.fds.bundle=' + self.bundle, '--iidfile', str(self.run / 'image.id'), str(context)]
        require(self.command('image-build', command, 1200) == 0, 'Image build failed')
        return image_id(read_regular(self.run / 'image.id', 256).decode())

    def cid(self, kind):
        value = read_regular(self.run / (kind + '.cid'), 128).decode().strip()
        require(re.fullmatch('[0-9a-f]{64}', value), 'Invalid container ID')
        return value

    def cleanup(self):
        results = {}
        for kind in ('runner', 'proxy'):
            path = self.run / (kind + '.cid')
            if not path.exists():
                stage = 'container' if kind == 'runner' else 'proxy-start'
                attempted = any(item['stage'] == stage for item in self.commands)
                results[kind] = 'FAILED_MISSING_CID' if attempted else 'NOT_CREATED'
                continue
            try:
                identifier = self.cid(kind)
                rc = self.command(kind + '-remove', ['podman', 'rm', '--force', '--time', '15', identifier], 60)
                absent = self.command(kind + '-absent', ['podman', 'container', 'exists', identifier], 30)
                results[kind] = 'REMOVED' if rc == 0 and absent == 1 else 'FAILED'
            except (Exception, KeyboardInterrupt):
                results[kind] = 'FAILED'
        # No workspace deletion while an owned container might still run.
        if all(v in ('REMOVED', 'NOT_CREATED') for v in results.values()):
            try:
                for name in ('session', 'proxy', 'private', 'build'):
                    path = self.run / name
                    if path.exists():
                        require(not path.is_symlink() and shutil.rmtree.avoids_symlink_attacks, 'Unsafe workspace cleanup')
                        shutil.rmtree(path)
                results['workspace'] = 'REMOVED'
            except (Exception, KeyboardInterrupt):
                results['workspace'] = 'FAILED'
        else:
            results['workspace'] = 'RETAINED_CONTAINER_CLEANUP_FAILED'
        write(self.evidence / 'CLEANUP.json', results)
        return all(v in ('REMOVED', 'NOT_CREATED') for v in results.values())

    def execute(self, image, payload):
        for name in ('session', 'proxy'):
            (self.run / name).mkdir(mode=0o700)
        require(self.command('proxy-start', podman_command('proxy', image, self.run, self.name, self.mode)) == 0,
                'Proxy start failed')
        deadline = time.monotonic() + 30
        while not (self.run / 'proxy/connect.sock').exists():
            require(time.monotonic() < deadline, 'Proxy socket not ready')
            time.sleep(0.2)
        info = (self.run / 'proxy/connect.sock').lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == UID and stat.S_IMODE(info.st_mode) == 0o600,
                'Proxy socket identity differs')
        rc = self.command('container', podman_command('runner', image, self.run, self.name, self.mode),
                          3600 if self.mode == 'serve' else 600, payload)
        inspected = json.loads(self.output('container-inspect', ['podman', 'container', 'inspect', self.cid('runner')]))
        require(type(inspected) is list and len(inspected) == 1, 'Container inspect count differs')
        raw_state = inspected[0].get('State', {})
        require(image_id(inspected[0]['Image']) == image, 'Container image differs')
        state = {k: raw_state.get(k) for k in ('Status', 'ExitCode', 'OOMKilled')}
        write(self.evidence / 'CONTAINER_STATE.json', state)
        result = clean_result(json.loads(read_regular(self.run / 'session/CONTAINER_RESULT.json', 32768)), self.mode, self.name)
        write(self.evidence / 'CONTAINER_RESULT.json', result)
        raw_checks = json.loads(read_regular(self.run / 'session/ISOLATION.json', 32768)).get('checks', {})
        require(type(raw_checks) is dict, 'Invalid isolation checks')
        checks = {key: raw_checks.get(key) is True for key in sorted(ISOLATION_KEYS)}
        write(self.evidence / 'ISOLATION.json', {'checks': checks, 'passed': all(checks.values())})
        probe = None
        if self.mode == 'prepare':
            probe = clean_probe(json.loads(read_regular(self.run / 'session/NETWORK_PROBE.json', 32768)))
            write(self.evidence / 'NETWORK_PROBE.json', probe)
        return container_ok(self.mode, result, rc, state, checks, probe and probe['passed'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=MODES)
    parser.add_argument('--output', required=True)
    parser.add_argument('--prepared')
    args = parser.parse_args()
    os.umask(0o077)
    require(os.getuid() == UID and os.getgid() == GID and set(os.getgroups()) <= {GID}
            and socket.gethostname().split('.')[0] == 'cicd-runner01', 'Dedicated account/host required')
    require(ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0, 'Cannot disable controller memory dumping')
    run = Path(args.output)
    require(run.parent == VERIFY_HOME and re.fullmatch('ansible-actions-[0-9a-f]{32}', run.name)
            and not any(p.is_symlink() for p in run.parents), 'Invalid run path')
    run.mkdir(mode=0o700)
    (run / 'evidence').mkdir(mode=0o700)
    (run / 'private').mkdir(mode=0o700)
    controller = Controller(run, args.mode, '')
    record = {'status': 'FAIL', 'mode': args.mode, 'account': ACCOUNT, 'uid': UID, 'started_at': now(),
              'repository': REPO, 'runner_name': controller.name, 'github_actions_verdict': 'NOT_RUN' if args.mode != 'serve' else 'NOT_ASSESSED',
              'production_apply': False, 'engine_transition': False, 'runner_registration_attempted': False}
    lock_fd = None
    success = False
    try:
        lock_fd = os.open(VERIFY_HOME / '.ansible-actions.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bundle = manifest(ROOT)
        controller.bundle = bundle
        record['bundle_sha256'] = bundle
        require(shutil.which('pasta') is not None, 'pasta not found')
        memory = {line.split(':', 1)[0]: int(line.split()[1]) * 1024
                  for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line}
        available = memory.get('MemAvailable', 0)
        free_disk = shutil.disk_usage(VERIFY_HOME).free
        require((os.cpu_count() or 0) >= 4 and available >= 6*1024**3 and free_disk >= 8*1024**3,
                'Need >=4 logical CPUs, >=6GiB available RAM and >=8GiB home free space')
        require(controller.output('selinux', ['getenforce']).strip() == 'Enforcing', 'SELinux must be Enforcing')
        info = json.loads(controller.output('podman-info', ['podman', 'info', '--format=json']))
        host = info.get('host', {})
        require(host.get('security', {}).get('rootless') is True and host.get('cgroupVersion') == 'v2'
                and host.get('cgroupManager') == 'systemd', 'Rootless/cgroup preflight failed')
        write(controller.evidence / 'HOST_PREFLIGHT.json', {'rootless': True, 'cgroup_version': 'v2',
              'cgroup_manager': 'systemd', 'selinux': 'Enforcing', 'logical_cpus': os.cpu_count(),
              'memory_available_bytes': available, 'home_free_bytes': free_disk})
        payload = None
        if args.mode == 'prepare':
            require(args.prepared is None, 'prepare does not accept prior prepared artifact')
            image = controller.build()
        else:
            require(args.prepared, 'Verified prepare artifact required')
            image = prepared_image(args.prepared, bundle)
        record['image_id'] = image
        write(controller.evidence / 'IMAGE.json', controller.inspect_image(image))
        if args.mode != 'prepare':
            data = sys.stdin.buffer.readline(8193)
            require(len(data) <= 8192 and not sys.stdin.buffer.read(1), 'Token packet bound exceeded')
            payload = (json.dumps(packet(json.loads(data))) + '\n').encode()
            record['runner_registration_attempted'] = True
        success = controller.execute(image, payload)
    except (Exception, KeyboardInterrupt) as exc:
        record['error_type'] = type(exc).__name__
        # No arbitrary exception text in credential-bearing phases.
        if args.mode == 'prepare':
            record['prepare_error'] = str(exc)[:1024]
            for label in ('image-build', 'proxy-start', 'container'):
                file = controller.private / (label + '.log')
                if file.is_file():
                    with file.open('rb') as handle:
                        handle.seek(max(0, file.stat().st_size - 65536))
                        (controller.evidence / (label + '.prepare.log')).write_bytes(handle.read(65536))
    finally:
        cleaned = controller.cleanup()
        record['container_cleanup'] = 'REMOVED' if cleaned else 'FAILED'
        record['ended_at'] = now()
        if success and cleaned:
            record['status'] = STATES[args.mode]
            if args.mode == 'serve':
                record['github_actions_verdict'] = 'VERIFY_RUN_AND_ARTIFACT'
            if args.mode == 'prepare':
                write(controller.evidence / 'PREPARED.json', {'status': 'PASS_PREPARE', 'repository': REPO,
                      'runner_version': VERSION, 'bundle_sha256': controller.bundle,
                      'image_id': record['image_id'], 'container_cleanup': 'REMOVED', 'created_at': now()})
        write(controller.evidence / 'HOST_RUN_RESULT.json', record)
        write(controller.evidence / 'COMMANDS.json', controller.commands)
        (controller.evidence / 'SHA256SUMS').write_text(''.join(digest(p) + '  ' + p.name + '\n'
            for p in sorted(controller.evidence.iterdir()) if p.is_file()))
        archive = run / ARCHIVE
        with tarfile.open(archive, 'w:gz') as handle:
            handle.add(controller.evidence, arcname='evidence')
        (run / (ARCHIVE + '.sha256')).write_text(digest(archive) + '  ' + ARCHIVE + '\n')
        if lock_fd is not None:
            os.close(lock_fd)
        print('STATUS=' + record['status'], flush=True)
        if record['status'] == 'PASS_PREPARE':
            print('PREPARED=' + str(controller.evidence / 'PREPARED.json'), flush=True)
    return 0 if success and cleaned else 1


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
