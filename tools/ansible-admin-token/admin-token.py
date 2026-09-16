"""Management-host token issuance with fixed-field diagnostics; never logs secrets."""
import ctypes
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, packet

STEPS = ('identity', 'memory-protection', 'gh-discovery', 'repository-read',
         'registration-token', 'removal-token', 'packet-validation', 'packet-write')
SAFE_PACKET_ERRORS = {
    'Invalid token packet fields': 'PACKET_FIELDS_INVALID',
    'Token packet repository mismatch': 'PACKET_REPOSITORY_MISMATCH',
    'Invalid token record': 'TOKEN_RECORD_INVALID',
    'Invalid token format': 'TOKEN_FORMAT_INVALID',
    'Token must have 10 to 120 minutes remaining': 'TOKEN_LIFETIME_OUT_OF_RANGE',
}


class Stop(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def login_home():
    uid = os.getuid()
    if uid < 1000 or os.geteuid() != uid:
        raise Stop('LOGIN_USER_REQUIRED')
    home = Path(pwd.getpwuid(uid).pw_dir)
    if not home.is_absolute() or any(p.is_symlink() for p in (home, *home.parents)):
        raise Stop('HOME_PATH_INVALID')
    info = home.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
        raise Stop('HOME_OWNER_OR_MODE_INVALID')
    return home


def protect_memory():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.restype = ctypes.c_int
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                          ctypes.c_ulong, ctypes.c_ulong]
    ctypes.set_errno(0)
    result = libc.prctl(4, 0, 0, 0, 0)
    return result, ctypes.get_errno()


def diagnostic_hint(stderr):
    """Only fixed classifications; arbitrary stderr is never serialized."""
    low = stderr[:65536].lower()
    for needle, label in ((b'gh auth login', 'AUTH_LOGIN_REQUIRED'),
                          (b'bad credentials', 'AUTH_REJECTED'),
                          (b'x509:', 'TLS_CERTIFICATE_ERROR'),
                          (b'no such host', 'DNS_LOOKUP_FAILED'),
                          (b'connection refused', 'CONNECTION_REFUSED'),
                          (b'network is unreachable', 'NETWORK_UNREACHABLE'),
                          (b'permission denied', 'PERMISSION_DENIED')):
        if needle in low:
            return label
    return 'UNCLASSIFIED'


def api(gh, method, endpoint, stage):
    env = os.environ.copy()
    for key in ('GH_DEBUG', 'GH_FORCE_TTY'):
        env.pop(key, None)
    env.update(GH_PROMPT_DISABLED='1', GH_PAGER='cat', LC_ALL='C')
    command = [gh, 'api', '--hostname', 'github.com', '--method', method,
               '-H', 'Accept: application/vnd.github+json',
               '-H', 'X-GitHub-Api-Version: 2022-11-28', '--include', endpoint]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=60, env=env)
    except subprocess.TimeoutExpired:
        stage['timed_out'] = True
        raise Stop('API_TIMEOUT') from None
    except OSError as exc:
        stage['errno'] = exc.errno
        raise Stop('GH_SPAWN_FAILED') from None
    stage.update(returncode=result.returncode, hint=diagnostic_hint(result.stderr))
    if len(result.stdout) > 262144 or len(result.stderr) > 262144:
        raise Stop('API_RESPONSE_TOO_LARGE')
    normalized = result.stdout.replace(b'\r\n', b'\n')
    header, separator, body = normalized.partition(b'\n\n')
    status = re.match(rb'HTTP/\d+(?:\.\d+)? ([1-5][0-9]{2})(?:\s|$)', header)
    if status:
        stage['http_status'] = int(status.group(1))
    elif result.returncode != 0:
        status = re.search(rb'\(HTTP ([1-5][0-9]{2})\)', result.stderr)
        if status:
            stage['http_status'] = int(status.group(1))
    if result.returncode != 0:
        raise Stop('API_COMMAND_FAILED')
    expected = 200 if method == 'GET' else 201
    if not separator or stage.get('http_status') != expected:
        raise Stop('API_HTTP_RESPONSE_INVALID')
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise Stop('API_JSON_INVALID') from None
    if not isinstance(value, dict):
        raise Stop('API_OBJECT_REQUIRED')
    stage['passed'] = True
    return value


def validate(value, stage):
    moment = utcnow()
    remaining = {}
    for kind in ('registration', 'removal'):
        try:
            expiry = dt.datetime.fromisoformat(value[kind]['expires_at'].replace('Z', '+00:00'))
            remaining[kind] = round((expiry - moment).total_seconds(), 3)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            raise Stop('TOKEN_EXPIRY_INVALID') from None
    stage['remaining_seconds'] = remaining
    try:
        packet(value, moment)
    except RuntimeError as exc:
        raise Stop(SAFE_PACKET_ERRORS.get(str(exc), 'PACKET_VALIDATION_FAILED')) from None
    stage['passed'] = True


