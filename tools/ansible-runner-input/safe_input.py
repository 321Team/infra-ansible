"""Review candidate: validate a token file before descriptor-only chmod.

Do not use on a server until test_safe_input.py has actually passed.
"""
import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
import pwd
import re
import socket
import stat
import sys
import uuid

ACCOUNT = "server01_cicd-runner"
EXPECTED_HOME = "/home/server01_cicd-runner"
REPOSITORY = "321Team/infra-ansible"
MAX_BYTES = 8192
NAME = re.compile(r"ansible-runner-token-[A-Za-z0-9_-]+\.json")
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class Rejected(Exception):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "STATUS=FAIL\nERROR_CODE=ARGUMENT_REJECTED\n")


def require(ok, code):
    if not ok:
        raise Rejected(code)


def token_basename(path, home):
    require(isinstance(path, str) and isinstance(home, str), "PATH_REJECTED")
    require(path.startswith(home + "/"), "PATH_REJECTED")
    name = path[len(home) + 1:]
    require(NAME.fullmatch(name) is not None, "PATH_REJECTED")
    return name


def open_home(home, uid):
    require(home.startswith("/") and home != "/" and
            all(p not in ("", ".", "..") for p in home[1:].split("/")),
            "HOME_REJECTED")
    fd = os.open("/", DIR_FLAGS)
    try:
        for component in home[1:].split("/"):
            parent = os.fstat(fd)
            require(parent.st_uid in (0, uid) and
                    not (stat.S_IMODE(parent.st_mode) & 0o022), "HOME_REJECTED")
            child = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        require(info.st_uid == uid and
                not (stat.S_IMODE(info.st_mode) & 0o022) and
                bool(info.st_mode & stat.S_IXUSR), "HOME_REJECTED")
        return fd
    except BaseException:
        os.close(fd)
        raise


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "PACKET_REJECTED")
        result[key] = value
    return result


def validate_packet(data, moment):
    try:
        value = json.loads(data, object_pairs_hook=unique_object)
        require(type(value) is dict and
                set(value) == {"repository", "registration", "removal"},
                "PACKET_REJECTED")
        require(value["repository"] == REPOSITORY, "PACKET_REJECTED")
        for kind in ("registration", "removal"):
            item = value[kind]
            require(type(item) is dict and set(item) == {"token", "expires_at"},
                    "PACKET_REJECTED")
            require(type(item["token"]) is str and
                    re.fullmatch(r"[A-Za-z0-9_-]{20,256}", item["token"]) is not None,
                    "PACKET_REJECTED")
            require(type(item["expires_at"]) is str, "PACKET_REJECTED")
            expiry = dt.datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00"))
            require(expiry.tzinfo is not None and
                    dt.timedelta(minutes=10) <= expiry - moment <= dt.timedelta(hours=2),
                    "PACKET_REJECTED")
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        raise Rejected("PACKET_REJECTED") from None


