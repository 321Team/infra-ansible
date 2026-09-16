"""File/protocol regression tests; GitHub and Podman are NOT executed."""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import common
import container
import runner

NAME = 'ansible-ci-' + 'b' * 32
BOM = b'\xef\xbb\xbf'
SECRET = 'DUMMY_PRIVATE_MUST_NOT_EXPORT'


def settings(**updates):
    value = {'agentId': 7, 'agentName': NAME, 'gitHubUrl': common.URL,
             'serverUrl': SECRET, 'poolName': SECRET}
    value.update(updates)
    return value


class IdentityTests(unittest.TestCase):
    def parse(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.runner'
            path.write_bytes(data)
            checks = {}
            value = container.registered_identity(path, NAME, checks)
            return value, checks

    def test_old_read_text_json_path_rejects_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / '.runner'
            p.write_bytes(BOM + json.dumps(settings()).encode())
            with self.assertRaises(json.JSONDecodeError):
                json.loads(p.read_text(encoding='utf-8'))

    def test_bom_and_plain_utf8_keep_exact_identity(self):
        for prefix in (BOM, b''):
            with self.subTest(bom=bool(prefix)):
                value, checks = self.parse(prefix + json.dumps(settings()).encode())
                self.assertEqual(value, {'agentId': 7, 'agentName': NAME, 'gitHubUrl': common.URL})
                self.assertEqual(checks, {'utf8_bom': bool(prefix), 'json_parsed': True,
                    'object': True, 'url_matches': True, 'name_matches': True, 'id_valid': True})
                self.assertNotIn(SECRET, json.dumps([value, checks]))

    def test_wrong_identity_and_invalid_ids_rejected(self):
        for value in (settings(gitHubUrl='https://github.com/321Team/infra-cicd'),
                settings(gitHubUrl=None), settings(agentName='existing-runner'),
                *(settings(agentId=x) for x in (True, 0, -1, '7', 1.5, 2**53)), []):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    self.parse(BOM + json.dumps(value).encode())

    def test_malformed_json_and_encoding_rejected(self):
        for data in (BOM + b'{', b'\xff', BOM + BOM + b'{}', b'\xff\xfe{\x00}\x00'):
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)):
                self.parse(data)

    def test_bounded_regular_file_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.runner'
            path.write_bytes(b'x' * 32769)
            with self.assertRaises(RuntimeError):
                container.registered_identity(path, NAME, {})
            link = Path(folder) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                container.registered_identity(link, NAME, {})
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                container.registered_identity(path, NAME, {})


