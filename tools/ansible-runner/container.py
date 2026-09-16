import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import URL, VERSION, now, packet, read_regular, require, write
from proxy import relay

SESSION = Path('/session')
RESULT = SESSION / 'CONTAINER_RESULT.json'
EVENTS = SESSION / 'EVENTS.jsonl'
RUNNER = SESSION / 'runner'


def event(stage, **values):
    record = dict(at=now(), stage=stage, **values)
    with EVENTS.open('a') as handle:
        handle.write(json.dumps(record) + '\n')
    print(json.dumps(record), flush=True)


class BridgeHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
                peer.settimeout(30)
                peer.connect('/proxy/connect.sock')
                self.request.settimeout(30)
                relay(self.request, peer)
        except OSError:
            pass


class Bridge(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = False
    slots = threading.BoundedSemaphore(32)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def shm_checks(mountinfo, stats):
    """Require only the dedicated, bounded, hardened writable shared memory mount."""
    rows = [line.split(' - ', 1) for line in mountinfo.splitlines() if ' - ' in line]
    rows = [(left.split(), right.split()) for left, right in rows]
    rows = [(left, right) for left, right in rows if len(left) >= 6 and len(right) >= 3 and left[4] == '/dev/shm']
    if len(rows) != 1:
        return dict.fromkeys(('shm-tmpfs', 'shm-writable', 'shm64m', 'shm-hardening'), False)
    left, right = rows[0]
    options = set(left[5].split(',')) | set(right[2].split(','))
    return {
        'shm-tmpfs': right[0] == 'tmpfs',
        'shm-writable': not bool(stats.f_flag & os.ST_RDONLY) and 'rw' in options and 'ro' not in options,
        'shm64m': stats.f_frsize * stats.f_blocks == 64 * 1024**2,
        'shm-hardening': {'nosuid', 'nodev', 'noexec'} <= options,
    }


def ipc_preflight():
    result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).with_name('ipc_probe.py'))],
                            text=True, capture_output=True, timeout=20)
    return result.returncode == 0 and result.stdout.strip() == 'PASS_IPC'


def isolation():
    values = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    interfaces = {line.split(':', 1)[0].strip() for line in Path('/proc/net/dev').read_text().splitlines() if ':' in line}
    checks = {
        'uid-gid': os.getuid() == 1000 and os.getgid() == 1000,
        'cap-effective-zero': int(values['CapEff'].strip(), 16) == 0,
        'cap-bounding-zero': int(values['CapBnd'].strip(), 16) == 0,
        'no-new-privileges': values['NoNewPrivs'].strip() == '1',
        'seccomp': values['Seccomp'].strip() == '2',
        'selinux-container-domain': ':container_t:' in Path('/proc/self/attr/current').read_text(),
        'network-only-loopback': interfaces == {'lo'},
        'root-readonly': bool(os.statvfs('/').f_flag & os.ST_RDONLY),
        'socket-mount-readonly': bool(os.statvfs('/proxy').f_flag & os.ST_RDONLY),
        'memory4g': Path('/sys/fs/cgroup/memory.max').read_text().strip() == str(4*1024**3),
        'pids512': Path('/sys/fs/cgroup/pids.max').read_text().strip() == '512',
        'cpu2': Path('/sys/fs/cgroup/cpu.max').read_text().split() == ['200000', '100000'],
    }
    checks.update(shm_checks(Path('/proc/self/mountinfo').read_text(), os.statvfs('/dev/shm')))
    for host in ('1.1.1.1', '10.1.93.102'):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            try:
                blocked = s.connect_ex((host, 443)) != 0
            except OSError:
                blocked = True
            checks['direct-network-blocked-' + host] = blocked
    write(SESSION / 'ISOLATION.json', {'checks': checks, 'passed': all(checks.values())})
    require(all(checks.values()), 'Container isolation check failed')


