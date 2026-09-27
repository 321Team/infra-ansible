import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOKS = {
    "precheck": ROOT / "playbooks/p1-k8s-01-kubelet-serving-tls-precheck.yml",
    "apply": ROOT / "playbooks/p1-k8s-01-kubelet-serving-tls-apply-one.yml",
    "restart": ROOT / "playbooks/p1-k8s-01-kubelet-serving-tls-restart-one.yml",
    "verify": ROOT / "playbooks/p1-k8s-01-kubelet-serving-tls-verify.yml",
    "rollback": ROOT / "playbooks/p1-k8s-01-kubelet-serving-tls-rollback-one.yml",
}
CLI_TASKS = ROOT / "playbooks/tasks/p1-k8s-01-kubelet-serving-tls-cli-contract.yml"
AUTH_TASKS = ROOT / "playbooks/tasks/p1-k8s-01-kubelet-serving-tls-auth-contract.yml"


def load_play(name):
    return yaml.safe_load(PLAYBOOKS[name].read_text(encoding="utf-8"))[0]


def all_tasks(play):
    return [*play.get("pre_tasks", []), *play.get("tasks", [])]


def task_named(play, name):
    for task in all_tasks(play):
        if task.get("name") == name:
            return task
    raise AssertionError(f"missing task: {name}")


class KubeletServingTLSContractTests(unittest.TestCase):
    def test_all_remote_playbooks_are_serial_and_fail_closed(self):
        for name in PLAYBOOKS:
            play = load_play(name)
            self.assertEqual(play["hosts"], "k8s_nodes")
            self.assertEqual(play["serial"], 1)
            self.assertIs(play["any_errors_fatal"], True)

    def test_cli_contract_handles_missing_kubelet_without_traceback(self):
        tasks = yaml.safe_load(CLI_TASKS.read_text(encoding="utf-8"))
        locate = next(t for t in tasks if t["name"] == "Locate the running kubelet process")
        require = next(t for t in tasks if t["name"] == "Require a running kubelet process")
        self.assertIs(locate["failed_when"], False)
        conditions = require["ansible.builtin.assert"]["that"]
        self.assertIn("p1_kubelet_tls_pid.rc == 0", conditions)
        self.assertIn(
            "p1_kubelet_tls_pid.stdout | trim is match('^[0-9]+$')",
            conditions,
        )

    def test_precheck_apply_restart_and_verify_revalidate_cli_contract(self):
        expected = {
            "precheck": "Validate effective kubelet CLI contract",
            "apply": "Revalidate effective kubelet CLI contract immediately before apply",
            "restart": "Revalidate effective kubelet CLI contract immediately before restart",
            "verify": "Revalidate effective kubelet CLI contract during verification",
        }
        for play_name, task_name in expected.items():
            task = task_named(load_play(play_name), task_name)
            self.assertEqual(
                task["ansible.builtin.include_tasks"],
                "tasks/p1-k8s-01-kubelet-serving-tls-cli-contract.yml",
            )

    def test_authn_authz_contract_is_explicit_and_reused(self):
        tasks = yaml.safe_load(AUTH_TASKS.read_text(encoding="utf-8"))
        guard = next(
            t
            for t in tasks
            if t["name"] == "Require approved kubelet authentication and authorization controls"
        )
        conditions = guard["ansible.builtin.assert"]["that"]
        joined = "\n".join(conditions)
        self.assertIn("anonymous", joined)
        self.assertIn("webhook", joined)
        self.assertIn("clientCAFile", joined)
        self.assertIn("authorization", joined)
        self.assertIn("'Webhook'", joined)

        for play_name in ("precheck", "apply", "restart", "verify"):
            text = PLAYBOOKS[play_name].read_text(encoding="utf-8")
            self.assertIn(
                "tasks/p1-k8s-01-kubelet-serving-tls-auth-contract.yml",
                text,
            )

    def test_mutation_gates_use_external_approval_refs_not_magic_tokens(self):
        cases = {
            "apply": ("p1_kubelet_tls_apply_approval_ref", "p1_kubelet_tls_apply_confirmed"),
            "restart": (
                "p1_kubelet_tls_restart_approval_ref",
                "p1_kubelet_tls_restart_confirmed",
            ),
            "rollback": (
                "p1_kubelet_tls_rollback_approval_ref",
                "p1_kubelet_tls_rollback_confirmed",
            ),
        }
        for name, required in cases.items():
            text = PLAYBOOKS[name].read_text(encoding="utf-8")
            for item in required:
                self.assertIn(item, text)
            self.assertNotIn("_approved", text)
            self.assertNotIn("approval token", text.lower())

    def test_apply_remains_config_only(self):
        text = PLAYBOOKS["apply"].read_text(encoding="utf-8")
        self.assertIn("serverTLSBootstrap: true", text)
        self.assertIn("ansible.builtin.lineinfile", text)
        self.assertIn("after.sha256", text)
        self.assertNotIn("state: restarted", text)
        self.assertNotIn("certificate approve", text)

    def test_restart_binds_staged_sha_and_observes_new_pending_csr(self):
        play = load_play("restart")
        guard = task_named(play, "Stop if config changed after staging")
        conditions = guard["ansible.builtin.assert"]["that"]
        self.assertTrue(
            any("p1_kubelet_tls_after_sha_file.content" in item for item in conditions)
        )
        text = PLAYBOOKS["restart"].read_text(encoding="utf-8")
        self.assertIn("Capture pre-restart CSR inventory from control01", text)
        self.assertIn("exactly one new pending serving csr", text.lower())
        self.assertIn("kubernetes.io/kubelet-serving", text)
        self.assertIn("system:node:{node}", text)
        self.assertIn("p1_kubelet_tls_csr_reviewer", text)
        self.assertNotIn("certificate approve", text)

    def test_rollback_requires_observed_and_staged_sha_plus_restart_confirmation(self):
        play = load_play("rollback")
        guard = task_named(play, "Guard against TOCTOU and unrelated changes since staging")
        conditions = guard["ansible.builtin.assert"]["that"]
        joined = "\n".join(conditions)
        self.assertIn("p1_kubelet_tls_current_sha256", joined)
        self.assertIn("p1_kubelet_tls_after_sha_file.content", joined)
        text = PLAYBOOKS["rollback"].read_text(encoding="utf-8")
        self.assertIn("p1_kubelet_tls_rollback_restart_confirmed", text)
        self.assertIn("--preserve=all", text)
        self.assertNotIn("state: absent", text)
        self.assertNotIn("rm ", text)

    def test_verify_checks_cli_authn_authz_chain_ip_and_hostname(self):
        text = PLAYBOOKS["verify"].read_text(encoding="utf-8")
        self.assertIn("effective kubelet CLI contract", text)
        self.assertIn("authentication and authorization controls", text)
        self.assertIn("-CAfile", text)
        self.assertIn("-checkip", text)
        self.assertIn("-checkhost", text)


if __name__ == "__main__":
    unittest.main()
