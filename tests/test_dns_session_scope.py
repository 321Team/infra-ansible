"""Production session plays, local-only facts and a stub role; no DNS writes."""
import json
from pathlib import Path
import shutil
import subprocess
import test_dns_worker02_scope as scope


class SessionScope(scope.Worker02Scope):
    def setUp(self):
        super().setUp()
        shutil.copyfile(scope.ROOT / 'playbooks/cr-p1-ans-01-01-worker02-session.yml', self.playbook)
        self.role.write_text('---\n- ansible.builtin.debug:\n    msg: SCOPE_FIXTURE_REACHED\n')
        shutil.copyfile(self.role, self.role.with_name('session-rollback.yml'))
        self.args = {'cr_dns_change_id': 'CR-P1-ANS-01-01',
                     'cr_dns_change_approved': 'CR-P1-ANS-01-01',
                     'cr_dns_session_action': 'apply',
                     'cr_dns_session_id': 'w02-20261009T150000-1234abcd',
                     'cr_dns_session_source': 'a' * 40,
                     'cr_dns_session_sha256': 'b' * 64,
                     'cr_dns_session_approved': 'w02-20261009T150000-1234abcd:apply'}

    def invoke(self, inventory=None):
        inv = self.root / 'inventory.json'
        inv.write_text(json.dumps(self.inventory if inventory is None else inventory))
        extra = self.root / 'extra.json'
        extra.write_text(json.dumps(self.args))
        return subprocess.run([str(self.cli), '-i', str(inv), '-e', '@' + str(extra), str(self.playbook)],
                              cwd=self.root, env=self.env, text=True, capture_output=True, timeout=90)

    def test_all_four_actions_are_single_host(self):
        for action in ('prepare', 'apply', 'reapply', 'rollback'):
            self.args['cr_dns_session_action'] = action
            self.args['cr_dns_session_approved'] = self.args['cr_dns_session_id'] + ':' + action
            self.test_exact_worker02_only_with_other_workers_present()

    def test_bad_or_missing_inputs_stop_before_facts(self):
        valid = dict(self.args)
        for key in valid:
            self.args = dict(valid)
            del self.args[key]
            with self.subTest(missing=key):
                self.assert_blocked(self.inventory)
        for key, value in (('cr_dns_session_action', 'workers'), ('cr_dns_session_id', '../escape'),
                           ('cr_dns_session_source', 'abc'), ('cr_dns_session_sha256', 'bad'),
                           ('cr_dns_session_approved', valid['cr_dns_session_id'] + ':rollback')):
            self.args = dict(valid, **{key: value})
            with self.subTest(key=key):
                self.assert_blocked(self.inventory)
