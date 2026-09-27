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


def load(name):
    return yaml.safe_load(PLAYBOOKS[name].read_text())[0]


def test_all_remote_playbooks_are_serial_and_fatal():
    for name in PLAYBOOKS:
        play = load(name)
        assert play["hosts"] == "k8s_nodes"
        assert play["serial"] == 1
        assert play["any_errors_fatal"] is True


def test_precheck_validates_effective_config_path_without_dumping_argv():
    text = PLAYBOOKS["precheck"].read_text()
    assert "CONFIG_PATH_OK=" in text
    assert "TLS_OVERRIDE_COUNT=" in text
    assert "--config=/var/lib/kubelet/config.yaml" in text


def test_apply_is_config_only_and_requires_explicit_target():
    text = PLAYBOOKS["apply"].read_text()
    assert "p1_kubelet_tls_target" in text
    assert "p1_kubelet_tls_apply_approved" in text
    assert "serverTLSBootstrap: true" in text
    assert "lineinfile" in text
    assert "state: restarted" not in text
    assert "certificate approve" not in text


def test_restart_requires_reviewer_ready_and_has_no_auto_approval():
    text = PLAYBOOKS["restart"].read_text()
    assert "p1_kubelet_tls_csr_reviewer_ready" in text
    assert "p1_kubelet_tls_attempt_id" in text
    assert "config.yaml.before" in text
    assert "state: restarted" in text
    assert "certificate approve" not in text
    assert "kubectl" not in text


def test_verify_checks_chain_ip_and_hostname():
    text = PLAYBOOKS["verify"].read_text()
    assert "openssl" in text
    assert "-checkip" in text
    assert "-checkhost" in text
    assert "-CAfile" in text


def test_rollback_is_hash_guarded_and_does_not_delete_pki():
    text = PLAYBOOKS["rollback"].read_text()
    assert "p1_kubelet_tls_current_sha256" in text
    assert "--preserve=all" in text
    assert "state: restarted" in text
    assert "rm " not in text
    assert "state: absent" not in text