def write_packet(home, value):
    fd, name = tempfile.mkstemp(prefix='ansible-runner-token-', suffix='.json', dir=home)
    path = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(value, handle)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def export_evidence(folder, report):
    """Archive exact generated bytes; no directory walk or credential file reads."""
    raw = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode()
    sums = (hashlib.sha256(raw).hexdigest() + '  RESULT.json\n').encode()
    archive = folder / 'ansible-admin-token-evidence.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        for name, data in (('RESULT.json', raw), ('SHA256SUMS', sums)):
            info = tarfile.TarInfo('evidence/' + name)
            info.size, info.mode, info.mtime = len(data), 0o600, 0
            output.addfile(info, io.BytesIO(data))
    archive.chmod(0o600)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
    return archive


def execute(home, report):
    def step(name):
        item = {'stage': name, 'passed': False}
        report['stages'].append(item)
        return item

    item = step('identity')
    item.update(uid=os.getuid(), expected_host=socket.gethostname().split('.')[0] == 'ansible01')
    if not item['expected_host']:
        raise Stop('ANSIBLE01_REQUIRED')
    item['passed'] = True
    item = step('memory-protection')
    rc, number = protect_memory()
    item.update(returncode=rc, errno=number)
    if rc != 0:
        raise Stop('MEMORY_PROTECTION_FAILED')
    item['passed'] = True
    item = step('gh-discovery')
    gh = shutil.which('gh')
    if gh is None:
        raise Stop('GH_NOT_FOUND')
    item['passed'] = True
    item = step('repository-read')
    repo = api(gh, 'GET', 'repos/' + REPO, item)
    if repo.get('full_name') != REPO:
        item['passed'] = False
        raise Stop('REPOSITORY_MISMATCH')
    permissions = repo.get('permissions')
    if isinstance(permissions, dict) and isinstance(permissions.get('admin'), bool):
        item['repository_admin_reported'] = permissions['admin']
    value = {'repository': REPO}
    for kind, name in (('registration', 'registration-token'), ('removal', 'remove-token')):
        item = step(kind + '-token')
        report['token_post_attempted'] = True
        data = api(gh, 'POST', f'repos/{REPO}/actions/runners/{name}', item)
        if not all(k in data for k in ('token', 'expires_at')):
            item['passed'] = False
            raise Stop('TOKEN_RESPONSE_FIELDS_MISSING')
        value[kind] = {k: data[k] for k in ('token', 'expires_at')}
    validate(value, step('packet-validation'))
    item = step('packet-write')
    path = write_packet(home, value)
    item['passed'] = True
    report['packet_written'] = True
    return path


def main():
    os.umask(0o077)
    try:
        home = login_home()
        folder = Path(tempfile.mkdtemp(prefix='ansible-admin-token-evidence-', dir=home))
    except Exception as exc:
        code = exc.code if isinstance(exc, Stop) else 'HOME_EVIDENCE_UNAVAILABLE'
        print('STOP: ' + code)
        return 1
    report = {'schema': 1, 'tool': 'admin-token-v1.1.1', 'repository': REPO,
              'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'common_sha256': hashlib.sha256(Path(__file__).with_name('common.py').read_bytes()).hexdigest(),
              'started_at': utcnow().isoformat(), 'status': 'FAIL', 'stages': [],
              'token_post_attempted': False, 'packet_written': False,
              'runner_registration_attempted': False, 'actions_executed': False}
    path = None
    try:
        path = execute(home, report)
        report['status'] = 'PASS_TOKEN_PACKET'
    except Exception as exc:
        report['error_code'] = exc.code if isinstance(exc, Stop) else 'UNEXPECTED_ERROR'
        if isinstance(exc, OSError):
            report['errno'] = exc.errno
    report['ended_at'] = utcnow().isoformat()
    try:
        archive = export_evidence(folder, report)
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        print('STOP: EVIDENCE_WRITE_FAILED')
        return 1
    if path is not None:
        print('TOKEN_PACKET=' + str(path))
        print('Credential file: transfer privately; never upload as evidence.')
    else:
        print('STOP: ' + report['error_code'])
        if report['stages']:
            item = report['stages'][-1]
            print('FAILED_STAGE=' + item['stage'])
            for key in ('returncode', 'http_status', 'hint', 'remaining_seconds', 'errno'):
                if key in item:
                    print(key.upper() + '=' + json.dumps(item[key], sort_keys=True))
    print('STATUS=' + report['status'])
    print('HOME_EVIDENCE=' + str(archive))
    return 0 if report['status'] == 'PASS_TOKEN_PACKET' else 1


if __name__ == '__main__':
    raise SystemExit(main())
