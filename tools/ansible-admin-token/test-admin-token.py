import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('admin', ROOT / 'admin-token.py')
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)
SECRET = 'FAKE_SECRET_FOR_LEAK_TEST_' + 'X' * 40


def token():
    return {'token': SECRET, 'expires_at': (admin.utcnow() + dt.timedelta(hours=1)).isoformat()}


def response(code=201, data=None, rc=0, stderr=b''):
    raw = json.dumps(data if data is not None else token()).encode()
    return subprocess.CompletedProcess([], rc, b'HTTP/2.0 ' + str(code).encode() + b' OK\r\nContent-Type: application/json\r\n\r\n' + raw, stderr)


def success_replies():
    return [response(200, {'full_name': admin.REPO, 'permissions': {'admin': True}}), response(), response()]


class Tests(unittest.TestCase):
    def run_case(self, replies=None, failure=None):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            output = io.StringIO()
            with patch.object(admin, 'login_home', return_value=home), \
                 patch.object(admin.os, 'getuid', return_value=1000), \
                 patch.object(admin.socket, 'gethostname', return_value='ansible01'), \
                 patch.object(admin, 'protect_memory', return_value=(0, 0)), \
                 patch.object(admin.shutil, 'which', return_value='/usr/bin/gh'), \
                 patch.object(admin.subprocess, 'run', side_effect=replies or success_replies()) as call, \
                 contextlib.redirect_stdout(output):
                if failure:
                    with failure:
                        rc = admin.main()
                else:
                    rc = admin.main()
            archives = list(home.glob('ansible-admin-token-evidence-*/ansible-admin-token-evidence.tar.gz'))
            self.assertEqual(len(archives), 1)
            archive = archives[0]
            self.assertEqual(stat.S_IMODE(archive.parent.stat().st_mode), 0o700)
            with tarfile.open(archive) as tar:
                self.assertEqual(tar.getnames(), ['evidence/RESULT.json', 'evidence/SHA256SUMS'])
                raw = tar.extractfile('evidence/RESULT.json').read()
                sums = tar.extractfile('evidence/SHA256SUMS').read()
                report = json.loads(raw)
            self.assertEqual(sums, (hashlib.sha256(raw).hexdigest() + '  RESULT.json\n').encode())
            self.assertTrue(archive.with_name(archive.name + '.sha256').read_text().startswith(hashlib.sha256(archive.read_bytes()).hexdigest()))
            self.assertNotIn(SECRET, raw.decode() + output.getvalue())
            self.assertFalse(report['runner_registration_attempted'])
            self.assertFalse(report['actions_executed'])
            packets = list(home.glob('ansible-runner-token-*.json'))
            if rc == 0:
                self.assertEqual(len(packets), 1)
                self.assertEqual(stat.S_IMODE(packets[0].stat().st_mode), 0o600)
                admin.packet(json.loads(packets[0].read_text()))
                self.assertIn('TOKEN_PACKET=', output.getvalue())
            else:
                self.assertEqual(packets, [])
                self.assertNotIn('TOKEN_PACKET=', output.getvalue())
            return report, rc, call.call_count, output.getvalue()

    def test_complete_packet_and_evidence(self):
        report, rc, calls, _ = self.run_case()
        self.assertEqual((rc, calls, report['status']), (0, 3, 'PASS_TOKEN_PACKET'))
        self.assertTrue(all(item['passed'] for item in report['stages']))

    def test_http_401_403_404_preserve_status_without_secrets(self):
        for code in (401, 403, 404):
            with self.subTest(code=code):
                report, rc, calls, _ = self.run_case([response(code, {'message': SECRET}, 1, SECRET.encode())])
                self.assertEqual((rc, calls, report['error_code']), (1, 1, 'API_COMMAND_FAILED'))
                self.assertEqual(report['stages'][-1]['http_status'], code)
                self.assertFalse(report['token_post_attempted'])

    def test_registration_fail_stops_before_removal(self):
        report, rc, calls, _ = self.run_case([success_replies()[0], response(403, {'message': SECRET}, 1)])
        self.assertEqual((rc, calls, report['stages'][-1]['stage']), (1, 2, 'registration-token'))

    def test_partial_issuance_does_not_write_packet(self):
        report, rc, calls, _ = self.run_case(success_replies()[:2] + [response(403, {'message': SECRET}, 1)])
        self.assertEqual((rc, calls, report['stages'][-1]['stage']), (1, 3, 'removal-token'))
        self.assertTrue(report['token_post_attempted'])

    def test_timeout_discards_captured_output(self):
        error = subprocess.TimeoutExpired('gh', 60, output=SECRET.encode(), stderr=SECRET.encode())
        report, rc, _, _ = self.run_case([error])
        self.assertEqual((rc, report['error_code']), (1, 'API_TIMEOUT'))
        self.assertTrue(report['stages'][-1]['timed_out'])

    def test_spawn_error_does_not_log_exception_text(self):
        report, rc, _, _ = self.run_case([PermissionError(13, SECRET)])
        self.assertEqual((rc, report['error_code'], report['stages'][-1]['errno']), (1, 'GH_SPAWN_FAILED', 13))

    def test_prctl_failure_stops_before_api(self):
        report, rc, calls, _ = self.run_case(failure=patch.object(admin, 'protect_memory', return_value=(-1, 1)))
        self.assertEqual((rc, calls, report['error_code']), (1, 0, 'MEMORY_PROTECTION_FAILED'))

    def test_gh_missing_stops_before_api(self):
        report, rc, calls, _ = self.run_case(failure=patch.object(admin.shutil, 'which', return_value=None))
        self.assertEqual((rc, calls, report['error_code']), (1, 0, 'GH_NOT_FOUND'))

    def test_wrong_host_stops_before_api(self):
        report, rc, calls, _ = self.run_case(failure=patch.object(admin.socket, 'gethostname', return_value='cicd-runner01'))
        self.assertEqual((rc, calls, report['error_code']), (1, 0, 'ANSIBLE01_REQUIRED'))

    def test_root_refused_before_evidence_or_api(self):
        output = io.StringIO()
        with patch.object(admin.os, 'getuid', return_value=0), \
             patch.object(admin.subprocess, 'run') as call, contextlib.redirect_stdout(output):
            self.assertEqual(admin.main(), 1)
        call.assert_not_called()
        self.assertEqual(output.getvalue(), 'STOP: LOGIN_USER_REQUIRED\n')

    def test_repository_mismatch_stops_before_post(self):
        report, rc, calls, _ = self.run_case([response(200, {'full_name': '321Team/infra-cicd'})])
        self.assertEqual((rc, calls, report['error_code']), (1, 1, 'REPOSITORY_MISMATCH'))
        self.assertFalse(report['token_post_attempted'])

    def test_missing_token_fields_fail_without_partial_packet(self):
        report, rc, calls, _ = self.run_case([success_replies()[0], response(data={'message': SECRET})])
        self.assertEqual((rc, calls, report['error_code']), (1, 2, 'TOKEN_RESPONSE_FIELDS_MISSING'))

    def test_partial_packet_write_failure_removes_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(admin.os, 'fsync', side_effect=OSError(28, SECRET)):
                with self.assertRaises(OSError):
                    admin.write_packet(Path(temporary), {'token': SECRET})
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_expired_and_future_tokens_report_numeric_time(self):
        for seconds in (-100, 300, 8000):
            bad = token()
            bad['expires_at'] = (admin.utcnow() + dt.timedelta(seconds=seconds)).isoformat()
            report, rc, _, _ = self.run_case([success_replies()[0], response(data=bad), response()])
            self.assertEqual((rc, report['error_code']), (1, 'TOKEN_LIFETIME_OUT_OF_RANGE'))
            self.assertIn('remaining_seconds', report['stages'][-1])

    def test_invalid_token_and_expiry_do_not_leak(self):
        for bad, expected in (({'token': SECRET + '\n', 'expires_at': token()['expires_at']}, 'TOKEN_FORMAT_INVALID'),
                              ({'token': SECRET, 'expires_at': SECRET}, 'TOKEN_EXPIRY_INVALID')):
            report, rc, _, _ = self.run_case([success_replies()[0], response(data=bad), response()])
            self.assertEqual((rc, report['error_code']), (1, expected))

    def test_write_failure_does_not_leak(self):
        report, rc, _, _ = self.run_case(failure=patch.object(admin, 'write_packet', side_effect=OSError(28, SECRET)))
        self.assertEqual((rc, report['error_code'], report['errno']), (1, 'UNEXPECTED_ERROR', 28))

    def test_unknown_exception_does_not_leak(self):
        report, rc, _, _ = self.run_case(failure=patch.object(admin, 'execute', side_effect=RuntimeError(SECRET)))
        self.assertEqual((rc, report['error_code']), (1, 'UNEXPECTED_ERROR'))

    def test_api_contract_and_environment(self):
        stage = {}
        with patch.dict(os.environ, {'GH_DEBUG': 'api', 'GH_FORCE_TTY': '1', 'GH_TOKEN': SECRET}), \
             patch.object(admin.subprocess, 'run', return_value=response()) as call:
            admin.api('/usr/bin/gh', 'POST', 'repos/' + admin.REPO + '/actions/runners/registration-token', stage)
        args, kwargs = call.call_args
        self.assertNotIn(SECRET, repr(args))
        self.assertNotIn('GH_DEBUG', kwargs['env'])
        self.assertNotIn('GH_FORCE_TTY', kwargs['env'])
        self.assertEqual(kwargs['env']['GH_TOKEN'], SECRET)
        self.assertEqual(args[0][2:4], ['--hostname', 'github.com'])
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(kwargs['timeout'], 60)

    def test_malformed_json_and_wrong_http_fail(self):
        for reply, code in ((subprocess.CompletedProcess([], 0, b'HTTP/2.0 201 OK\n\n' + SECRET.encode(), b''), 'API_JSON_INVALID'),
                            (response(200), 'API_HTTP_RESPONSE_INVALID'),
                            (response(data=[]), 'API_OBJECT_REQUIRED')):
            with patch.object(admin.subprocess, 'run', return_value=reply):
                with self.assertRaises(admin.Stop) as error:
                    admin.api('/usr/bin/gh', 'POST', 'fixed', {})
                self.assertEqual(error.exception.code, code)

    def test_failure_hints_and_stderr_status(self):
        for raw, hint in ((b'gh auth login', 'AUTH_LOGIN_REQUIRED'), (b'x509: invalid', 'TLS_CERTIFICATE_ERROR'), (b'no such host', 'DNS_LOOKUP_FAILED')):
            report, rc, _, _ = self.run_case([subprocess.CompletedProcess([], 1, b'', raw + b' (HTTP 403) ' + SECRET.encode())])
            self.assertEqual((rc, report['stages'][-1]['hint'], report['stages'][-1]['http_status']), (1, hint, 403))

    def test_evidence_failure_removes_new_packet(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = admin.write_packet(home, {'token': SECRET})
            output = io.StringIO()
            with patch.object(admin, 'login_home', return_value=home), \
                 patch.object(admin, 'execute', return_value=path), \
                 patch.object(admin, 'export_evidence', side_effect=OSError(28, SECRET)), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(admin.main(), 1)
            self.assertFalse(path.exists())
            self.assertNotIn(SECRET, output.getvalue())
            self.assertIn('EVIDENCE_WRITE_FAILED', output.getvalue())

    def test_actual_child_http_parse(self):
        # Real local subprocess; no network or GitHub credentials are used.
        with tempfile.TemporaryDirectory() as temporary:
            child = Path(temporary) / 'fake-gh'
            child.write_text('#!/bin/sh\nprintf \'HTTP/2.0 200 OK\\r\\n\\r\\n{"full_name":"321Team/infra-ansible"}\'\n')
            child.chmod(0o700)
            stage = {}
            self.assertEqual(admin.api(str(child), 'GET', 'fixed', stage)['full_name'], admin.REPO)
            self.assertEqual((stage['returncode'], stage['http_status']), (0, 200))


if __name__ == '__main__':
    unittest.main(verbosity=2)
