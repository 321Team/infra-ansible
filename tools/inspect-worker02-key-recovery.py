#!/usr/bin/env python3
"""Issue9 fixed-host, read-only recovery inspection. Never restores a key.

AI usage: CODEX_ASSISTED. Linux/SELinux implementation requires independent
review and a field receipt; MOCK results do not establish operating readiness.
"""
import argparse
import hashlib
import json
import os
import platform
import socket
import stat
import sys
from datetime import datetime, timezone, timedelta

HOST = "k8s-worker02"
BACKUP = "/var/lib/ansible-issue9-worker02.NXrcqAmF/authorized_keys"
TARGET = "/home/svc_ansible/.ssh/authorized_keys"
EXPECTED_HASH = "b7923e8c646b7a7dd2ccba1ac48ddf02d264780db9100317644dcf87216cc834"
EXPECTED = {"sha256": EXPECTED_HASH, "uid": 1001, "gid": 1001,
            "mode": "0600", "context": "unconfined_u:object_r:ssh_home_t:s0"}
MAX_BYTES = 256 * 1024
PARENTS = {
    "/": (0, False), "/var": (0, False), "/var/lib": (0, False),
    "/var/lib/ansible-issue9-worker02.NXrcqAmF": (0, True),
    "/home": (0, False), "/home/svc_ansible": (1001, False),
    "/home/svc_ansible/.ssh": (1001, True),
}


class Stop(Exception):
    """Only fixed non-secret error codes may leave the inspector."""


def fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_uid, st.st_gid, st.st_mode,
            st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def directory_identity(st):
    return (st.st_dev, st.st_ino, st.st_uid, st.st_gid, st.st_mode)


def check_directory(st, owner, private):
    mode = stat.S_IMODE(st.st_mode)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != owner:
        raise Stop("UNTRUSTED_PARENT_TYPE_OR_OWNER")
    if mode & 0o022 or (private and mode & 0o077):
        raise Stop("UNTRUSTED_PARENT_PERMISSIONS")


def check_file(st, backup):
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise Stop("FILE_NOT_SINGLE_LINK_REGULAR")
    if not 0 < st.st_size <= MAX_BYTES:
        raise Stop("FILE_SIZE_OUT_OF_BOUND")
    if st.st_uid not in (0, 1001):
        raise Stop("UNEXPECTED_FILE_OWNER")
    # Source ownership/label is recorded independently, not inferred from the
    # receipt for TARGET. A restored stage must get EXPECTED explicitly.
    if backup and stat.S_IMODE(st.st_mode) != 0o600:
        raise Stop("BACKUP_NOT_PRIVATE_0600")


def context_text(raw):
    try:
        value = raw.removesuffix(b"\x00").decode("ascii")
    except (AttributeError, UnicodeError):
        raise Stop("INVALID_SELINUX_CONTEXT") from None
    # Do not emit arbitrary xattr bytes into an evidence/log channel.
    if not value or len(value) > 256 or value.count(":") < 3:
        raise Stop("INVALID_SELINUX_CONTEXT")
    if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:,.-" for c in value):
        raise Stop("INVALID_SELINUX_CONTEXT")
    return value


