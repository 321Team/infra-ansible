#!/usr/bin/env python3
"""One controller-wide lock shared by the rollout and standalone CR wrapper."""
import argparse
import fcntl
import os
from pathlib import Path
import pwd
import stat
import sys

FD_ENV = "CR_NTP_WORKFLOW_LOCK_FD"


def default_lock_path():
    # HOME and the checkout/evidence path must not split the lock namespace.
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / ".local/state/fds-ntp/CR-P1-NTP-01-01.lock"


def secure_parent(path):
    uid = os.geteuid()
    path = Path(path)
    for directory in reversed([path] + list(path.parents)):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            directory.mkdir(mode=0o700)
            info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, uid):
            raise ValueError("Unsafe workflow lock directory: %s" % directory)
        writable = stat.S_IMODE(info.st_mode) & 0o022
        if writable and not (directory != path and info.st_mode & stat.S_ISVTX):
            raise ValueError("Writable workflow lock directory: %s" % directory)


def acquire_lock(inherited_fd=None, path=None):
    """Return an owned descriptor; tests may supply an isolated path directly."""
    path = Path(path) if path is not None else default_lock_path()
    secure_parent(path.parent)
    descriptor = None
    try:
        if inherited_fd is None:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        else:
            if not str(inherited_fd).isdigit():
                raise ValueError("Invalid inherited workflow lock descriptor")
            descriptor = os.dup(int(inherited_fd))
        held = os.fstat(descriptor)
        named = path.lstat()
        if (not stat.S_ISREG(held.st_mode) or not stat.S_ISREG(named.st_mode)
                or held.st_uid != os.geteuid() or held.st_nlink != 1
                or stat.S_IMODE(held.st_mode) != 0o600
                or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError("Workflow lock descriptor does not name the protected lock file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another NTP controller workflow is running") from exc
        os.set_inheritable(descriptor, True)
        return descriptor
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inherited", type=int)
    parser.add_argument("--exec", dest="command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        inherited = args.check_inherited if args.check_inherited is not None else os.environ.get(FD_ENV)
        descriptor = acquire_lock(inherited)
        if args.check_inherited is not None:
            os.close(descriptor)
            return 0
        if not args.command:
            raise ValueError("Specify --exec COMMAND or --check-inherited FD")
        environment = dict(os.environ, **{FD_ENV: str(descriptor)})
        os.execvpe(args.command[0], args.command, environment)
    except (OSError, ValueError) as exc:
        print("STOP: %s" % exc, file=sys.stderr)
        return 73


if __name__ == "__main__":
    raise SystemExit(main())
