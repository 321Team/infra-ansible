"""Issue short-lived repository Runner tokens on the management host only."""
import ctypes
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, packet, require


def main():
    require(os.getuid() >= 1000 and socket.gethostname().split('.')[0] == 'ansible01', 'Run as login user on ansible01')
    require(ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0, 'Cannot disable token tool memory dumping')
    gh = shutil.which('gh')
    require(gh, 'gh missing on management host')
    value = {'repository': REPO}
    for key, endpoint in (('registration', 'registration-token'), ('removal', 'remove-token')):
        result = subprocess.run([gh, 'api', '--method', 'POST', f'repos/{REPO}/actions/runners/{endpoint}'],
                                capture_output=True, timeout=60)
        require(result.returncode == 0, 'Token issuance failed; API output excluded')
        data = json.loads(result.stdout)
        value[key] = {k: data[k] for k in ('token', 'expires_at')}
    packet(value)
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    require(home.stat().st_uid == os.getuid() and not any(p.is_symlink() for p in (home, *home.parents)), 'Login home differs')
    os.umask(0o077)
    fd, path = tempfile.mkstemp(prefix='ansible-runner-token-', suffix='.json', dir=home)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle)
        handle.write('\n')
    print('TOKEN_PACKET=' + path)
    print('This credential file is not evidence. Transfer privately; do not upload it.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('STOP: ' + type(exc).__name__)
        raise SystemExit(1)
