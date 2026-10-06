#!/usr/bin/env python3
"""Issue9 disposable file experiment, NOT an operational SSH restore tool.

No input paths, SSH, credentials, Ansible, sudo, or service operations.
Only synthetic files under this process's TemporaryDirectory are modified.
The algorithm below is a fixture prototype, not a reviewed production helper.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(path):
    s = path.stat()
    return (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode))


def exercise(root, expected, interrupt=False):
    # Fixed direct-child paths in a newly owned private fixture directory.
    source, target = root / 'backup', root / 'target'
    for path in (source, target):
        s = path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
            raise ValueError('not a single-link regular fixture file')
    if digest(source) != expected:
        raise ValueError('fixture backup hash mismatch')
    fd, name = tempfile.mkstemp(prefix='staged-', dir=root)
    os.close(fd)
    stage = Path(name)
    try:
        subprocess.run(['/usr/bin/cp', '--preserve=all', '--', str(source), str(stage)],
                       check=True, capture_output=True, timeout=10)
        if digest(stage) != expected or metadata(stage) != metadata(source):
            raise ValueError('staged fixture verification failed')
        if interrupt:
            raise RuntimeError('injected interruption before replacement')
        os.replace(stage, target)
        if digest(target) != expected or metadata(target) != metadata(source):
            raise ValueError('restored fixture verification failed')
    finally:
        stage.unlink(missing_ok=True)


def run():
    rows = []
    cases = ('changed_content_and_mode', 'identical_reapply', 'wrong_hash',
             'backup_symlink', 'target_symlink', 'backup_hardlink', 'precommit_interruption')
    for case in cases:
        with tempfile.TemporaryDirectory(prefix='issue9-file-fixture-') as name:
            root = Path(name)
            source, target = root / 'backup', root / 'target'
            source.write_bytes(b'SYNTHETIC FIXTURE BASELINE\n')
            source.chmod(0o600)
            target.write_bytes(b'SYNTHETIC FIXTURE CHANGED\n')
            target.chmod(0o640)
            expected = digest(source)
            if case == 'identical_reapply':
                target.write_bytes(source.read_bytes())
                target.chmod(0o600)
            elif case == 'wrong_hash':
                source.write_bytes(b'TAMPERED SYNTHETIC BACKUP\n')
            elif case == 'backup_symlink':
                source.rename(root / 'source-real')
                source.symlink_to(root / 'source-real')
            elif case == 'target_symlink':
                target.rename(root / 'target-real')
                target.symlink_to(root / 'target-real')
            elif case == 'backup_hardlink':
                os.link(source, root / 'source-alias')
            before = (target.read_bytes(), metadata(target), target.is_symlink())
            rejected = False
            try:
                exercise(root, expected, interrupt=case == 'precommit_interruption')
            except (ValueError, RuntimeError):
                rejected = True
            if case in ('changed_content_and_mode', 'identical_reapply'):
                passed = not rejected and digest(target) == expected and metadata(target) == metadata(source)
            else:
                passed = rejected and before == (target.read_bytes(), metadata(target), target.is_symlink())
            passed = passed and not list(root.glob('staged-*'))
            rows.append({'case': case, 'passed': passed})
    result = {'scope': 'local synthetic file fixture only', 'production_restore': 'NOT_RUN',
              'ansible_engine_test': 'NOT_RUN', 'selinux_context_test': 'NOT_RUN',
              'cross_uid_gid_restore': 'NOT_RUN', 'power_loss_durability': 'NOT_TESTED',
              'concurrent_adversarial_changes': 'NOT_TESTED',
              'cases': rows, 'status': 'PASS' if all(x['passed'] for x in rows) else 'FAIL'}
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run())
