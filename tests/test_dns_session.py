"""Actual temporary-file snapshot tests; no DNS, SSH, sudo or service operation."""
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('dns_session', Path(__file__).resolve().parents[1] / 'library/fds_dns_session.py')
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)


class SessionState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'sessions'
        self.args = dict(session='w02-20261009T150000-1234abcd', source='a' * 40,
                         current={'interface': 'eth0', 'connection': 'System eth0',
                                  'ipv4_dns': '192.0.2.1', 'ipv4_dns_search': 'old.example',
                                  'ipv4_ignore_auto_dns': 'no'},
                         desired={'dns': ['192.0.2.2', '192.0.2.3'],
                                  'search': ['example.test'], 'ignore_auto': True},
                         root=self.root, uid=os.geteuid(),
                         now=datetime.datetime(2026, 10, 9, 6, tzinfo=datetime.timezone.utc))
        self.applied = dict(self.args['current'], ipv4_dns='192.0.2.2,192.0.2.3',
                            ipv4_dns_search='example.test', ipv4_ignore_auto_dns='yes')

    def prepare(self):
        result = session.run('prepare', **self.args)
        self.path = Path(result['path'])
        self.original_bytes = self.path.read_bytes()
        self.args['expected'] = result['sha256']
        return result

    def test_prepare_apply_reapply_and_restore_same_original(self):
        self.prepare()
        self.assertFalse(session.run('apply', **self.args)['changed'])
        for action in ('reapply', 'rollback'):
            result = session.run(action, **dict(self.args, current=self.applied))
            self.assertEqual(result['original'], self.args['current'])
        session.run('rollback', **self.args)
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)

    def test_check_prepare_has_no_file_or_usable_hash(self):
        result = session.run('prepare', **dict(self.args, check=True))
        self.assertFalse(result['snapshot_written'])
        self.assertIsNone(result['sha256'])
        self.assertFalse(self.root.exists())

    def test_duplicate_prepare_never_overwrites(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            session.run('prepare', **dict(self.args, current=self.applied))
        self.assertEqual(self.path.read_bytes(), self.original_bytes)

    def test_interrupted_prepare_directory_not_reused(self):
        (self.root / self.args['session']).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            session.run('prepare', **self.args)

    def test_missing_and_wrong_hash(self):
        self.prepare()
        for expected in ('', '0' * 64):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                session.run('apply', **dict(self.args, expected=expected))

    def test_original_tamper_rejected_by_pinned_hash(self):
        self.prepare()
        self.path.write_bytes(self.original_bytes + b' ')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            session.run('apply', **self.args)

    def test_valid_hash_does_not_replace_binding_checks(self):
        self.prepare()
        data = json.loads(self.original_bytes)
        data['endpoint'] = '192.0.2.99'
        payload = json.dumps(data).encode()
        self.path.write_bytes(payload)
        with self.assertRaisesRegex(ValueError, 'binding mismatch'):
            session.run('apply', **dict(self.args, expected=hashlib.sha256(payload).hexdigest()))

    def test_wrong_source_or_desired(self):
        self.prepare()
        for override in ({'source': 'b' * 40}, {'desired': dict(self.args['desired'], search=['other.test'])}):
            with self.subTest(override=override), self.assertRaisesRegex(ValueError, 'binding mismatch'):
                session.run('apply', **dict(self.args, **override))

    def test_first_apply_rejects_stale_future_or_changed_snapshot(self):
        self.prepare()
        for seconds in (-1, 901):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, '15 minutes'):
                session.run('apply', **dict(self.args, now=self.args['now'] + datetime.timedelta(seconds=seconds)))
        with self.assertRaisesRegex(ValueError, 'unchanged'):
            session.run('apply', **dict(self.args, current=self.applied))

    def test_reapply_does_not_silently_repair_new_drift(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'previously applied'):
            session.run('reapply', **self.args)

    def test_rollback_rejects_unrelated_drift_but_has_no_expiry(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'neither session original nor desired'):
            session.run('rollback', **dict(self.args, current=dict(self.applied, ipv4_dns='192.0.2.99')))
        session.run('rollback', **dict(self.args, current=self.applied,
                                      now=self.args['now'] + datetime.timedelta(days=1)))

    def test_interface_or_connection_change_stops_all_actions(self):
        self.prepare()
        for key in ('interface', 'connection'):
            for action in ('apply', 'reapply', 'rollback'):
                with self.subTest(key=key, action=action), self.assertRaisesRegex(ValueError, 'connection drift'):
                    session.run(action, **dict(self.args, current=dict(self.applied, **{key: 'other'})))

    def test_snapshot_mode_hardlink_symlink_rejected(self):
        self.prepare()
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'mode'):
            session.run('apply', **self.args)
        self.path.chmod(0o600)
        other = self.path.with_name('alias')
        os.link(self.path, other)
        with self.assertRaisesRegex(ValueError, 'link'):
            session.run('apply', **self.args)
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises(OSError):
            session.run('apply', **self.args)

    def test_unsafe_session_directory_and_ancestor_rejected(self):
        self.prepare()
        self.path.parent.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '0700'):
            session.run('apply', **self.args)
        self.path.parent.chmod(0o700)
        self.root.chmod(0o777)
        with self.assertRaisesRegex(ValueError, 'writable'):
            session.run('apply', **self.args)

    def test_path_traversal_or_invalid_source_rejected_without_writes(self):
        for override in ({'session': '../escape'}, {'source': 'abc'}, {'session': None}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                session.run('prepare', **dict(self.args, **override))
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