class LinuxReader:
    def environment(self):
        return platform.system(), os.geteuid(), socket.gethostname(), self.enforcing()

    @staticmethod
    def enforcing():
        # Kernel SELinux status, no getenforce subprocess or policy change.
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open("/sys/fs/selinux/enforce", flags)
        try:
            return os.read(fd, 8) == b"1"
        finally:
            os.close(fd)

    @staticmethod
    def snapshot(path):
        if path not in (BACKUP, TARGET):
            raise Stop("PATH_OUT_OF_SCOPE")
        fds = []
        links = []
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            root = os.open("/", flags)
            fds.append(root)
            check_directory(os.fstat(root), *PARENTS["/"])
            current = ""
            parts = path.split("/")[1:]
            for part in parts[:-1]:
                parent = fds[-1]
                current += "/" + part
                child = os.open(part, flags, dir_fd=parent)
                fds.append(child)
                observed = os.fstat(child)
                check_directory(observed, *PARENTS[current])
                named = os.stat(part, dir_fd=parent, follow_symlinks=False)
                if directory_identity(named) != directory_identity(observed):
                    raise Stop("PARENT_CHANGED")
                links.append((parent, part, child, directory_identity(observed)))
            parent = fds[-1]
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
            fds.append(fd)
            before = os.fstat(fd)
            check_file(before, path == BACKUP)
            named = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if fingerprint(named) != fingerprint(before):
                raise Stop("FILE_CHANGED")
            context = context_text(os.getxattr(fd, "security.selinux"))
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise Stop("FILE_GREW_OUT_OF_BOUND")
                digest.update(chunk)
            if fingerprint(before) != fingerprint(os.fstat(fd)) or total != before.st_size:
                raise Stop("FILE_CHANGED_DURING_READ")
            if context != context_text(os.getxattr(fd, "security.selinux")):
                raise Stop("CONTEXT_CHANGED_DURING_READ")
            if fingerprint(before) != fingerprint(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)):
                raise Stop("FILE_CHANGED")
            for parent_fd, name, child_fd, identity in links:
                if (directory_identity(os.fstat(child_fd)) != identity or
                    directory_identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) != identity):
                    raise Stop("PARENT_CHANGED")
            return {"sha256": digest.hexdigest(), "uid": before.st_uid,
                    "gid": before.st_gid, "mode": f"{stat.S_IMODE(before.st_mode):04o}",
                    "context": context, "dev": before.st_dev, "inode": before.st_ino,
                    "nlink": before.st_nlink, "size": total,
                    "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns}
        finally:
            for fd in reversed(fds):
                os.close(fd)


def inspect(reader):
    result = {"schema": "fds.issue9.key-recovery-inspection.v1", "host": HOST,
              "expected_destination": dict(EXPECTED),
              "status": "INCOMPLETE", "production_restore": "NOT_RUN",
              "target_write": "NOT_IMPLEMENTED", "runtime_go": False,
              "restore_ready": False, "fresh_ssh": "NOT_RUN",
              "snapshot_is_not_write_authorization": True,
              "concurrent_writer_exclusion": "NOT_ESTABLISHED"}
    try:
        system, uid, hostname, enforcing = reader.environment()
        if system != "Linux" or uid != 0 or hostname != HOST:
            raise Stop("HOST_PLATFORM_OR_ACCOUNT_MISMATCH")
        if enforcing is not True:
            raise Stop("SELINUX_NOT_ENFORCING")
        first = {"backup": reader.snapshot(BACKUP), "target": reader.snapshot(TARGET)}
        second = {"backup": reader.snapshot(BACKUP), "target": reader.snapshot(TARGET)}
        if first != second:
            raise Stop("SNAPSHOT_CHANGED_RETRY_REVIEW_REQUIRED")
        if first["backup"]["sha256"] != EXPECTED_HASH:
            raise Stop("BACKUP_HASH_MISMATCH")
        if (first["backup"]["dev"], first["backup"]["inode"]) == (first["target"]["dev"], first["target"]["inode"]):
            raise Stop("BACKUP_AND_TARGET_SAME_FILE")
        result["observed"] = first
        result["destination_drift"] = [k for k, v in EXPECTED.items() if first["target"][k] != v]
        # A different backup label is an observation, not proof that the
        # destination should adopt it, nor automatic permission to relabel.
        result["backup_label_matches_destination_expectation"] = first["backup"]["context"] == EXPECTED["context"]
        result["status"] = "DRIFT_REVIEW_REQUIRED" if result["destination_drift"] else "UNCHANGED_NO_RESTORE_NEEDED"
        return result, 2 if result["destination_drift"] else 0
    except Stop as exc:
        result["error_code"] = str(exc)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        # Never print raw key bytes, xattr values, or OS exception text.
        result["error_code"] = "READ_OR_PLATFORM_CAPABILITY_FAILED"
    return result, 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true", required=True,
                        help="Acknowledge this command cannot restore or stage a key")
    parser.parse_args()
    # Refuse unsupported environments before referring to POSIX-only APIs.
    if platform.system() != "Linux":
        result = {"status": "INCOMPLETE", "error_code": "HOST_PLATFORM_OR_ACCOUNT_MISMATCH",
                  "production_restore": "NOT_RUN", "runtime_go": False}
        rc = 2
    else:
        result, rc = inspect(LinuxReader())
    result["captured_at_kst"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    result["inspector_sha256"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
