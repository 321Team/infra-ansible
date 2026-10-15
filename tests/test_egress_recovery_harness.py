"""Exercise the real recap/helper shell path with a fake inventory CLI only."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('egress_fixture', ROOT / 'tests/run-egress-recovery.py')
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)
BASH = shutil.which('bash')
if not BASH and os.name == 'nt':
    candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe'
    BASH = str(candidate) if candidate.is_file() else None


@unittest.skipUnless(BASH, 'Bash is required; no Ansible or server access is used')
class EgressHarness(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='egress harness ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binary = self.root / 'engine with spaces'
        self.binary.mkdir()
        self.trace = self.root / 'inventory.trace'
        inventory = self.binary / 'ansible-inventory'
        inventory.write_text('#!/bin/bash\nset -eu\nprintf "%s\\n" "$@" > "$TRACE"\n'
                             'if [[ "${INVENTORY_FAIL:-0}" != 0 ]]; then exit 77; fi\n'
                             'printf "@egress_proxy:\\n  |--egress-proxy01\\n"\n', encoding='utf-8')
        inventory.chmod(0o700)
        source = (ROOT / 'scripts/cr-p1-mon-01-01-run.sh').read_text(encoding='utf-8')
        self.function = source[source.index('assert_idempotent() {'):source.index('\nrequire_change_approval()')]
        self.good = 'egress-proxy01 : ok=40 changed=0 unreachable=0 failed=0 skipped=3 rescued=0 ignored=0\n'

    def posix(self, path):
        if os.name != 'nt':
            return str(path)
        return subprocess.check_output([BASH, '-c', 'cygpath -u "$1"', 'fixture', str(path)], text=True).strip()

    def invoke(self, recap, broken=False, **extra):
        path = self.root / 'recap with spaces.txt'
        path.write_text(recap, encoding='utf-8')
        with patch.dict(os.environ, FDS_ANSIBLE_ENGINE_DIR='/must-not-use-operating-engine',
                        FDS_ANSIBLE_ENGINE_VERSION='9.0.0'):
            env = FIXTURE.fixture_environment(self.binary, self.root)
        self.assertNotIn('FDS_ANSIBLE_ENGINE_DIR', env)
        self.assertNotIn('FDS_ANSIBLE_ENGINE_VERSION', env)
        # Git Bash needs POSIX PATH; the production fixture runs on Linux.
        env.update(PATH=self.posix(self.binary)+':/usr/bin:/bin', TRACE=self.posix(self.trace), **extra)
        if broken:
            command = ['bash', '-c', 'set -Eeuo pipefail\nrepo_root="$1"\n'+self.function+
                       '\nassert_idempotent "$2"', 'fixture', self.posix(ROOT), self.posix(path)]
        else:
            command = FIXTURE.recap_command(self.posix(ROOT), self.posix(path), self.function)
        command[0] = BASH
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)

    def test_previous_extraction_fails_positive_before_inventory(self):
        result = self.invoke(self.good, broken=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fds_engine_exec', result.stderr)
        self.assertFalse(self.trace.exists())

    def test_positive_uses_selected_inventory_and_ignores_inherited_opt_in(self):
        result = self.invoke(self.good+'localhost : ok=1 changed=0 unreachable=0 failed=0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace.read_text().splitlines(),
                         ['-i', self.posix(ROOT)+'/inventory/hosts.yml', '--graph', 'egress_proxy'])

    def test_changed_is_rejected(self):
        self.assertEqual(self.invoke(self.good.replace('changed=0', 'changed=1')).returncode, 1)

    def test_localhost_only_is_rejected(self):
        self.assertEqual(self.invoke('localhost : ok=1 changed=0 unreachable=0 failed=0\n').returncode, 1)

    def test_wrong_target_is_rejected(self):
        self.assertEqual(self.invoke(self.good.replace('egress-proxy01', 'k8s-worker01')).returncode, 1)

    def test_extra_target_is_rejected(self):
        self.assertEqual(self.invoke(self.good+self.good.replace('egress-proxy01', 'k8s-worker01')).returncode, 1)

    def test_inventory_failure_is_not_success(self):
        # The empty graph also makes grep fail; pipefail returns that last
        # nonzero status, not necessarily the inventory subprocess's 77.
        self.assertEqual(self.invoke(self.good, INVENTORY_FAIL='1').returncode, 1)
        self.assertTrue(self.trace.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
