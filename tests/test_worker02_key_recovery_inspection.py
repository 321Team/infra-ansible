import contextlib
import copy
import hashlib
import importlib.util
from pathlib import Path
import stat
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("inspector", Path(__file__).resolve().parents[1] / "tools" / "inspect-worker02-key-recovery.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def st(inode=1, mode=stat.S_IFREG | 0o600, uid=1001, gid=1001, nlink=1, size=20, changed=0):
    return types.SimpleNamespace(st_dev=7, st_ino=inode, st_mode=mode,
                                 st_uid=uid, st_gid=gid, st_nlink=nlink,
                                 st_size=size, st_mtime_ns=changed, st_ctime_ns=changed)


def observation(inode):
    return dict(MOD.EXPECTED, dev=7, inode=inode, nlink=1, size=20, mtime_ns=0, ctime_ns=0)


class Reader:
    def __init__(self):
        self.env = ("Linux", 0, MOD.HOST, True)
        self.values = {MOD.BACKUP: observation(11), MOD.TARGET: observation(12)}
        self.calls = []
        self.change = None

    def environment(self):
        return self.env

    def snapshot(self, path):
        self.calls.append(path)
        result = copy.deepcopy(self.values[path])
        if self.change and len(self.calls) > 2 and path == self.change:
            result["ctime_ns"] += 1
        return result


class InspectionTests(unittest.TestCase):
    def test_healthy_is_read_only_and_not_restore_ready(self):
        reader = Reader()
        result, rc = MOD.inspect(reader)
        self.assertEqual((rc, result["status"]), (0, "UNCHANGED_NO_RESTORE_NEEDED"))
        self.assertFalse(result["restore_ready"])
        self.assertFalse(result["runtime_go"])
        self.assertEqual(result["target_write"], "NOT_IMPLEMENTED")
        self.assertEqual(reader.calls, [MOD.BACKUP, MOD.TARGET] * 2)

    def test_backup_label_and_ownership_are_not_destination_expectation(self):
        reader = Reader()
        reader.values[MOD.BACKUP].update(context="system_u:object_r:var_lib_t:s0", uid=0, gid=0)
        result, rc = MOD.inspect(reader)
        self.assertEqual(rc, 0)
        self.assertFalse(result["backup_label_matches_destination_expectation"])
        self.assertEqual(result["expected_destination"]["uid"], 1001)
        self.assertEqual(result["observed"]["backup"]["uid"], 0)

    def test_every_destination_drift_requires_review_and_preserves_input(self):
        changes = {"sha256": "0" * 64, "uid": 0, "gid": 0, "mode": "0644", "context": "system_u:object_r:tmp_t:s0"}
        for key, value in changes.items():
            with self.subTest(key=key):
                reader = Reader()
                reader.values[MOD.TARGET][key] = value
                before = copy.deepcopy(reader.values)
                result, rc = MOD.inspect(reader)
                self.assertEqual((rc, result["destination_drift"]), (2, [key]))
                self.assertEqual(result["status"], "DRIFT_REVIEW_REQUIRED")
                self.assertEqual(reader.values, before)

    def test_backup_corruption_does_not_claim_valid_source(self):
        reader = Reader()
        reader.values[MOD.BACKUP]["sha256"] = "0" * 64
        result, rc = MOD.inspect(reader)
        self.assertEqual((rc, result["error_code"]), (2, "BACKUP_HASH_MISMATCH"))
        self.assertNotIn("observed", result)

    def test_wrong_host_account_platform_and_selinux_stop_before_key_read(self):
        for env in [("Windows", 0, MOD.HOST, True), ("Linux", 1001, MOD.HOST, True),
                    ("Linux", 0, "k8s-worker01", True), ("Linux", 0, MOD.HOST, False)]:
            with self.subTest(env=env):
                reader = Reader()
                reader.env = env
                result, rc = MOD.inspect(reader)
                self.assertEqual(rc, 2)
                self.assertEqual(reader.calls, [])
                self.assertEqual(result["status"], "INCOMPLETE")

    def test_either_snapshot_drift_rejects_report(self):
        for path in [MOD.BACKUP, MOD.TARGET]:
            with self.subTest(path=path):
                reader = Reader()
                reader.change = path
                result, rc = MOD.inspect(reader)
                self.assertEqual((rc, result["error_code"]), (2, "SNAPSHOT_CHANGED_RETRY_REVIEW_REQUIRED"))
                self.assertNotIn("observed", result)

    def test_same_file_source_and_target_rejected(self):
        reader = Reader()
        reader.values[MOD.TARGET]["inode"] = 11
        result, rc = MOD.inspect(reader)
        self.assertEqual((rc, result["error_code"]), (2, "BACKUP_AND_TARGET_SAME_FILE"))

    def test_read_failure_does_not_expose_exception_contents(self):
        reader = Reader()
        with mock.patch.object(reader, "snapshot", side_effect=OSError("SYNTHETIC_SECRET_DO_NOT_OUTPUT")):
            result, rc = MOD.inspect(reader)
        self.assertEqual(rc, 2)
        self.assertNotIn("SYNTHETIC_SECRET", str(result))

    def test_nonregular_link_owner_and_backup_permissions_rejected(self):
        cases = [st(mode=stat.S_IFLNK | 0o600), st(mode=stat.S_IFIFO | 0o600),
                 st(nlink=2), st(uid=123), st(size=0), st(size=MOD.MAX_BYTES + 1), st(mode=stat.S_IFREG | 0o644)]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(MOD.Stop):
                    MOD.check_file(case, True)

    def test_directory_trust_rejects_user_writable_ancestors(self):
        for mode, uid, private in [(0o777, 0, False), (0o775, 0, False),
                                  (0o700, 1001, False), (0o755, 0, True)]:
            with self.subTest(mode=mode, uid=uid, private=private):
                with self.assertRaises(MOD.Stop):
                    MOD.check_directory(st(mode=stat.S_IFDIR | mode, uid=uid), 0, private)

    def test_context_input_cannot_inject_log_lines(self):
        self.assertEqual(MOD.context_text(b"system_u:object_r:var_lib_t:s0\x00"), "system_u:object_r:var_lib_t:s0")
        for value in [b"x\nSECRET", b"u:r:t:s0\n", b"\xff:r:t:s0", b"u:r:t:s0\x00\x00"]:
            with self.subTest(value=value):
                with self.assertRaises(MOD.Stop):
                    MOD.context_text(value)


class FakeKernel:
    """Mock POSIX FD semantics; never touches real keys or OS metadata."""
    def __init__(self, failure=None):
        self.failure = failure
        self.payload = b"SYNTHETIC PUBLIC KEY FIXTURE\n"
        self.paths = {"/": st(inode=1, mode=stat.S_IFDIR | 0o755, uid=0)}
        for i, path in enumerate(["/var", "/var/lib", MOD.BACKUP.rsplit("/", 1)[0]], 2):
            self.paths[path] = st(inode=i, mode=stat.S_IFDIR | (0o700 if i == 4 else 0o755), uid=0)
        self.paths[MOD.BACKUP] = st(inode=5, size=len(self.payload))
        self.opened = {}
        self.closed = []
        self.offset = {}
        self.stat_calls = 0
        self.xattr_calls = 0

    def open(self, path, flags, dir_fd=None):
        if flags & 3 != 0:
            raise AssertionError("write access attempted")
        if not flags & MOD.os.O_NOFOLLOW or not flags & MOD.os.O_CLOEXEC:
            raise AssertionError("descriptor protection missing")
        if dir_fd is not None:
            path = self.opened[dir_fd].rstrip("/") + "/" + path
        if self.failure == "symlink" and path.endswith("NXrcqAmF"):
            raise OSError("NOFOLLOW rejected synthetic symlink")
        fd = 30 + len(self.opened)
        self.opened[fd] = path
        self.offset[fd] = 0
        return fd

    def fstat(self, fd):
        value = copy.copy(self.paths[self.opened[fd]])
        if self.failure == "file_drift" and self.offset[fd]:
            value.st_ctime_ns += 1
        return value

    def stat(self, path, dir_fd=None, follow_symlinks=None):
        assert follow_symlinks is False
        self.stat_calls += 1
        full = self.opened[dir_fd].rstrip("/") + "/" + path
        value = copy.copy(self.paths[full])
        if self.failure == "parent_drift" and self.stat_calls > 4 and full.endswith("NXrcqAmF"):
            value.st_ino += 1
        if self.failure == "path_drift" and self.stat_calls > 4 and full == MOD.BACKUP:
            value.st_ino += 1
        return value

    def read(self, fd, size):
        offset = self.offset[fd]
        self.offset[fd] += size
        return self.payload[offset:offset + size]

    def getxattr(self, fd, name):
        assert name == "security.selinux"
        self.xattr_calls += 1
        return b"u:r:t:s1" if self.failure == "context_drift" and self.xattr_calls > 1 else b"u:r:t:s0"

    def close(self, fd):
        self.closed.append(fd)

    @contextlib.contextmanager
    def install(self):
        with contextlib.ExitStack() as stack:
            for i, name in enumerate(["O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK"]):
                stack.enter_context(mock.patch.object(MOD.os, name, 0x1000 << i, create=True))
            for name in ["open", "fstat", "stat", "read", "getxattr", "close"]:
                stack.enter_context(mock.patch.object(MOD.os, name, getattr(self, name), create=True))
            yield


class DescriptorTests(unittest.TestCase):
    def test_fd_reader_hashes_synthetic_contents_and_closes_descriptors(self):
        kernel = FakeKernel()
        with kernel.install():
            result = MOD.LinuxReader.snapshot(MOD.BACKUP)
        self.assertEqual(result["sha256"], hashlib.sha256(kernel.payload).hexdigest())
        self.assertNotIn(kernel.payload.decode(), str(result))
        self.assertEqual(set(kernel.opened), set(kernel.closed))

    def test_symlink_content_context_parent_and_path_drift_rejected(self):
        for failure in ["symlink", "file_drift", "context_drift", "parent_drift", "path_drift"]:
            with self.subTest(failure=failure):
                kernel = FakeKernel(failure)
                with kernel.install():
                    with self.assertRaises((MOD.Stop, OSError)):
                        MOD.LinuxReader.snapshot(MOD.BACKUP)
                self.assertEqual(set(kernel.opened), set(kernel.closed))

    def test_out_of_scope_path_does_not_open_any_file(self):
        kernel = FakeKernel()
        with kernel.install():
            with self.assertRaises(MOD.Stop):
                MOD.LinuxReader.snapshot("/home/svc_ansible/.ssh/id_ed25519")
        self.assertEqual(kernel.opened, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
