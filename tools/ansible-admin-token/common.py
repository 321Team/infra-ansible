import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

REPO = '321Team/infra-ansible'
URL = 'https://github.com/' + REPO
VERSION = '2.337.0'
RUNNER_SHA = '70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613'
RUNNER_BYTES = 226430031
RUNNER_URL = f'https://github.com/actions/runner/releases/download/v{VERSION}/actions-runner-linux-x64-{VERSION}.tar.gz'
BASE = 'docker.io/library/python@sha256:581429e3df12d76e6af4be5ab7d0e7fc2013eb57dc23d2de691411c8efdbb970'
BASE_ID = 'sha256:e8565fa265f973c06f0515fac7aa9d102edae01b5677d69216900b84029c6ad0'
UID, GID = 1001, 1002
ACCOUNT = 'ansible-verify'
VERIFY_HOME = Path('/home/ansible-verify')
HOST_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
ARCHIVE = 'ansible-actions-runner-evidence.tar.gz'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def read_regular(path, maximum=1024*1024, owner=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum,
                'Expected bounded regular file')
        if owner is not None:
            require(info.st_uid == owner and stat.S_IMODE(info.st_mode) == 0o600, 'Token file owner/mode must match login/0600')
        data = stream.read(maximum + 1)
        require(len(data) == info.st_size and len(data) <= maximum, 'File changed or exceeded bound')
        return data


def manifest(root):
    root = Path(root)
    require(not any(p.is_symlink() for p in (root, *root.parents)), 'Linked bundle root')
    for entry in root.rglob('*'):
        info = entry.lstat()
        require(stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                'Bundle links/special files rejected')
    rows = (root / 'SHA256SUMS').read_text().splitlines()
    seen = set()
    for row in rows:
        sha, name = row.split('  ', 1)
        p = PurePosixPath(name)
        require(re.fullmatch('[0-9a-f]{64}', sha) and re.fullmatch('[A-Za-z0-9_./-]+', name)
                and name not in seen and not p.is_absolute()
                and all(part not in ('', '.', '..') for part in name.split('/')), 'Invalid manifest')
        path = root / name
        require(not any(x.is_symlink() for x in (path, *path.parents)) and path.is_file()
                and digest(path) == sha, 'Bundle hash mismatch: ' + name)
        seen.add(name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    require(actual == seen | {'SHA256SUMS'}, 'Unexpected/missing bundle file')
    return digest(root / 'SHA256SUMS')


def packet(value, moment=None):
    require(isinstance(value, dict) and set(value) == {'repository', 'registration', 'removal'}, 'Invalid token packet fields')
    require(value['repository'] == REPO, 'Token packet repository mismatch')
    moment = moment or dt.datetime.now(dt.timezone.utc)
    for kind in ('registration', 'removal'):
        item = value[kind]
        require(isinstance(item, dict) and set(item) == {'token', 'expires_at'}, 'Invalid token record')
        require(isinstance(item['token'], str) and re.fullmatch('[A-Za-z0-9_-]{20,256}', item['token']), 'Invalid token format')
        expiry = dt.datetime.fromisoformat(item['expires_at'].replace('Z', '+00:00'))
        require(expiry.tzinfo is not None and dt.timedelta(minutes=10) <= expiry - moment <= dt.timedelta(hours=2),
                'Token must have 10 to 120 minutes remaining')
    return value


def image_id(value):
    value = value.strip()
    if re.fullmatch('[0-9a-f]{64}', value):
        value = 'sha256:' + value
    require(re.fullmatch('sha256:[0-9a-f]{64}', value), 'Invalid image ID')
    return value
