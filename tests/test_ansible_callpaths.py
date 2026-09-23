"""Local unit/mock checks; not evidence of an ansible01 execution."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'tools/collect-ansible-callpaths.py'
spec = importlib.util.spec_from_file_location('callpaths', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CollectorTests(unittest.TestCase):
    def test_no_raw_secrets_or_arguments(self):
        data = b'PASSWORD=VerySecret123\nTOKEN=abc ansible-playbook /tmp/deploy.yml --vault-password-file /tmp/password\n# ansible\n'
        result = module.scan_text(data)
        encoded = json.dumps(result)
        self.assertNotIn('VerySecret123', encoded)
        self.assertNotIn('vault-password', encoded)
        self.assertEqual(result['reference_lines'], [{'line': 2, 'references': ['ansible-playbook']}])

    def test_repo_locations_omit_credentials(self):
        data = b'[baseos]\nenabled=1\nbaseurl=https://user:secret@example.com/path?token=abc\n'
        result = module.repo_sections(data)
        self.assertEqual(result, [{'id': 'baseos', 'enabled_literal': '1', 'location_fields_present': ['baseurl']}])

    def test_metadata_inspection_never_executes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'executed'
            wrapper = root / 'deploy.sh'
            wrapper.write_text('#!/bin/sh\ntouch ' + str(marker) + '\nansible-playbook site.yml\n')
            wrapper.chmod(0o700)
            inv = module.Inventory()
            self.assertIsNotNone(inv.read(wrapper, 'test'))
            self.assertFalse(marker.exists())
            self.assertEqual(inv.files[0]['status'], 'READ')

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'original'
            source.write_text('sensitive')
            link = root / 'link'
            link.symlink_to(source)
            inv = module.Inventory()
            self.assertIsNone(inv.read(link, 'test'))
            self.assertEqual(inv.files[0]['status'], 'SYMLINK_PATH_NOT_READ')

    def test_fifo_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fifo'
            os.mkfifo(path)
            inv = module.Inventory()
            self.assertIsNone(inv.read(path, 'test'))
            self.assertEqual(inv.files[0]['status'], 'NOT_REGULAR')

    def test_oversize_is_coverage_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'large'
            path.write_bytes(b'x' * (module.MAX_FILE + 1))
            inv = module.Inventory()
            self.assertIsNone(inv.read(path, 'test'))
            self.assertEqual(inv.gaps[0]['reason'], 'BYTE_LIMIT')

    def test_permission_denied_not_absence(self):
        with patch.object(module.os, 'open', side_effect=PermissionError):
            inv = module.Inventory()
            self.assertIsNone(inv.read('/unlikely/fixture', 'test'))
            self.assertEqual(inv.gaps[0]['reason'], 'PermissionError')

    def test_root_guard(self):
        with patch.object(module.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(ValueError, 'non-root'):
                module.validate(SimpleNamespace())

    def test_host_guard(self):
        with patch.object(module.os, 'geteuid', return_value=1001), patch.object(module.socket, 'gethostname', return_value='other-host'):
            with self.assertRaisesRegex(ValueError, 'host mismatch'):
                module.validate(SimpleNamespace(expected_host='ansible01'))

    def test_query_environment_and_no_shell(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(module.subprocess, 'run') as run:
            run.return_value = SimpleNamespace(returncode=1, stdout=b'', stderr=b'secret')
            row, data = module.query(['/usr/bin/crontab', '-l'], Path(tmp))
            kwargs = run.call_args.kwargs
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['env']['HOME'], tmp)
            self.assertNotIn('BASH_ENV', kwargs['env'])
            self.assertNotIn('secret', json.dumps(row))
            self.assertEqual(row['rc'], 1)

    def test_full_collection_mock_missing_crontab_and_unchanged_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / 'repo'
            repo.mkdir()
            cfg = repo / 'ansible.cfg'
            cfg.write_text('[defaults]\ninventory=./inventory/hosts.yml\n')
            before = cfg.read_bytes()
            def query(argv, cwd):
                data = (b'a' * 40 + b'\n') if argv[0].endswith('/git') else b''
                return {'argv': argv, 'rc': 0 if data else 1, 'status': 'RETURNED'}, data
            original = module.Inventory.read
            def read(inv, path, category):
                return original(inv, path, category) if repo in Path(path).parents else None
            with patch.object(module, 'validate', return_value=(repo, root)), \
                 patch.object(module, 'query', side_effect=query), \
                 patch.object(module.Inventory, 'read', read), \
                 patch.object(module.Inventory, 'directory', return_value=[]), \
                 patch.dict(os.environ, {'PATH': ''}), \
                 patch.object(module.sys, 'argv', ['collector', '--repo', str(repo), '--output-parent', str(root), '--expected-host', 'fixture', '--expected-user', 'fixture']):
                self.assertEqual(module.main(), 0)
                self.assertEqual(module.main(), 0)
            reports = sorted(root.glob('ansible-callpaths-*/REPORT.json'))
            self.assertEqual(len(reports), 2)
            report = json.loads(reports[0].read_text())
            self.assertEqual(report['current_user_crontab']['status'], 'UNCONFIRMED')
            self.assertEqual(report['status'], 'COLLECTED_REVIEW_REQUIRED')
            self.assertEqual(report['runtime'], 'NOT_RUN')
            self.assertEqual(before, cfg.read_bytes())
            self.assertEqual(reports[0].stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
