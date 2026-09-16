"""Privilege boundary: account checks/install, then runuser; home evidence always."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ACCOUNT, ARCHIVE, GID, HOST_PATH, UID, VERIFY_HOME, digest,
                    manifest, now, packet, read_regular, require, write)

ROOT = Path(__file__).resolve().parent
EXPECTED = {'prepare': 'PASS_PREPARE', 'registration-check': 'PASS_REGISTRATION_CHECK',
            'serve': 'SESSION_ENDED_REQUIRES_CI_REVIEW'}


def caller():
    require(os.geteuid() == 0, 'Use sudo bash run.sh from the existing login account')
    uid = int(os.environ.get('SUDO_UID', '-1'))
    require(uid >= 1000 and uid != UID, 'Original non-root login UID required')
    who = pwd.getpwuid(uid)
    require(who.pw_name == os.environ.get('SUDO_USER'), 'Sudo caller mismatch')
    home = Path(who.pw_dir)
    require(home.is_absolute() and home.is_dir() and home.stat().st_uid == uid
            and not any(p.is_symlink() for p in (home, *home.parents)), 'Caller home owner/path differs')
    return who


def stream(command, evidence, label, payload=None, cwd=None):
    cwd = ROOT if cwd is None else cwd
    write(evidence / (label + '.command.json'), command)
    write(evidence / (label + '.context.json'), {'cwd': str(cwd)})
    with (evidence / (label + '.log')).open('wb') as log:
        process = subprocess.Popen(command, cwd=cwd, env={'PATH': HOST_PATH, 'LANG': 'C.UTF-8', 'LC_ALL': 'C'},
                                   stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            first = True
            while True:
                try:
                    process.communicate(input=payload if first else None, timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    print('WAIT=' + label, flush=True)
            rc = process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                for _ in range(3):
                    try:
                        process.wait(30)  # Give the controller time to remove its exact CIDs.
                        break
                    except subprocess.TimeoutExpired:
                        print('WAIT=dedicated-cleanup', flush=True)
                if process.poll() is None:
                    process.kill()
                    process.wait()
    (evidence / (label + '.rc')).write_text(str(rc) + '\n')
    # Only account checks and the trusted host controller write here; container
    # stdout/Runner native logs are private and never enter this stream.
    with (evidence / (label + '.log')).open('r', errors='replace') as handle:
        for line in handle:
            print(line, end='', flush=True)
    return rc


def copy_original(run, destination):
    require(not any(p.is_symlink() for p in run.parents), 'Linked run parent')
    directory = os.open(run, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require(os.fstat(directory).st_uid == UID, 'Run directory owner differs')
        destination.mkdir()
        for name, maximum in ((ARCHIVE, 16*1024**2), (ARCHIVE + '.sha256', 256)):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_uid == UID and info.st_nlink == 1
                        and 0 < info.st_size <= maximum, 'Invalid evidence file')
                data = handle.read(maximum + 1)
                require(len(data) == info.st_size, 'Evidence changed while collecting')
                (destination / name).write_bytes(data)
    finally:
        os.close(directory)
    archive = destination / ARCHIVE
    require((destination / (ARCHIVE + '.sha256')).read_text().split() == [digest(archive), ARCHIVE], 'Evidence checksum differs')
    # No extraction as root. Read one bounded JSON member only.
    with tarfile.open(archive, 'r:gz') as handle:
        members, expanded = [], 0
        for member in handle:
            expanded += member.size
            require(len(members) < 100 and expanded <= 16*1024**2, 'Evidence archive bounds exceeded')
            members.append(member)
        selected = [m for m in members if m.name == 'evidence/HOST_RUN_RESULT.json']
        require(len(selected) == 1 and selected[0].isfile() and selected[0].size < 32768, 'Host result absent/invalid')
        return json.load(handle.extractfile(selected[0]))


def overall_ok(mode, rc, value, bundle):
    return (type(rc) is int and rc == 0 and type(value) is dict and value.get('status') == EXPECTED[mode]
            and value.get('mode') == mode and value.get('account') == ACCOUNT
            and type(value.get('uid')) is int and value['uid'] == UID
            and value.get('bundle_sha256') == bundle and value.get('container_cleanup') == 'REMOVED'
            and value.get('production_apply') is False and value.get('engine_transition') is False)


def finish(output, evidence, record, who):
    record['ended_at'] = now()
    write(evidence / 'HOME_RUN_RESULT.json', record)
    (evidence / 'SHA256SUMS').write_text(''.join(digest(p) + '  ' + p.relative_to(evidence).as_posix() + '\n'
        for p in sorted(evidence.rglob('*')) if p.is_file()))
    archive = output / ARCHIVE
    with tarfile.open(archive, 'w:gz') as handle:
        handle.add(evidence, arcname='evidence')
    (output / (ARCHIVE + '.sha256')).write_text(digest(archive) + '  ' + ARCHIVE + '\n')
    for path in sorted(output.rglob('*'), reverse=True):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
        os.chown(path, who.pw_uid, who.pw_gid)
    os.chmod(output, 0o700)
    os.chown(output, who.pw_uid, who.pw_gid)
    print('STATUS=' + record['status'], flush=True)
    print('HOME_EVIDENCE=' + str(archive), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=EXPECTED)
    parser.add_argument('--prepared')
    parser.add_argument('--token-file')
    args = parser.parse_args()
    require((args.mode == 'prepare' and args.prepared is None and args.token_file is None)
            or (args.mode != 'prepare' and args.prepared and args.token_file), 'Mode input fields differ')
    os.umask(0o077)
    who = caller()
    output = Path(tempfile.mkdtemp(prefix='ansible-actions-evidence-', dir=who.pw_dir))
    evidence = output / 'evidence'
    evidence.mkdir()
    run = VERIFY_HOME / ('ansible-actions-' + uuid.uuid4().hex)
    record = {'status': 'FAIL', 'mode': args.mode, 'started_at': now(), 'login_account': who.pw_name,
              'dedicated_run': str(run), 'host_rc': None,
              'github_actions_verdict': 'NOT_RUN' if args.mode != 'serve' else 'NOT_ASSESSED',
              'production_apply': False, 'engine_transition': False}
    print('HOME_OUTPUT=' + str(output), flush=True)
    bundle = None
    try:
        require(socket.gethostname().split('.')[0] == 'cicd-runner01', 'Expected cicd-runner01')
        require(ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0, 'Cannot disable launcher memory dumping')
        bundle = manifest(ROOT)
        record['bundle_sha256'] = bundle
        require((Path('/run/user') / str(UID) / 'bus').is_socket(), 'Dedicated user manager not ready')
        for label, argv in [('identity', ['resume', '--uid', str(UID), '--gid', str(GID)]), ('sudo-policy', ['sudo-policy'])]:
            require(stream([sys.executable, '-I', '-B', str(ROOT / 'support/check-account.py'), *argv], evidence, label) == 0,
                    label + ' check failed')
        installed = VERIFY_HOME / ('FDS_Ansible_Actions_Runner_' + uuid.uuid4().hex)
        installed.mkdir(mode=0o700)
        # Copy only manifest-listed bounded files, while the install directory is
        # root-private. No recursive root copy of unexpected operator-side paths.
        names = [line.split('  ', 1)[1] for line in (ROOT / 'SHA256SUMS').read_text().splitlines()] + ['SHA256SUMS']
        for name in names:
            target = installed / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(read_regular(ROOT / name, 2*1024**2))
        require(manifest(installed) == bundle, 'Installed bundle differs')
        for path in [installed, *installed.rglob('*')]:
            os.chmod(path, 0o755 if path.is_dir() else 0o644)
            os.chown(path, 0, 0)
        payload = None
        if args.mode != 'prepare':
            token_path = Path(args.token_file)
            require(token_path.is_absolute() and not any(p.is_symlink() for p in token_path.parents), 'Invalid token path')
            payload = (json.dumps(packet(json.loads(read_regular(token_path, 8192, who.pw_uid)))) + '\n').encode()
        runuser = shutil.which('runuser', path=HOST_PATH)
        require(runuser, 'runuser missing')
        command = [runuser, '-u', ACCOUNT, '--', 'env', '-i', 'HOME=' + str(VERIFY_HOME), 'USER=' + ACCOUNT,
                   'LOGNAME=' + ACCOUNT, 'PATH=' + HOST_PATH, 'LANG=C.UTF-8', 'XDG_RUNTIME_DIR=/run/user/' + str(UID),
                   'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/' + str(UID) + '/bus',
                   'python3', '-I', '-B', str(installed / 'runner.py'), args.mode, '--output', str(run)]
        if args.prepared:
            command += ['--prepared', args.prepared]
        record['host_rc'] = stream(command, evidence, 'dedicated-run', payload, cwd=VERIFY_HOME)
    except (Exception, KeyboardInterrupt) as exc:
        record['launch_error_type'] = type(exc).__name__
        if args.mode == 'prepare':
            record['prepare_error'] = str(exc)[:1024]
    try:
        original = copy_original(run, evidence / 'original')
        write(evidence / 'ORIGINAL_HOST_RUN_RESULT.json', original)
        if 'launch_error_type' not in record and overall_ok(args.mode, record['host_rc'], original, bundle):
            record['status'] = EXPECTED[args.mode]
            record['github_actions_verdict'] = 'NOT_RUN' if args.mode != 'serve' else 'VERIFY_RUN_AND_ARTIFACT'
    except (Exception, KeyboardInterrupt) as exc:
        record['collection_error_type'] = type(exc).__name__
    finish(output, evidence, record, who)
    return 0 if record['status'] == EXPECTED[args.mode] else 1


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('STOP: ' + type(exc).__name__, flush=True)
        raise SystemExit(1)
