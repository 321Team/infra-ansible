#!/usr/bin/env python3
"""Read-only account checks; never edits sudo policy, users, groups or passwords."""
import argparse
import json
import os
from pathlib import Path
import pwd
import socket
import stat
import subprocess

ACCOUNT = 'ansible-verify'
HOST = 'cicd-runner01'
HOME_PATH = Path('/home/ansible-verify')


def denial_confirmed(rc, stdout, stderr, account=ACCOUNT, host=HOST):
    # On the observed sudo 1.9.17 el10 host, explicit denial exits 0.
    # Accept only the exact denial statement, no warning/allow/error mixed in.
    expected = f'User {account} is not allowed to run sudo on {host}.'
    lines = [line.strip() for line in (stdout + '\n' + stderr).splitlines() if line.strip()]
    return type(rc) is int and rc in (0, 1) and lines == [expected]


def identity_errors(record, expected_uid, expected_gid):
    errors = []
    requirements = {
        'account': record['name'] == ACCOUNT,
        'uid': record['uid'] == expected_uid and expected_uid >= 1000,
        'gid': record['gid'] == expected_gid and expected_gid >= 1000,
        'home': record['home'] == str(HOME_PATH),
        'shell': record['shell'] == '/bin/bash',
        'groups': set(record['groups']) == {expected_gid},
        'home-owner': record['home_uid'] == expected_uid and record['home_gid'] == expected_gid,
        'home-mode': record['home_mode'] == 0o700,
        'home-directory': record['home_directory'] is True and record['home_linked'] is False,
        'password-locked': record['password_locked'] is True,
        'credentials-absent': record['credential_paths_present'] == [],
    }
    errors.extend(name for name, ok in requirements.items() if not ok)
    return errors


def observe_identity():
    account = pwd.getpwnam(ACCOUNT)
    home_stat = HOME_PATH.lstat()
    result = subprocess.run(['getent', 'shadow', ACCOUNT], text=True, capture_output=True, timeout=30)
    fields = result.stdout.strip().split(':')
    locked = (result.returncode == 0 and len(fields) == 9 and fields[0] == ACCOUNT
              and fields[1].startswith(('!', '*')))
    # Never print/store the password field or the raw shadow result.
    forbidden = ['.ssh', '.aws', '.azure', '.kube', '.docker/config.json', '.git-credentials',
                 '.config/gh', '.config/containers/auth.json']
    present = [p for p in forbidden if (HOME_PATH / p).exists() or (HOME_PATH / p).is_symlink()]
    return dict(name=account.pw_name, uid=account.pw_uid, gid=account.pw_gid,
                home=account.pw_dir, shell=account.pw_shell,
                groups=os.getgrouplist(ACCOUNT, account.pw_gid),
                home_uid=home_stat.st_uid, home_gid=home_stat.st_gid,
                home_mode=stat.S_IMODE(home_stat.st_mode),
                home_directory=stat.S_ISDIR(home_stat.st_mode),
                home_linked=any(p.is_symlink() for p in [HOME_PATH, *HOME_PATH.parents]),
                password_locked=bool(locked), credential_paths_present=present)


def check_policy():
    env = dict(os.environ, LC_ALL='C', LANG='C')
    command = ['sudo', '-n', '-ll', '-U', ACCOUNT]
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=30)
    allowed_hosts = {HOST, socket.gethostname()}
    confirmed = any(denial_confirmed(result.returncode, result.stdout, result.stderr, host=h)
                    for h in allowed_hosts)
    print(json.dumps(dict(check='sudo-policy', command=command, rc=result.returncode,
                         stdout=result.stdout, stderr=result.stderr,
                         denial_confirmed=confirmed), ensure_ascii=False), flush=True)
    if not confirmed:
        raise RuntimeError('sudo denial is not confirmed; policy unchanged and execution stopped')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['sudo-policy', 'resume'])
    parser.add_argument('--uid', type=int)
    parser.add_argument('--gid', type=int)
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != HOST:
        raise RuntimeError('Run this read-only check as root on cicd-runner01')
    if args.mode == 'sudo-policy':
        check_policy()
    else:
        if args.uid is None or args.gid is None:
            raise RuntimeError('Resume requires the observed UID and GID')
        record = observe_identity()
        errors = identity_errors(record, args.uid, args.gid)
        print(json.dumps(dict(check='resume-identity', record=record, errors=errors)), flush=True)
        if errors:
            raise RuntimeError('Existing account differs from the expected dedicated account')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        print('STOP: ' + str(exc), flush=True)
        raise SystemExit(1)
