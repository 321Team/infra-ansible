"""Regression boundaries for the observed read-only shared-memory failure."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import container
import runner

ROW = '45 30 0:55 / /dev/shm rw,nosuid,nodev,noexec,relatime - tmpfs shm rw,size=65536k\n'


class IPCBoundaries(unittest.TestCase):
    def stats(self, readonly=False, size=64*1024**2):
        return SimpleNamespace(f_flag=os.ST_RDONLY if readonly else 0, f_frsize=4096, f_blocks=size//4096)

    def test_hardened_bounded_mount_accepts(self):
        self.assertTrue(all(container.shm_checks(ROW, self.stats()).values()))

    def test_unsafe_or_missing_mounts_reject(self):
        for row in ('', ROW+ROW, ROW.replace('tmpfs shm', 'ext4 disk'),
                    ROW.replace('rw,', 'ro,', 1), ROW.replace(',noexec', ''),
                    ROW.replace(',nosuid', ''), ROW.replace(',nodev', '')):
            with self.subTest(row=row):
                self.assertFalse(all(container.shm_checks(row, self.stats()).values()))

    def test_readonly_and_unbounded_or_different_size_reject(self):
        for stats in (self.stats(True), self.stats(size=0), self.stats(size=128*1024**2), self.stats(size=32*1024**2)):
            self.assertFalse(all(container.shm_checks(ROW, stats).values()))

    def test_all_modes_require_ipc_success_and_shm_checks(self):
        state = {'Status':'exited','ExitCode':0,'OOMKilled':False}
        checks = dict.fromkeys(runner.ISOLATION_KEYS, True)
        for mode, status in [('prepare','PASS_PREPARE_CONTAINER'), ('registration-check','PASS_REGISTRATION_CHECK'), ('serve','SESSION_ENDED')]:
            result = {'status':status,'listener_version_matches':True,'ipc_preflight_passed':True,
                      'configure_rc':0,'remove_rc':0,'listener_rc':0,'runner':{'agentId':4},'job_finished_observed':True}
            self.assertTrue(runner.container_ok(mode,result,0,state,checks,True))
            for bad in (False, None, 1, 'true'):
                self.assertFalse(runner.container_ok(mode,dict(result,ipc_preflight_passed=bad),0,state,checks,True))
            for key in ('shm-tmpfs','shm-writable','shm64m','shm-hardening'):
                self.assertFalse(runner.container_ok(mode,result,0,state,dict(checks,**{key:False}),True))

    def test_probe_rejects_failure_fake_success_and_timeout(self):
        for rc, out, expected in [(0,'PASS_IPC\n',True),(1,'PASS_IPC\n',False),(0,'',False),(0,'FAIL_IPC',False)]:
            with patch.object(container.subprocess,'run',return_value=SimpleNamespace(returncode=rc,stdout=out)) as call:
                self.assertEqual(container.ipc_preflight(), expected)
                self.assertEqual(call.call_args.kwargs['timeout'],20)
        with patch.object(container.subprocess,'run',side_effect=subprocess.TimeoutExpired(['probe'],20)):
            self.assertRaises(subprocess.TimeoutExpired,container.ipc_preflight)

    def test_runner_only_uses_private_bounded_tmpfs(self):
        for mode in runner.MODES:
            command = runner.podman_command('runner','sha256:'+'a'*64,Path('/dedicated/fresh'),'ansible-ci-'+'b'*32,mode)
            self.assertIn('--ipc=private',command)
            self.assertIn('/dev/shm:rw,nosuid,nodev,noexec,size=64m,mode=1777',command)
            self.assertIn('--read-only-tmpfs=false',command)
            self.assertNotIn('--ipc=host',command)
            side = runner.podman_command('proxy','sha256:'+'a'*64,Path('/dedicated/fresh'),'ansible-ci-'+'b'*32,mode)
            self.assertNotIn('--tmpfs',side)

    def test_ipc_gate_precedes_token_read_and_registration(self):
        source=(ROOT/'container.py').read_text()
        self.assertLess(source.index("record['ipc_preflight_passed'] = ipc_preflight()"),source.index('secret = packet('))
        self.assertIn('ipc_probe.py', (ROOT/'build/Containerfile').read_text())


if __name__=='__main__':
    unittest.main(verbosity=2)