def metadata(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_nlink, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def same_entry(home_fd, name, info):
    current = os.stat(name, dir_fd=home_fd, follow_symlinks=False)
    require(metadata(current) == metadata(info), "INPUT_CHANGED")


def protect_token(home_fd, name, uid, moment, record):
    # The production caller already checked the full path; keep this boundary
    # self-contained so direct callers cannot smuggle '/' or '..' components.
    require(NAME.fullmatch(name) is not None, "PATH_REJECTED")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=home_fd)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                before.st_uid == uid and not (before.st_mode & 0o7000) and
                0 < before.st_size <= MAX_BYTES, "FILE_REJECTED")
        pieces = []
        remaining = MAX_BYTES + 1
        while remaining:
            piece = os.read(fd, remaining)
            if not piece:
                break
            pieces.append(piece)
            remaining -= len(piece)
        data = b"".join(pieces)
        require(len(data) == before.st_size and len(data) <= MAX_BYTES and
                metadata(os.fstat(fd)) == metadata(before), "INPUT_CHANGED")
        validate_packet(data, moment)
        require(metadata(os.fstat(fd)) == metadata(before), "INPUT_CHANGED")
        same_entry(home_fd, name, before)
        record["input_validated"] = True
        if stat.S_IMODE(before.st_mode) != 0o600:
            # Never replace this with chmod(path). A directory-entry swap must
            # not redirect the permission operation to the operator's home.
            os.fchmod(fd, 0o600)
            record["permission_changed"] = True
        after = os.fstat(fd)
        require(stat.S_ISREG(after.st_mode) and after.st_uid == uid and
                after.st_nlink == 1 and stat.S_IMODE(after.st_mode) == 0o600 and
                after.st_dev == before.st_dev and after.st_ino == before.st_ino and
                after.st_size == before.st_size and
                after.st_mtime_ns == before.st_mtime_ns, "INPUT_CHANGED")
        same_entry(home_fd, name, after)
        record["status"] = "PASS_TOKEN_INPUT"
    finally:
        os.close(fd)


def make_evidence(home_fd):
    name = "ansible-token-input-evidence-" + uuid.uuid4().hex
    os.mkdir(name, 0o700, dir_fd=home_fd)
    fd = os.open(name, DIR_FLAGS, dir_fd=home_fd)
    return name, fd


def write_evidence(fd, record):
    # No operator input, token contents, content hash or raw exception strings.
    safe = {key: record[key] for key in
            ("status", "error_code", "input_validated", "permission_changed")}
    safe["schema"] = 1
    data = (json.dumps(safe, sort_keys=True, indent=2) + "\n").encode("utf-8")
    checksum = (hashlib.sha256(data).hexdigest() + "  RESULT.json\n").encode("ascii")
    for name, payload in (("RESULT.json", data), ("RESULT.json.sha256", checksum)):
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                      os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
        with os.fdopen(out, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    os.fsync(fd)


def production_home():
    uid = os.getuid()
    require(uid == os.geteuid() and uid >= 1000, "LOGIN_REJECTED")
    who = pwd.getpwuid(uid)
    require(who.pw_name == ACCOUNT and who.pw_dir == EXPECTED_HOME and
            socket.gethostname().split(".")[0] == "cicd-runner01", "LOGIN_REJECTED")
    require(ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) == 0, "DUMP_GUARD_FAILED")
    return who.pw_dir, uid


def main(argv=None):
    parser = SafeParser(description="Validate a token file before chmod; no sudo.")
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    record = {"status": "FAIL", "error_code": None,
              "input_validated": False, "permission_changed": False}
    home_fd = evidence_fd = None
    output = None
    try:
        home, uid = production_home()
        home_fd = open_home(home, uid)
        evidence_name, evidence_fd = make_evidence(home_fd)
        output = home + "/" + evidence_name + "/RESULT.json"
        name = token_basename(args.token_file, home)
        protect_token(home_fd, name, uid, dt.datetime.now(dt.timezone.utc), record)
    except Rejected as exc:
        record["error_code"] = str(exc)  # Only fixed codes raised above.
    except Exception:
        record["error_code"] = "IO_OR_RUNTIME_ERROR"
    finally:
        if evidence_fd is not None:
            try:
                write_evidence(evidence_fd, record)
            except Exception:
                record["status"] = "FAIL"
                record["error_code"] = "EVIDENCE_WRITE_FAILED"
                output = None
            finally:
                os.close(evidence_fd)
        if home_fd is not None:
            os.close(home_fd)
    print("STATUS=" + record["status"])
    if record["error_code"]:
        print("ERROR_CODE=" + record["error_code"])
    if output:
        print("HOME_EVIDENCE=" + output)
    # Only a successfully checked path may be displayed.
    if record["status"] == "PASS_TOKEN_INPUT":
        print("TOKEN_FILE=" + args.token_file)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
