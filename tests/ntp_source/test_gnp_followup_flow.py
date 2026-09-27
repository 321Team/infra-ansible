#!/usr/bin/env python3
"""Plan A follow-up playbook flow: receipts per gate/phase and end-of-run drift STOP.

Runs the real playbook and gate task bytes against six local fake hosts. Only
fds_ntp_gnp_followup and fds_ntp_probe are replaced by a stub that returns
PASS receipts with scenario-controlled digests. No SSH, kubectl, iptables,
chronyd, UDP or production host is used (LOCAL/MOCK flow only).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = 'playbooks/cr-p1-ntp-01-01-followup-gnp.yml'
GATE_TASKS = 'roles/ntp_source/tasks/_followup_gate.yml'
HOSTS = ['k8s-control01', 'k8s-control02', 'k8s-control03', 'k8s-worker01', 'k8s-worker02', 'k8s-worker03']
UPSTREAMS = ['162.159.200.1', '162.159.200.123']  # Fixture inputs, never contacted.

STUB = '''#!/usr/bin/python
import json
from ansible.module_utils.basic import AnsibleModule

SCENARIO = %r
KEYS = ["gate", "phase", "run_id", "source_head", "inventory_hostname", "ansible_host",
        "source_upstreams", "kubeconfig", "offset_limit_ms", "input_sha256"]


def main():
    module = AnsibleModule(argument_spec={k: {"type": "raw"} for k in KEYS})
    p = module.params
    with open(SCENARIO) as handle:
        drift = json.load(handle)
    gate, phase, host = p["gate"], p.get("phase") or "packets", p["inventory_hostname"]
    if gate in ("authz", "contract", "kernel", "negative", "sample") and not p.get("kubeconfig"):
        module.fail_json(changed=False, msg="missing required arguments: kubeconfig")
    changed = drift.get(gate) == host and phase == "end"
    result = {}
    if gate == "contract":
        result = {"calico_digest": "changed" if changed else "calico-same"}
    elif gate == "kernel":
        result = {"structure_sha256": "changed" if changed else "structure-" + host}
    module.exit_json(changed=False, receipt={
        "gate": gate, "phase": phase, "inventory_hostname": host, "result": result,
        "stops": [], "errors": [], "gate_pass": True})


main()
'''

SCENARIOS = {
    'pass_no_packets': dict(packets=False, drift={}, rc=0),
    'pass_with_packets': dict(packets=True, drift={}, rc=0),
    'contract_drift_stops': dict(packets=False, drift={'contract': 'k8s-control01'}, rc=2,
                                 message='HEP/GNP/FelixConfiguration changed during the run'),
    'kernel_drift_stops': dict(packets=False, drift={'kernel': 'k8s-worker02'}, rc=2,
                               message='Felix HostEndpoint chain structure changed during the run'),
}


def expected_receipts(packets, drift):
    names = {'start-authz--k8s-control01.json', 'start-contract--k8s-control01.json'} | {'start-kernel--%s.json' % h for h in HOSTS}
    if packets:
        for h in HOSTS:
            names |= {'packets-positive--%s.json' % h, 'packets-negative--%s.json' % h,
                      'packets-sample--%s.json' % h}
    names.add('end-contract--k8s-control01.json')
    if 'contract' not in drift:
        names |= {'end-kernel--%s.json' % h for h in HOSTS}
    return names


def git(workspace, *argv):
    return subprocess.run(['git', '-C', str(workspace), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


def scenario(output, name, spec, ansible_playbook):
    base = output / name
    workspace, evidence = base / 'workspace', base / 'evidence'
    for rel in (PLAYBOOK, GATE_TASKS):
        (workspace / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, workspace / rel)
    scenario_path = base / 'scenario.json'
    scenario_path.write_text(json.dumps(spec['drift']))
    library = workspace / 'library'
    library.mkdir()
    for module in ('fds_ntp_gnp_followup.py', 'fds_ntp_probe.py'):
        (library / module).write_text(STUB % str(scenario_path))
    (workspace / 'ansible.cfg').write_text('[defaults]\nretry_files_enabled=False\nlibrary=./library\n')
    git(workspace, 'init', '-q')
    git(workspace, 'add', '-A')
    git(workspace, '-c', 'user.name=fixture', '-c', 'user.email=fixture@invalid', 'commit', '-qm', 'fixture')
    head = git(workspace, 'rev-parse', 'HEAD')
    evidence.mkdir()
    host = dict(ansible_connection='local', ansible_become=False, ansible_python_interpreter=sys.executable)
    inventory = {'all': {'hosts': {'localhost': dict(host)},
                         'children': {'k8s_nodes': {'hosts': {
                             h: dict(host, ansible_host='192.0.2.%d' % (i + 1)) for i, h in enumerate(HOSTS)}}}}}
    inventory_path = base / 'inventory.yml'
    inventory_path.write_text(yaml.safe_dump(inventory, sort_keys=False))
    extra = dict(cr_ntp_followup_run_id='flow-' + name.replace('_', '-'), cr_ntp_followup_source_head=head,
                 cr_ntp_followup_evidence_dir=str(evidence), cr_ntp_followup_packets=spec['packets'],
                 cr_ntp_followup_kubeconfig='/tmp/fds-ntp-followup-readonly.conf',
                 cr_ntp_source_upstreams=UPSTREAMS, cr_ntp_offset_max_ms=100,
                 cr_ntp_followup_samples=2, cr_ntp_followup_interval=0)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ANSIBLE_', 'PYTHON'))}
    env.update(ANSIBLE_CONFIG=str(workspace / 'ansible.cfg'), ANSIBLE_NOCOLOR='1',
               LANG='C.UTF-8', LC_ALL='C.UTF-8')
    process = subprocess.run([ansible_playbook, '-i', str(inventory_path), '-e', json.dumps(extra),
                              str(workspace / PLAYBOOK)], env=env, cwd=workspace, capture_output=True,
                             text=True, timeout=300)
    (base / 'stdout.log').write_text(process.stdout)
    (base / 'stderr.log').write_text(process.stderr)
    assert process.returncode == spec['rc'], (name, process.returncode, process.stdout[-3000:])
    assert 'has no attribute' not in process.stdout, name
    if 'message' in spec:
        assert spec['message'] in process.stdout, name
    receipts = {p.name for p in (evidence / extra['cr_ntp_followup_run_id']).iterdir()}
    expected = expected_receipts(spec['packets'], spec['drift'])
    assert receipts == expected, (name, sorted(receipts ^ expected))
    return dict(rc=process.returncode, receipts=len(receipts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ansible-playbook', required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = dict(name='gnp_followup_flow', passed=False,
                  scope='LOCAL Ansible flow; gate modules stubbed; no host/network acceptance',
                  playbook_sha256=hashlib.sha256((ROOT / PLAYBOOK).read_bytes()).hexdigest(),
                  gate_tasks_sha256=hashlib.sha256((ROOT / GATE_TASKS).read_bytes()).hexdigest(),
                  scenarios={})
    try:
        for name, spec in SCENARIOS.items():
            result['scenarios'][name] = scenario(output, name, spec, args.ansible_playbook)
        result['passed'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    (output / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