def probe():
    results = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': 'http://127.0.0.1:3128'}))
    for url in ('https://api.github.com/', 'https://github.com/', 'https://pypi.org/simple/ansible-core/',
                'https://files.pythonhosted.org/'):
        status = None
        try:
            request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'fds-runner-prepare'})
            with opener.open(request, timeout=30) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code  # TLS transport, not an authenticated API/CI success assertion.
        except (urllib.error.URLError, OSError):
            pass  # Keep a failed row so failure evidence retains the complete target list.
        results.append({'target': url, 'tls_http_reached': type(status) is int and 200 <= status < 500, 'status': status})
    for host in ('10.1.93.102', '169.254.169.254', 'example.com', 'github.com.evil.invalid'):
        line = b''
        try:
            with socket.create_connection(('127.0.0.1', 3128), timeout=10) as client:
                client.sendall(f'CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n'.encode())
                line = client.recv(512).split(b'\r\n', 1)[0]
        except OSError:
            pass
        results.append({'target': host, 'denied': line == b'HTTP/1.1 403 Forbidden'})
    good = all(row.get('tls_http_reached', row.get('denied', False)) for row in results)
    write(SESSION / 'NETWORK_PROBE.json', {'passed': good, 'results': results,
                                         'scope': 'TLS transport + deny behavior; no registration/job'})
    require(good, 'Proxy network probe failed')


def runner_env(token=None):
    env = {'HOME': '/session/home', 'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
           'TMPDIR': '/session/tmp', 'DOTNET_CLI_TELEMETRY_OPTOUT': '1',
           'http_proxy': 'http://127.0.0.1:3128', 'https_proxy': 'http://127.0.0.1:3128',
           'HTTP_PROXY': 'http://127.0.0.1:3128', 'HTTPS_PROXY': 'http://127.0.0.1:3128',
           'no_proxy': 'localhost,127.0.0.1,::1', 'NO_PROXY': 'localhost,127.0.0.1,::1',
           'RUNNER_MANUALLY_TRAP_SIG': '1'}
    if token is not None:
        env['ACTIONS_RUNNER_INPUT_TOKEN'] = token
    return env


