"""Archive boundary, commit identity and dependency-lock regression tests."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verification_kit', ROOT / 'tools/verification-kit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


class KitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='verification-kit-tests-')
        cls.base = Path(cls.temp.name)
        cls.repo = cls.base / 'repository'
        cls.repo.mkdir()
        cls.wheels = cls.base / 'wheels'
        cls.wheels.mkdir()
        lock = kit.decode((ROOT / kit.LOCK).read_bytes())
        for w in lock['wheels']:
            raw = ('synthetic wheel fixture: ' + w['filename']).encode()
            w.update(size=len(raw), sha256=kit.sha(raw))
            (cls.wheels / w['filename']).write_bytes(raw)
        inputs = {kit.TOOL: (ROOT / kit.TOOL).read_bytes(), kit.LOCK: kit.encoded(lock),
                  kit.GUIDE: b'Fixture guide. Not an operational package.\n',
                  '.gitattributes': b'* -text\n', 'sample.sh': b'#!/bin/sh\nexit 0\n'}
        for engine in lock['engines']:
            path = 'tests/requirements-verification-' + engine + '.txt'
            inputs[path] = (ROOT / path).read_bytes()
        for name, raw in inputs.items():
            p = cls.repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        (cls.repo / 'sample.sh').chmod(0o755)
        (cls.repo / '.env').write_bytes(b'fixture-only-not-a-real-secret\n')
        kit.git(cls.repo, 'init', '--template=')
        kit.git(cls.repo, 'add', '.')
        kit.git(cls.repo, 'update-index', '--chmod=+x', 'sample.sh')
        # Make a parent containing a credential-like file; it must not enter the source-only pack.
        kit.git(cls.repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'Fixture parent')
        cls.parent = kit.git(cls.repo, 'rev-parse', 'HEAD').decode().strip()
        (cls.repo / '.env').unlink()
        kit.git(cls.repo, 'add', '-u')
        (cls.repo / 'second.txt').write_bytes(b'latest snapshot\n')
        kit.git(cls.repo, 'add', 'second.txt')
        kit.git(cls.repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'Fixture snapshot')
        cls.commit = kit.git(cls.repo, 'rev-parse', 'HEAD').decode().strip()
        cls.result = kit.build(cls.repo, cls.commit, cls.wheels, cls.base / 'build')
        cls.archive = Path(cls.result['archive'])
        cls.files = kit.verify_archive(cls.archive, cls.result['sha256'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def write_variant(self, files, name):
        path = self.base / (name + '.tar.gz')
        raw = kit.make_archive(files)
        path.write_bytes(raw)
        return path, kit.sha(raw)

    def test_roundtrip_preserves_commit_blob_and_executable_mode(self):
        extracted = kit.extract_files(self.files, self.base / 'roundtrip')
        repo = kit.materialize(extracted, self.base / 'restored')
        self.assertEqual(kit.git(repo, 'rev-parse', 'HEAD').decode().strip(), self.commit)
        kit.clean_source(repo, self.commit)
        self.assertEqual(kit.git(repo, 'ls-tree', 'HEAD', 'sample.sh').split()[0], b'100755')
        self.assertFalse((repo / '.git/config').read_text().find('[remote ') >= 0)
        with self.assertRaises(subprocess.CalledProcessError):
            kit.git(repo, 'cat-file', '-e', self.parent)

    def test_build_is_reproducible_in_same_toolchain(self):
        second = kit.build(self.repo, self.commit, self.wheels, self.base / 'second-build')
        self.assertEqual(self.result['sha256'], second['sha256'])

    def test_outer_digest_rejects_corruption(self):
        with self.assertRaisesRegex(ValueError, 'Outer'):
            kit.verify_archive(self.archive, '0' * 64)

    def test_inner_digest_rejects_repacked_corruption(self):
        changed = dict(self.files)
        changed['source/second.txt'] = (b'changed\n', 0o644)
        archive, digest = self.write_variant(changed, 'changed-text')
        with self.assertRaisesRegex(ValueError, 'Inner'):
            kit.verify_archive(archive, digest)

    def test_missing_file_is_rejected(self):
        changed = dict(self.files)
        del changed['SOURCE.pack']
        archive, digest = self.write_variant(changed, 'missing-pack')
        with self.assertRaisesRegex(ValueError, 'missing'):
            kit.verify_archive(archive, digest)

    def test_duplicate_manifest_entry_is_rejected(self):
        changed = dict(self.files)
        raw = changed['SHA256SUMS'][0]
        changed['SHA256SUMS'] = (raw + raw.splitlines(keepends=True)[0], 0o644)
        archive, digest = self.write_variant(changed, 'duplicate-manifest')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            kit.verify_archive(archive, digest)

    def test_traversal_link_and_duplicate_tar_are_rejected(self):
        for label in ('traversal', 'link', 'duplicate', 'case-collision'):
            with self.subTest(label=label):
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode='w:gz') as tar:
                    item = tarfile.TarInfo('../escape' if label == 'traversal' else 'safe')
                    item.mode = 0o644
                    if label == 'link':
                        item.type, item.linkname = tarfile.SYMTYPE, '/outside'
                    tar.addfile(item)
                    if label in ('duplicate', 'case-collision'):
                        item.name = 'SAFE' if label == 'case-collision' else 'safe'
                        tar.addfile(item)
                raw = buf.getvalue()
                path = self.base / (label + '.tar.gz')
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    kit.verify_archive(path, kit.sha(raw))

    def test_existing_result_directory_preserved(self):
        out = self.base / 'existing-output'
        out.mkdir()
        marker = out / 'evidence.txt'
        marker.write_bytes(b'do not overwrite')
        with self.assertRaisesRegex(ValueError, 'NEW directory'):
            kit.extract_files(self.files, out)
        self.assertEqual(marker.read_bytes(), b'do not overwrite')

    def test_dirty_checkout_and_wrong_commit_rejected(self):
        with self.assertRaisesRegex(ValueError, 'requested commit'):
            kit.clean_source(self.repo, self.parent)
        path = self.repo / 'untracked.txt'
        path.write_bytes(b'untracked')
        try:
            with self.assertRaisesRegex(ValueError, 'dirty'):
                kit.clean_source(self.repo, self.commit)
        finally:
            path.unlink()

    def test_missing_or_changed_wheel_rejected(self):
        lock = kit.lock_data(self.files['source/' + kit.LOCK][0])
        w = lock['wheels'][0]
        path = self.wheels / w['filename']
        original = path.read_bytes()
        try:
            path.write_bytes(b'bad wheel')
            with self.assertRaisesRegex(ValueError, 'Wheel hash'):
                kit.verify_wheels(lock, self.wheels)
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'Missing/extra'):
                kit.verify_wheels(lock, self.wheels)
        finally:
            path.write_bytes(original)

    def test_lock_rejects_redirects_duplicates_and_missing_wheels(self):
        lock = kit.decode(self.files['source/' + kit.LOCK][0])
        for kind in ('redirect', 'duplicate', 'missing'):
            changed = copy.deepcopy(lock)
            if kind == 'redirect':
                changed['wheels'][0]['url'] = 'https://example.invalid/artifact.whl'
            elif kind == 'duplicate':
                changed['wheels'].append(changed['wheels'][0])
            else:
                changed['wheels'].pop()
            with self.assertRaises(ValueError):
                kit.lock_data(kit.encoded(changed))

    def test_credentials_and_unsafe_names_rejected(self):
        for name in ('.ssh/id_rsa', 'known_hosts', '.env', 'secrets.pem', '__pycache__/module.pyc',
                     '../outside', '/absolute', 'CON.txt', 'x:y', 'x\\y'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                kit.source_content_allowed(kit.safe_name(name), b'fixture')
        raw = b'-----BEGIN ' + b'OPENSSH PRIVATE KEY-----'
        with self.assertRaises(ValueError):
            kit.source_content_allowed('normal.txt', raw)

    def test_parent_git_pip_and_ansible_environment_removed(self):
        with patch.dict(os.environ, {'GIT_DIR': '/outside', 'PIP_INDEX_URL': 'https://example.invalid',
                                    'PYTHONPATH': '/outside', 'ANSIBLE_INVENTORY': '/production', 'SSH_AUTH_SOCK': '/agent'}):
            env = kit.environment()
        self.assertFalse(set(('GIT_DIR', 'PIP_INDEX_URL', 'PYTHONPATH', 'ANSIBLE_INVENTORY', 'SSH_AUTH_SOCK')) & env.keys())
        self.assertEqual(env['GIT_CONFIG_GLOBAL'], os.devnull)

    def test_nonlinux_prepare_does_not_create_runtime(self):
        with patch.object(kit.sys, 'platform', 'win32'):
            with self.assertRaisesRegex(ValueError, 'requires Linux'):
                kit.prepare(self.archive, self.result['sha256'], self.base / 'wrong-platform')
        self.assertFalse((self.base / 'wrong-platform').exists())

    def test_prepare_commands_are_offline_and_within_new_runtime(self):
        commands = []
        def record(command, cwd, env, directory, timeout=1800):
            commands.append([str(x) for x in command])
        out = self.base / 'simulated-runtime'
        with patch.object(kit, 'target_host'), patch.object(kit, 'logged', side_effect=record):
            result = kit.prepare(self.archive, self.result['sha256'], out)
        installs = [cmd for cmd in commands if 'install' in cmd]
        self.assertEqual(len(installs), 4)
        for cmd in installs:
            self.assertIn('--no-index', cmd)
            self.assertIn('--require-hashes', cmd)
            self.assertIn('--only-binary=:all:', cmd)
            self.assertIn('--no-user', cmd)
            self.assertTrue(Path(cmd[cmd.index('--prefix') + 1]).is_relative_to(out))
            self.assertTrue(Path(cmd[0]).is_relative_to(out))
        self.assertEqual(result['scope'], 'fixture_local_only')
        self.assertEqual(kit.git(out / 'repo', 'rev-parse', 'HEAD').decode().strip(), self.commit)


if __name__ == '__main__':
    unittest.main()