class RegistrationFlowTests(unittest.TestCase):
    def flow(self, data, configure_rc=0, remove_rc=0):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            target = root / 'runner'
            calls = []
            def native(args, stage, token=None, timeout=180):
                calls.append(stage)
                if stage == 'configure':
                    if configure_rc == 0:
                        (target / '.runner').write_bytes(data)
                    return configure_rc
                self.assertEqual(stage, 'remove')
                if remove_rc == 0:
                    (target / '.runner').unlink()
                return remove_rc
            replacements = {'SESSION': root, 'RUNNER': target, 'RESULT': root / 'CONTAINER_RESULT.json',
                'EVENTS': root / 'EVENTS.jsonl', 'Bridge': MagicMock(), 'isolation': MagicMock(),
                'event': MagicMock(), 'native': native,
                'packet': lambda _: {'registration': {'token': SECRET}, 'removal': {'token': SECRET}}}
            for name, value in replacements.items():
                stack.enter_context(patch.object(container, name, value))
            stack.enter_context(patch.object(container.ctypes, 'CDLL', return_value=SimpleNamespace(prctl=lambda *a: 0)))
            stack.enter_context(patch.object(container.threading, 'Thread'))
            stack.enter_context(patch.object(container.shutil, 'copytree', side_effect=lambda a, b: b.mkdir()))
            stack.enter_context(patch.object(container.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=common.VERSION + '\n', stderr='')))
            stack.enter_context(patch.object(sys, 'argv', ['container.py', 'registration-check']))
            stack.enter_context(patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'{}\n'))))
            stack.enter_context(patch.dict(os.environ, {'FDS_RUNNER_NAME': NAME}))
            rc = container.main()
            raw = json.loads((root / 'CONTAINER_RESULT.json').read_text())
            clean = runner.clean_result(raw, 'registration-check', NAME)
            self.assertNotIn(SECRET, json.dumps(clean))
            return rc, clean, calls

    def test_bom_registration_configure_identity_remove_pass(self):
        rc, value, calls = self.flow(BOM + json.dumps(settings()).encode())
        self.assertEqual((rc, calls), (0, ['configure', 'remove']))
        self.assertEqual(value['status'], 'PASS_REGISTRATION_CHECK')
        self.assertTrue(value['identity_checks']['utf8_bom'])
        self.assertTrue(runner.container_ok('registration-check', value, rc,
            {'Status': 'exited', 'ExitCode': 0, 'OOMKilled': False}, dict.fromkeys(runner.ISOLATION_KEYS, True)))
        self.assertNotIn('failure_phase', value)

    def test_plain_registration_pass(self):
        rc, value, _ = self.flow(json.dumps(settings()).encode())
        self.assertEqual(rc, 0)
        self.assertFalse(value['identity_checks']['utf8_bom'])

    def test_broken_json_recovery_remove_stays_fail_with_diagnostics(self):
        rc, value, calls = self.flow(BOM + b'{')
        self.assertEqual((rc, calls), (1, ['configure', 'remove']))
        self.assertEqual((value['configure_rc'], value['remove_rc'], value['status']), (0, 0, 'FAIL'))
        self.assertEqual(value['failure_phase'], 'registered-identity')
        self.assertEqual(value['error_type'], 'JSONDecodeError')
        self.assertEqual(value['identity_checks'], {'utf8_bom': True})
        self.assertNotIn('runner', value)

    def test_wrong_repository_recovery_does_not_accept_identity(self):
        rc, value, calls = self.flow(json.dumps(settings(gitHubUrl=SECRET)).encode())
        self.assertEqual((rc, calls), (1, ['configure', 'remove']))
        self.assertFalse(value['identity_checks']['url_matches'])
        self.assertNotIn('runner', value)
        self.assertEqual(value['error_type'], 'RuntimeError')

    def test_remove_failure_stays_fail_and_preserves_exact_id(self):
        rc, value, calls = self.flow(BOM + json.dumps(settings()).encode(), remove_rc=1)
        self.assertEqual((rc, calls), (1, ['configure', 'remove']))
        self.assertEqual(value['status'], 'FAIL')
        self.assertEqual(value['failure_phase'], 'remove')
        self.assertEqual(value['runner']['agentId'], 7)

    def test_configure_failure_does_not_invent_identity_or_remove(self):
        rc, value, calls = self.flow(b'', configure_rc=1)
        self.assertEqual((rc, calls), (1, ['configure']))
        self.assertEqual(value['failure_phase'], 'configure')
        self.assertNotIn('runner', value)

    def test_only_fixed_diagnostics_exported(self):
        raw = {'mode': 'registration-check', 'status': 'FAIL', 'error_type': SECRET,
               'failure_phase': SECRET, 'error_message': SECRET,
               'identity_checks': {'utf8_bom': True, 'url_matches': SECRET, 'json_parsed': 1, SECRET: SECRET}}
        value = runner.clean_result(raw, 'registration-check', NAME)
        self.assertEqual(value['error_type'], 'OTHER')
        self.assertNotIn('failure_phase', value)
        self.assertEqual(value['identity_checks'], {'utf8_bom': True})
        self.assertNotIn(SECRET, json.dumps(value))


if __name__ == '__main__':
    unittest.main(verbosity=2)