def native(args, stage, token=None, timeout=180):
    # Runner-native output and _diag can contain runtime credentials. They stay in
    # the disposable workspace, are not exported, and are destroyed on cleanup.
    with (SESSION / (stage + '.private.log')).open('wb') as handle:
        process = subprocess.run(args, cwd=RUNNER, env=runner_env(token), stdin=subprocess.DEVNULL,
                                 stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
    event(stage, rc=process.returncode, native_output='EXCLUDED_PRIVATE_WORKSPACE')
    return process.returncode


def registered_identity(path, name, checks):
    # Runner v2.337.0 IOUtil.SaveObject writes Encoding.UTF8 (with a BOM).
    # Keep strict UTF-8/JSON and identity validation; only the leading BOM is optional.
    raw = read_regular(path, 32768)
    checks['utf8_bom'] = raw.startswith(b'\xef\xbb\xbf')
    metadata = json.loads(raw.decode('utf-8-sig'))
    checks['json_parsed'] = True
    checks['object'] = type(metadata) is dict
    require(checks['object'], 'Runner settings must be an object')
    url, identifier = metadata.get('gitHubUrl'), metadata.get('agentId')
    checks['url_matches'] = type(url) is str and url.rstrip('/') == URL
    checks['name_matches'] = metadata.get('agentName') == name
    checks['id_valid'] = type(identifier) is int and 0 < identifier < 2**53
    require(all(checks[key] for key in ('url_matches', 'name_matches', 'id_valid')),
            'Registered identity differs')
    return {'agentId': identifier, 'agentName': name, 'gitHubUrl': URL}


def session_run():
    completed = False
    job_result = None
    process = subprocess.Popen(['/bin/bash', './run.sh'], cwd=RUNNER, env=runner_env(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        # Only emit recognized state transitions, never the source line/job name.
        for raw in iter(lambda: process.stdout.readline(8193), b''):
            if len(raw) > 8192:
                continue
            line = raw.decode('utf-8', errors='replace')
            if 'Listening for Jobs' in line:
                event('listening')
            elif 'Running job:' in line:
                event('job-started')
            match = re.search(r'Job .+ completed with result: (Succeeded|Failed|Canceled|Skipped)\s*$', line)
            if match:
                completed, job_result = True, match[1]
                event('job-finished', reported_result=job_result)
        rc = process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdout.close()
    return rc, completed, job_result


def main():
    os.umask(0o077)
    mode = sys.argv[1] if len(sys.argv) == 2 else ''
    require(mode in ('prepare', 'registration-check', 'serve'), 'Invalid mode')
    record = {'mode': mode, 'status': 'FAIL', 'started_at': now(), 'github_actions_verdict': 'NOT_ASSESSED'}
    bridge = None
    secret = None
    removal_attempted = False
    phase = 'isolation'
    try:
        require(ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0, 'Cannot disable controller memory dumping')
        isolation()
        phase = 'ipc-preflight'
        record['ipc_preflight_passed'] = ipc_preflight()
        require(record['ipc_preflight_passed'], 'Multiprocessing preflight failed')
        bridge = Bridge(('127.0.0.1', 3128), BridgeHandler)
        threading.Thread(target=bridge.serve_forever, daemon=True).start()
        for name in ('home', 'tmp'):
            (SESSION / name).mkdir(mode=0o700)
        shutil.copytree('/opt/runner', RUNNER)
        os.chmod(RUNNER, 0o700)
        phase = 'listener-version'
        version = subprocess.run([str(RUNNER / 'bin/Runner.Listener'), '--version'], cwd=RUNNER,
                                 env=runner_env(), text=True, capture_output=True, timeout=30)
        record['listener_version_matches'] = version.returncode == 0 and version.stdout.strip() == VERSION
        # Before any credential is read, diagnostics are safe and useful for missing dependencies.
        if not record['listener_version_matches']:
            event('listener-version-failed', rc=version.returncode, detail=version.stderr[-4096:])
        require(record['listener_version_matches'], 'Runner.Listener version/dependency test failed')
        if mode == 'prepare':
            phase = 'network-probe'
            probe()
            record['status'] = 'PASS_PREPARE_CONTAINER'
            return 0
        phase = 'token-packet'
        secret = packet(json.loads(sys.stdin.buffer.readline(8193)))
        require(len(sys.stdin.buffer.read(1)) == 0, 'Unexpected token packet suffix')
        name = os.environ['FDS_RUNNER_NAME']
        require(re.fullmatch(r'ansible-ci-[0-9a-f]{32}', name), 'Invalid fresh Runner name')
        phase = 'configure'
        rc = native(['/bin/bash', './config.sh', '--unattended', '--url', URL, '--name', name,
                     '--work', '_work', '--labels', 'fds-ci,ansible-isolated', '--ephemeral', '--disableupdate'],
                    'configure', secret['registration']['token'])
        record['configure_rc'] = rc
        require(rc == 0, 'Runner configuration failed; private native logs excluded')
        phase = 'registered-identity'
        record['identity_checks'] = {}
        record['runner'] = registered_identity(RUNNER / '.runner', name, record['identity_checks'])
        event('configured', id=record['runner']['agentId'], name=name)
        if mode == 'serve':
            phase = 'listener-session'
            rc, completed, reported = session_run()
            record.update(listener_rc=rc, job_finished_observed=completed, reported_job_result=reported,
                          status='SESSION_ENDED' if rc == 0 else 'FAIL', github_actions_verdict='VERIFY_RUN_AND_ARTIFACT')
            # Ephemeral completion deregisters itself. Failure or early termination
            # may leave a record; management-host API observation is still required.
            record['deregistration'] = 'REQUIRES_MANAGEMENT_API_CHECK'
            return 0 if rc == 0 and completed else 1
        phase = 'remove'
        removal_attempted = True
        removal = native(['/bin/bash', './config.sh', 'remove', '--unattended'], 'remove', secret['removal']['token'])
        record['remove_rc'] = removal
        require(removal == 0, 'Runner removal failed; retain exact ID for management-host cleanup')
        record['status'] = 'PASS_REGISTRATION_CHECK'
        return 0
    except BaseException as exc:
        record['failure_phase'] = phase
        record['error_type'] = type(exc).__name__
        # Fixed messages only. Never serialize arbitrary exceptions containing credentials.
        event('failed', error_type=type(exc).__name__)
        return 1
    finally:
        if mode == 'registration-check' and secret and not removal_attempted and (RUNNER / '.runner').is_file():
            try:
                record['remove_rc'] = native(['/bin/bash', './config.sh', 'remove', '--unattended'],
                                             'remove', secret['removal']['token'])
            except BaseException:
                record['remove_rc'] = None
            # An earlier failure remains FAIL even if recovery removal succeeds.
        record['ended_at'] = now()
        write(RESULT, record)
        if bridge:
            bridge.shutdown()
            bridge.server_close()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
