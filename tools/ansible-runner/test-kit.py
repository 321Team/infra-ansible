"""Local policy/boundary tests. These do not claim a Podman or GitHub run."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import common
import container
import launch
import proxy
import runner


def token_packet():
    return {'repository': common.REPO, 'registration': {'token': 'R'*40, 'expires_at': '2026-09-16T13:00:00Z'},
            'removal': {'token': 'D'*40, 'expires_at': '2026-09-16T13:00:00Z'}}


MOMENT = dt.datetime(2026, 9, 16, 12, 15, tzinfo=dt.timezone.utc)
IMAGE = 'sha256:' + 'a'*64
NAME = 'ansible-ci-' + 'b'*32


class PolicyTests(unittest.TestCase):
    def test_proxy_allowed_targets(self):
        for host in (*proxy.EXACT, 'pipelines.actions.githubusercontent.com', 'results.blob.core.windows.net'):
            with self.subTest(host=host):
                self.assertEqual(proxy.target(f'CONNECT {host}:443 HTTP/1.1'.encode()), host)

    def test_proxy_rejected_targets(self):
        for line in (b'CONNECT 127.0.0.1:443 HTTP/1.1', b'CONNECT 10.1.93.102:443 HTTP/1.1',
                     b'CONNECT 169.254.169.254:443 HTTP/1.1', b'CONNECT [::1]:443 HTTP/1.1',
                     b'CONNECT github.com.evil.invalid:443 HTTP/1.1', b'CONNECT github.com:80 HTTP/1.1',
                     b'CONNECT evilgithub.com:443 HTTP/1.1', b'CONNECT github.com.:443 HTTP/1.1',
                     b'CONNECT user@github.com:443 HTTP/1.1', b'GET https://github.com/ HTTP/1.1',
                     b'CONNECT -x.actions.githubusercontent.com:443 HTTP/1.1',
                     b'CONNECT .actions.githubusercontent.com:443 HTTP/1.1',
                     b'CONNECT github.com:443 HTTP/2', b'CONNECT github.com:443 HTTP/1.1\x00'):
            with self.subTest(line=line):
                self.assertRaises(ValueError, proxy.target, line)

    def test_dns_private_mixed_and_empty_denied(self):
        def row(address):
            return (socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))
        for ips in ([], ['127.0.0.1'], ['10.0.0.1'], ['169.254.169.254'], ['::1'], ['fc00::1'],
                    ['224.0.0.1'], ['100.64.0.1'], ['8.8.8.8', '10.0.0.1'], ['::ffff:127.0.0.1']):
            with self.subTest(ips=ips):
                self.assertRaises(ValueError, proxy.addresses, 'github.com', lambda *a, **k: [row(x) for x in ips])

    def test_dns_public_preserved(self):
        values = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('140.82.112.3', 443))]
        self.assertIs(proxy.addresses('github.com', lambda *a, **k: values), values)

    def test_token_packet_valid_and_rejections(self):
        self.assertIs(common.packet(token_packet(), MOMENT)['repository'], common.REPO)
        changes = [lambda x: x.update(repository='321Team/infra-cicd'),
                   lambda x: x['registration'].update(token='x\n'+'R'*40),
                   lambda x: x['registration'].update(expires_at='2026-09-16T12:20:00Z'),
                   lambda x: x['removal'].update(expires_at='2026-09-16T18:00:00Z'),
                   lambda x: x.update(extra=True), lambda x: x.pop('removal'),
                   lambda x: x['removal'].update(expires_at='2026-09-16T13:00:00')]
        for change in changes:
            value = token_packet(); change(value)
            with self.subTest(value_keys=list(value)):
                self.assertRaises((RuntimeError, ValueError), common.packet, value, MOMENT)

    def test_token_file_mode_owner_and_links(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'token'
            path.write_bytes(b'dummy'); path.chmod(0o600)
            self.assertEqual(common.read_regular(path, 10, os.getuid()), b'dummy')
            self.assertRaises(RuntimeError, common.read_regular, path, 3, os.getuid())
            path.chmod(0o644)
            self.assertRaises(RuntimeError, common.read_regular, path, 10, os.getuid())
            path.chmod(0o600)
            link = Path(folder) / 'link'; link.symlink_to(path)
            self.assertRaises(OSError, common.read_regular, link)
            hard = Path(folder) / 'hard'; os.link(path, hard)
            self.assertRaises(RuntimeError, common.read_regular, path)

    def test_manifest_mutations_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); f = root / 'code.py'; f.write_text('value = 1\n')
            sums = root / 'SHA256SUMS'; sums.write_text(common.digest(f)+'  code.py\n')
            self.assertEqual(common.manifest(root), common.digest(sums))
            f.write_text('value = 2\n')
            self.assertRaises(RuntimeError, common.manifest, root)
            sums.write_text(common.digest(f)+'  code.py\n')
            (root / 'unexpected').write_text('x')
            self.assertRaises(RuntimeError, common.manifest, root)

    def test_commands_enforce_isolation(self):
        main = runner.podman_command('runner', IMAGE, Path('/dedicated/fresh'), NAME, 'prepare')
        side = runner.podman_command('proxy', IMAGE, Path('/dedicated/fresh'), NAME, 'prepare')
        self.assertIn('--network=none', main)
        self.assertIn('--network=pasta', side)
        self.assertIn('/dedicated/fresh/proxy:/proxy:ro,z', main)
        for args in (main, side):
            for flag in ('--cap-drop=ALL', '--security-opt=no-new-privileges', '--read-only',
                         '--userns=keep-id:uid=1000,gid=1000', '--log-driver=none'):
                self.assertIn(flag, args)
            for forbidden in ('--privileged', '--network=host', '/var/run', 'docker.sock', 'podman.sock', 'token'):
                self.assertNotIn(forbidden, ' '.join(args))

    def test_manifest_rejects_linked_directory_even_if_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'bundle'; root.mkdir()
            external = Path(folder) / 'external'; external.mkdir()
            (root / 'SHA256SUMS').write_text('')
            (root / 'linked').symlink_to(external, target_is_directory=True)
            self.assertRaises(RuntimeError, common.manifest, root)

    def test_token_only_config_child_env(self):
        secret = 'DUMMY'*10
        self.assertEqual(container.runner_env(secret)['ACTIONS_RUNNER_INPUT_TOKEN'], secret)
        self.assertNotIn('ACTIONS_RUNNER_INPUT_TOKEN', container.runner_env())
        self.assertNotIn(secret, ' '.join(runner.podman_command('runner', IMAGE, Path('/run'), NAME, 'serve')))


class FakePeer:
    def __init__(self, blocks=()):
        self.blocks, self.sent, self.connected = list(blocks), [], None
    def settimeout(self, value):
        pass
    def recv(self, size):
        return self.blocks.pop(0) if self.blocks else b''
    def sendall(self, data):
        self.sent.append(data)
    def connect(self, address):
        self.connected = address
    def close(self):
        pass


class ProtocolTests(unittest.TestCase):
    def test_public_connect_uses_validated_ip_without_reresolution(self):
        client = FakePeer([b'CONNECT github.com:443 HTTP/1.1\r\nHost: github.com\r\n\r\n'])
        remote = FakePeer()
        values = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('140.82.112.3', 443))]
        with patch.object(proxy, 'addresses', return_value=values) as addresses, patch.object(proxy.socket, 'socket', return_value=remote), patch.object(proxy, 'relay') as relay:
            proxy.Handler(client, None, None)
        addresses.assert_called_once_with('github.com')
        self.assertEqual(remote.connected, values[0][4])
        self.assertEqual(client.sent, [b'HTTP/1.1 200 Connection Established\r\n\r\n'])
        relay.assert_called_once_with(client, remote)

    def test_invalid_pre_tunnel_payload_and_oversized_headers_rejected(self):
        for data in (b'CONNECT github.com:443 HTTP/1.1\r\n\r\nEXTRA', b'X'*16385,
                     b'CONNECT 10.0.0.1:443 HTTP/1.1\r\n\r\n', b''):
            client = FakePeer([data])
            with patch.object(proxy, 'addresses') as addresses:
                proxy.Handler(client, None, None)
            addresses.assert_not_called()
            self.assertTrue(client.sent[0].startswith(b'HTTP/1.1 403'))

    def test_dns_denial_never_opens_upstream(self):
        client = FakePeer([b'CONNECT github.com:443 HTTP/1.1\r\n\r\n'])
        with patch.object(proxy, 'addresses', side_effect=ValueError), patch.object(proxy.socket, 'socket') as make_socket:
            proxy.Handler(client, None, None)
        make_socket.assert_not_called()
        self.assertTrue(client.sent[0].startswith(b'HTTP/1.1 403'))


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.state = {'Status': 'exited', 'ExitCode': 0, 'OOMKilled': False}
        self.checks = dict.fromkeys(runner.ISOLATION_KEYS, True)
        self.result = {'mode': 'prepare', 'status': 'PASS_PREPARE_CONTAINER', 'listener_version_matches': True}

    def test_prepare_requires_all_conditions(self):
        self.assertTrue(runner.container_ok('prepare', self.result, 0, self.state, self.checks, True))
        for rc in (1, -15, None, False):
            self.assertFalse(runner.container_ok('prepare', self.result, rc, self.state, self.checks, True))
        for field, value in (('Status', 'running'), ('ExitCode', 1), ('OOMKilled', True), ('OOMKilled', None)):
            state = dict(self.state, **{field: value})
            self.assertFalse(runner.container_ok('prepare', self.result, 0, state, self.checks, True))
        self.assertFalse(runner.container_ok('prepare', self.result, 0, self.state, self.checks, False))
        for key in self.checks:
            checks = dict(self.checks); checks.pop(key)
            self.assertFalse(runner.container_ok('prepare', self.result, 0, self.state, checks, True))

    def test_export_discards_unknown_fields_and_tokens(self):
        value = dict(self.result, arbitrary='SECRET', error_type='SECRET', reported_job_result='SECRET',
                     runner={'gitHubUrl': common.URL, 'agentName': NAME, 'agentId': 7, 'poolName': 'SECRET'})
        result = runner.clean_result(value, 'prepare', NAME)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(result['runner'], {'gitHubUrl': common.URL, 'agentName': NAME, 'agentId': 7})
        self.assertRaises(RuntimeError, runner.clean_result, {}, 'prepare', NAME)

    def test_registration_requires_removal_and_identity(self):
        result = {'status': 'PASS_REGISTRATION_CHECK', 'listener_version_matches': True,
                  'configure_rc': 0, 'remove_rc': 0, 'runner': {'agentId': 7}}
        self.assertTrue(runner.container_ok('registration-check', result, 0, self.state, self.checks))
        result['remove_rc'] = 1
        self.assertFalse(runner.container_ok('registration-check', result, 0, self.state, self.checks))
        result['remove_rc'] = 0; result.pop('runner')
        self.assertFalse(runner.container_ok('registration-check', result, 0, self.state, self.checks))

    def test_serve_is_not_ci_success(self):
        result = {'status': 'SESSION_ENDED', 'listener_version_matches': True, 'configure_rc': 0,
                  'listener_rc': 0, 'runner': {'agentId': 7}, 'job_finished_observed': True, 'reported_job_result': 'Failed'}
        self.assertTrue(runner.container_ok('serve', result, 0, self.state, self.checks))
        result['job_finished_observed'] = False
        self.assertFalse(runner.container_ok('serve', result, 0, self.state, self.checks))
        self.assertEqual(runner.STATES['serve'], 'SESSION_ENDED_REQUIRES_CI_REVIEW')

    def test_network_probe_completeness(self):
        rows = [{'target': x, 'status': 200, 'tls_http_reached': True} for x in runner.PROBE_ALLOW]
        rows += [{'target': x, 'denied': True} for x in runner.PROBE_DENY]
        value = {'results': rows, 'passed': True}
        self.assertTrue(runner.clean_probe(value)['passed'])
        value['results'][0]['status'] = 502
        self.assertFalse(runner.clean_probe(value)['passed'])
        value['results'].pop()
        self.assertRaises(RuntimeError, runner.clean_probe, value)

    def test_home_result_requires_cleanup_and_binding(self):
        result = {'status': 'PASS_PREPARE', 'mode': 'prepare', 'account': common.ACCOUNT, 'uid': common.UID,
                  'bundle_sha256': 'abc', 'container_cleanup': 'REMOVED', 'production_apply': False, 'engine_transition': False}
        self.assertTrue(launch.overall_ok('prepare', 0, result, 'abc'))
        self.assertFalse(launch.overall_ok('prepare', 1, result, 'abc'))
        self.assertFalse(launch.overall_ok('prepare', 0, result, 'wrong'))
        result['container_cleanup'] = 'FAILED'
        self.assertFalse(launch.overall_ok('prepare', 0, result, 'abc'))

    def test_prepared_binding_rejects_wrong_bundle_or_image(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); p = home / ('ansible-actions-'+'a'*32) / 'evidence/PREPARED.json'
            p.parent.mkdir(parents=True)
            value = {'status': 'PASS_PREPARE', 'bundle_sha256': 'abc', 'repository': common.REPO,
                     'runner_version': common.VERSION, 'container_cleanup': 'REMOVED', 'image_id': IMAGE}
            with patch.object(runner, 'VERIFY_HOME', home), patch.object(runner, 'UID', os.getuid()):
                common.write(p, value); p.chmod(0o600)
                self.assertEqual(runner.prepared_image(p, 'abc'), IMAGE)
                self.assertRaises(RuntimeError, runner.prepared_image, p, 'wrong')
                value['image_id'] = '--privileged'; common.write(p, value)
                self.assertRaises(RuntimeError, runner.prepared_image, p, 'abc')


class CleanupTests(unittest.TestCase):
    def controller(self, root):
        for name in ('private', 'evidence', 'session', 'proxy'):
            (root / name).mkdir()
        for kind, identifier in (('runner', 'a'*64), ('proxy', 'b'*64)):
            (root / (kind + '.cid')).write_text(identifier)
        return runner.Controller(root, 'prepare', 'abc')

    def test_exact_cids_only_removed_then_workspace_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); controller = self.controller(root)
            calls = []
            def command(stage, args, *rest):
                calls.append(args)
                return 1 if 'exists' in args else 0
            controller.command = command
            self.assertTrue(controller.cleanup())
            self.assertEqual([a[-1] for a in calls], ['a'*64, 'a'*64, 'b'*64, 'b'*64])
            self.assertFalse((root / 'session').exists())
            self.assertTrue((root / 'evidence/CLEANUP.json').is_file())

    def test_cleanup_failure_preserves_workspace_and_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); controller = self.controller(root)
            controller.command = lambda *a: 0  # exists=0 means still present.
            self.assertFalse(controller.cleanup())
            self.assertTrue((root / 'session').is_dir())

    def test_started_without_cid_is_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); controller = self.controller(root)
            (root / 'runner.cid').unlink()
            controller.commands.append({'stage': 'container'})
            controller.command = lambda stage, *a: 1 if stage.endswith('-absent') else 0
            self.assertFalse(controller.cleanup())
            self.assertTrue((root / 'session').is_dir())

    def test_secret_not_in_command_records(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); controller = self.controller(root)
            secret = b'DUMMY_SECRET_NEVER_EXPORT\n'
            rc = controller.command('container', [sys.executable, '-I', '-B', '-c',
                'import sys; assert len(sys.stdin.buffer.read()) > 0; print("safe")'], payload=secret)
            self.assertEqual(rc, 0)
            self.assertNotIn(secret.decode().strip(), json.dumps(controller.commands))
            self.assertNotIn(secret, (root / 'private/container.log').read_bytes())

    def test_missing_container_result_does_not_become_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'private').mkdir(); (root / 'evidence').mkdir()
            controller = runner.Controller(root, 'prepare', 'abc')
            def command(label, *args):
                if label == 'proxy-start':
                    path = root / 'proxy/connect.sock'; path.write_text('mock socket'); path.chmod(0o600)
                return 0
            controller.command = command
            controller.output = lambda *args: json.dumps([{'Image': IMAGE, 'State': {'Status': 'exited', 'ExitCode': 0, 'OOMKilled': False}}])
            controller.cid = lambda kind: 'a'*64
            with patch.object(runner, 'UID', os.getuid()), patch.object(runner.stat, 'S_ISSOCK', return_value=True):
                self.assertRaises(FileNotFoundError, controller.execute, IMAGE, None)
            self.assertFalse((root / 'evidence/PREPARED.json').exists())

    def test_home_collector_rejects_symlink_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); run = root / 'run'; run.mkdir()
            external = root / 'outside'; external.write_bytes(b'not evidence')
            (run / common.ARCHIVE).symlink_to(external)
            with patch.object(launch, 'UID', os.getuid()):
                self.assertRaises(OSError, launch.copy_original, run, root / 'collected')

    def test_home_collector_accepts_fixed_bounded_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); run = root / 'run'; run.mkdir()
            original = root / 'HOST_RUN_RESULT.json'; common.write(original, {'status': 'FAIL'})
            archive = run / common.ARCHIVE
            with tarfile.open(archive, 'w:gz') as handle:
                handle.add(original, arcname='evidence/HOST_RUN_RESULT.json')
            (run / (common.ARCHIVE+'.sha256')).write_text(common.digest(archive)+'  '+common.ARCHIVE+'\n')
            with patch.object(launch, 'UID', os.getuid()):
                self.assertEqual(launch.copy_original(run, root / 'collected'), {'status': 'FAIL'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
