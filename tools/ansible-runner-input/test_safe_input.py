"""Synthetic filesystem regressions; production credentials are never needed."""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("safe_input", Path(__file__).with_name("safe_input.py"))
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="ansible-input-unit-", dir=pwd.getpwuid(os.getuid()).pw_dir)
        self.root = Path(self.temp.name)
        self.uid = os.getuid()
        self.fd = os.open(self.root, guard.DIR_FLAGS)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.close, self.fd)
        self.moment = dt.datetime(2026, 9, 16, 18, tzinfo=dt.timezone.utc)
        self.path = self.root / "ansible-runner-token-synthetic.json"
        self.record = {"status": "FAIL", "error_code": None,
                       "input_validated": False, "permission_changed": False}

    def value(self):
        expiry = (self.moment + dt.timedelta(minutes=60)).isoformat()
        return {"repository": guard.REPOSITORY,
                "registration": {"token": "SYNTHETIC_REGISTRATION_12345", "expires_at": expiry},
                "removal": {"token": "SYNTHETIC_REMOVAL_1234567890", "expires_at": expiry}}

    def put(self, value=None, raw=None, mode=0o644):
        data = raw if raw is not None else json.dumps(value or self.value()).encode()
        self.path.write_bytes(data)
        self.path.chmod(mode)
        return data

    def protect(self):
        guard.protect_token(self.fd, self.path.name, self.uid, self.moment, self.record)

    def rejected_unchanged(self):
        before = self.path.lstat()
        with patch.object(guard.os, "fchmod", wraps=os.fchmod) as change:
            with self.assertRaises((guard.Rejected, OSError)):
                self.protect()
            change.assert_not_called()
        self.assertEqual(stat.S_IMODE(before.st_mode), stat.S_IMODE(self.path.lstat().st_mode))
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.record["permission_changed"])

    def test_valid_regular_file_only_changes_its_mode(self):
        data = self.put()
        self.protect()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.read_bytes(), data)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.record["status"], "PASS_TOKEN_INPUT")
        self.assertTrue(self.record["permission_changed"])

    def test_valid_0600_is_idempotent(self):
        self.put(mode=0o600)
        with patch.object(guard.os, "fchmod", wraps=os.fchmod) as change:
            self.protect()
            change.assert_not_called()
        self.assertEqual(self.record["status"], "PASS_TOKEN_INPUT")

    def test_reject_home_and_noncanonical_paths(self):
        bad = [str(self.root), "", "relative.json", "/", str(self.root) + "/",
               str(self.root) + "//" + self.path.name,
               str(self.root) + "/../" + self.path.name,
               str(self.path) + "/", str(self.path) + "\n",
               "/outside/" + self.path.name, str(self.root) + "/ordinary.json"]
        with patch.object(guard.os, "fchmod", wraps=os.fchmod) as change:
            for path in bad:
                with self.subTest(path=path), self.assertRaises(guard.Rejected):
                    guard.token_basename(path, str(self.root))
            change.assert_not_called()
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(guard.token_basename(str(self.path), str(self.root)), self.path.name)

    def test_directory_disguised_as_token(self):
        self.path.mkdir(mode=0o700)
        self.rejected_unchanged()

    def test_missing_file(self):
        with patch.object(guard.os, "fchmod", wraps=os.fchmod) as change:
            with self.assertRaises(FileNotFoundError):
                self.protect()
            change.assert_not_called()

    def test_file_symlink(self):
        self.path.symlink_to(self.root)
        self.rejected_unchanged()

    def test_hardlink(self):
        self.put()
        other = self.root / "other.json"
        os.link(self.path, other)
        self.rejected_unchanged()
        self.assertEqual(other.stat().st_mode & 0o777, 0o644)

    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        os.mkfifo(self.path, 0o600)
        previous = signal.signal(signal.SIGALRM, lambda *_: self.fail("FIFO open blocked"))
        signal.alarm(3)
        try:
            self.rejected_unchanged()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)

    def test_owner_mismatch(self):
        self.put()
        before = self.path.stat().st_mode
        with patch.object(guard.os, "fchmod", wraps=os.fchmod) as change:
            with self.assertRaises(guard.Rejected):
                guard.protect_token(self.fd, self.path.name, self.uid + 10000,
                                    self.moment, self.record)
            change.assert_not_called()
        self.assertEqual(self.path.stat().st_mode, before)

    def test_special_permission_bits(self):
        self.put(mode=0o4644)
        self.rejected_unchanged()

    def test_empty_oversized_malformed_duplicate_json(self):
        samples = [b"", b"x" * (guard.MAX_BYTES + 1), b"not-json",
                   b'{"repository":"one","repository":"two"}', b"\xff"]
        for raw in samples:
            with self.subTest(length=len(raw)):
                self.put(raw=raw)
                self.rejected_unchanged()
                self.assertEqual(self.path.read_bytes(), raw)

    def test_packet_schema_repository_token_and_expiry(self):
        values = []
        value = self.value(); value["repository"] = "321Team/infra-cicd"; values.append(value)
        value = self.value(); del value["removal"]; values.append(value)
        value = self.value(); value["extra"] = "secret"; values.append(value)
        value = self.value(); value["registration"]["token"] = "short"; values.append(value)
        for expiry in ((self.moment - dt.timedelta(seconds=1)).isoformat(),
                       (self.moment + dt.timedelta(minutes=9)).isoformat(),
                       (self.moment + dt.timedelta(hours=3)).isoformat(),
                       "2026-09-16T19:00:00", None, "broken"):
            value = self.value(); value["removal"]["expires_at"] = expiry; values.append(value)
        for value in values:
            with self.subTest(value=value):
                data = self.put(value=value)
                self.rejected_unchanged()
                self.assertEqual(self.path.read_bytes(), data)

    def test_exact_expiry_boundaries(self):
        for minutes in (10, 120):
            value = self.value()
            for kind in ("registration", "removal"):
                value[kind]["expires_at"] = (self.moment + dt.timedelta(minutes=minutes)).isoformat()
            guard.validate_packet(json.dumps(value).encode(), self.moment)

    def test_home_open_and_symlinked_component(self):
        opened = guard.open_home(str(self.root), self.uid)
        os.close(opened)
        target = self.root / "real"; target.mkdir()
        linked = self.root / "linked"; linked.symlink_to(target, target_is_directory=True)
        for path in (linked, linked / "child"):
            with self.subTest(path=path), self.assertRaises(OSError):
                guard.open_home(str(path), self.uid)

    def test_insecure_home_refused_without_fixing_it(self):
        self.root.chmod(0o777)
        try:
            with self.assertRaises(guard.Rejected):
                guard.open_home(str(self.root), self.uid)
            self.assertEqual(self.root.stat().st_mode & 0o777, 0o777)
        finally:
            self.root.chmod(0o700)  # Test fixture only.

    def test_path_swap_never_chmods_directory(self):
        self.put()
        original = self.root / "moved-original.json"
        real_fchmod = os.fchmod
        def swap_then_chmod(fd, mode):
            self.path.rename(original)
            self.path.mkdir(mode=0o700)
            real_fchmod(fd, mode)
        with patch.object(guard.os, "fchmod", side_effect=swap_then_chmod):
            with self.assertRaises(guard.Rejected):
                self.protect()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(original.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.record["status"], "FAIL")

    def test_main_rejected_input_has_home_evidence_without_raw_exception(self):
        output = io.StringIO()
        with patch.object(guard, "production_home", return_value=(str(self.root), self.uid)):
            with contextlib.redirect_stdout(output):
                rc = guard.main(["--token-file", str(self.root)])
        self.assertEqual(rc, 1)
        files = list(self.root.glob("ansible-token-input-evidence-*/RESULT.json"))
        self.assertEqual(len(files), 1)
        data = files[0].read_bytes()
        self.assertEqual(json.loads(data)["error_code"], "PATH_REJECTED")
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(files[0].parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(files[0].with_name("RESULT.json.sha256").read_text(),
                         hashlib.sha256(data).hexdigest() + "  RESULT.json\n")
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_unexpected_exception_is_redacted(self):
        output = io.StringIO()
        secret = "SYNTHETIC_SECRET_DO_NOT_LOG_12345"
        with patch.object(guard, "production_home", side_effect=RuntimeError(secret)):
            with contextlib.redirect_stdout(output):
                rc = guard.main(["--token-file", str(self.path)])
        self.assertEqual(rc, 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn("IO_OR_RUNTIME_ERROR", output.getvalue())

    def test_root_cli_identity_is_rejected(self):
        with patch.object(guard.os, "getuid", return_value=0):
            with patch.object(guard.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(guard.Rejected, "LOGIN_REJECTED"):
                    guard.production_home()

    def test_argument_errors_do_not_echo_supplied_values(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as stopped:
            guard.main(["--unknown", "SYNTHETIC_SECRET_DO_NOT_LOG"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn("SYNTHETIC_SECRET_DO_NOT_LOG", output.getvalue())
        self.assertIn("ARGUMENT_REJECTED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
