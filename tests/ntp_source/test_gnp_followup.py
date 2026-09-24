#!/usr/bin/env python3
"""Plan A follow-up: Calico contract, HEP kernel wiring and gate logic (LOCAL/MOCK).

The contract fixture is the received Gate 2 snapshot (see its provenance).
The kernel fixture below is SYNTHETIC in Felix's documented shape: no
post-HEP iptables-save has been captured yet.  Replace it with the new
read-only capture before treating kernel parsing as field-validated.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from policy_test_support import load_policy

ROOT = Path(__file__).resolve().parents[2]
load_policy()


def load_util(name):
    full = "ansible.module_utils." + name
    spec = importlib.util.spec_from_file_location(full, ROOT / "module_utils" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


C = load_util("fds_ntp_gnp_contract")
K = load_util("fds_ntp_hep_kernel")
spec = importlib.util.spec_from_file_location("gnp_followup", ROOT / "library/fds_ntp_gnp_followup.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

FIXTURE = json.loads((ROOT / "tests/ntp_source/fixtures/calico_gate2_20260922.json").read_text())
UPSTREAMS = ["162.159.200.1", "162.159.200.123"]  # Fixture inputs, never contacted.
FELIX = {"items": [{"kind": "FelixConfiguration", "metadata": {"name": "default"}, "spec": {}}]}
# nodeport-30080-allow as recorded in infra-kubernetes GATE2_RUNTIME_EXECUTION_20260922.md.
NODEPORT = {"apiVersion": "crd.projectcalico.org/v1", "kind": "GlobalNetworkPolicy",
            "metadata": {"name": "nodeport-30080-allow"},
            "spec": {"selector": "fds.example/role == 'worker'", "order": 50, "applyOnForward": True,
                     "preDNAT": True, "types": ["Ingress"],
                     "ingress": [{"action": "Allow", "protocol": "TCP", "source": {"nets": ["10.1.93.50/32"]},
                                  "destination": {"ports": [30080]}},
                                 {"action": "Deny", "protocol": "TCP", "destination": {"ports": [30080]}}]}}


def objects():
    return copy.deepcopy(FIXTURE["hostendpoints"]), copy.deepcopy(FIXTURE["globalnetworkpolicies"]), copy.deepcopy(FELIX)


def policy(gnps, host):
    return next(i for i in gnps["items"] if i["metadata"]["name"] == "fds-k8s-host-" + host)["spec"]


def run(heps, gnps, felix, upstreams=UPSTREAMS):
    return C.validate(heps, gnps, felix, G.HOSTS, G.SOURCE, upstreams)


class ContractTests(unittest.TestCase):
    def test_gate2_snapshot_passes(self):
        report = run(*objects())
        self.assertEqual(sorted(report), sorted(G.HOSTS))
        self.assertEqual(report["k8s-worker01"]["egress"]["approved_verdicts"], {"10.1.93.102": "Allow"})
        self.assertEqual(sorted(report["k8s-control01"]["egress"]["approved_verdicts"]), UPSTREAMS)
        self.assertEqual(len(report["k8s-control01"]["ingress"]["approved_verdicts"]), 5)

    def test_later_preDNAT_tcp_nodeport_policy_is_irrelevant(self):
        heps, gnps, felix = objects()
        gnps["items"].append(copy.deepcopy(NODEPORT))
        run(heps, gnps, felix)

    def fails(self, mutate, kind=C.ContractFail, upstreams=UPSTREAMS):
        heps, gnps, felix = objects()
        mutate(heps, gnps, felix)
        with self.assertRaises(kind):
            run(heps, gnps, felix, upstreams)

    def test_violations_fail(self):
        def broad(h, g, f):
            policy(g, "k8s-worker01")["egress"][4]["destination"]["nets"] = ["0.0.0.0/0"]
        def missing_allow(h, g, f):
            del policy(g, "k8s-worker02")["egress"][4]
        def early_allow_all(h, g, f):
            policy(g, "k8s-control02")["egress"].insert(0, {"action": "Allow"})
        def early_deny(h, g, f):
            policy(g, "k8s-worker03")["egress"].insert(0, {"action": "Deny", "protocol": "UDP"})
        def lower_order_allow(h, g, f):
            g["items"].append({"kind": "GlobalNetworkPolicy", "metadata": {"name": "zz"},
                               "spec": {"selector": "fds.example/role == 'worker'", "order": 10,
                                        "types": ["Egress"], "egress": [{"action": "Allow", "protocol": "UDP"}]}})
        def no_hep(h, g, f):
            h["items"] = [i for i in h["items"] if i["spec"]["node"] != "k8s-worker01"]
        def wildcard_hep(h, g, f):
            h["items"][0]["spec"]["interfaceName"] = "*"
        def duplicate_hep(h, g, f):
            h["items"].append(copy.deepcopy(h["items"][0]))
        def wide_ingress(h, g, f):
            policy(g, "k8s-control01")["ingress"][5]["source"]["nets"] = ["10.1.93.0/24"]
        def failsafe(h, g, f):
            f["items"][0]["spec"]["failsafeOutboundHostPorts"] = [{"protocol": "udp", "port": 123}]
        def unselected(h, g, f):
            policy(g, "k8s-worker01")["selector"] = 'fds.example/node == "nobody"'
        for mutate in (broad, missing_allow, early_allow_all, early_deny, lower_order_allow, no_hep,
                       wildcard_hep, duplicate_hep, wide_ingress, failsafe, unselected):
            with self.subTest(mutate.__name__):
                self.fails(mutate)
        with self.subTest("unapproved upstream set"):
            self.fails(lambda h, g, f: None, upstreams=["162.159.200.1", "194.58.200.20"])

    def test_unmodelled_grammar_stops(self):
        def grammar(h, g, f):
            policy(g, "k8s-worker01")["selector"] = "has(fds.example/node)"
        def pass_action(h, g, f):
            policy(g, "k8s-worker01")["egress"].insert(0, {"action": "Pass", "protocol": "UDP"})
        def do_not_track(h, g, f):
            policy(g, "k8s-worker01")["doNotTrack"] = True
        def tier(h, g, f):
            policy(g, "k8s-worker01")["tier"] = "security"
        def named_port(h, g, f):
            policy(g, "k8s-worker01")["egress"][4]["destination"]["ports"] = ["ntp"]
        def not_nets(h, g, f):
            policy(g, "k8s-worker01")["egress"][4]["destination"]["notNets"] = ["10.0.0.0/8"]
        def bpf(h, g, f):
            f["items"][0]["spec"]["bpfEnabled"] = True
        def felix_missing(h, g, f):
            f["items"] = []
        def predNAT_udp(h, g, f):
            item = copy.deepcopy(NODEPORT)
            item["spec"]["ingress"][0]["protocol"] = "UDP"
            item["spec"]["ingress"][0]["destination"]["ports"] = ["100:200"]
            # Ingress UDP/123 is contracted only on the NTP source (control01).
            item["spec"]["selector"] = "fds.example/role == 'control-plane'"
            g["items"].append(item)
        for mutate in (grammar, pass_action, do_not_track, tier, named_port, not_nets, bpf,
                       felix_missing, predNAT_udp):
            with self.subTest(mutate.__name__):
                self.fails(mutate, C.ContractStop)

    def test_tcp_rule_with_unmodelled_fields_is_skipped(self):
        heps, gnps, felix = objects()
        policy(gnps, "k8s-worker01")["egress"].insert(0, {"action": "Allow", "protocol": "TCP",
                                                         "destination": {"selector": "x == 'y'"}})
        run(heps, gnps, felix)

    def test_digest_ignores_volatile_metadata_only(self):
        heps, gnps, felix = objects()
        base = G.canonical_digest({"h": heps, "g": gnps})
        heps["items"][0]["metadata"]["resourceVersion"] = "999"
        self.assertEqual(base, G.canonical_digest({"h": heps, "g": gnps}))
        policy(gnps, "k8s-worker01")["order"] = 99
        self.assertNotEqual(base, G.canonical_digest({"h": heps, "g": gnps}))


# SYNTHETIC Felix-shaped wiring (see module docstring).
KERNEL = """# synthetic
*raw
:PREROUTING ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:cali-OUTPUT - [0:0]
:cali-to-host-endpoint - [0:0]
[9:9] -A OUTPUT -m comment --comment "cali:tVnHkvAo15HuiPy0" -j cali-OUTPUT
[9:9] -A cali-OUTPUT -m comment --comment "cali:ZbkN6P8OdRcBRPpU" -j cali-to-host-endpoint
COMMIT
*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
:cali-OUTPUT - [0:0]
:cali-to-host-endpoint - [0:0]
:cali-th-ens160 - [0:0]
:cali-po-default.fds-k8s-host-k8s-worker01 - [0:0]
[50:5000] -A OUTPUT -m comment --comment "cali:tVnHkvAo15HuiPy0" -j cali-OUTPUT
[0:0] -A cali-OUTPUT -m comment --comment "cali:Mq1_rAdXXH3YkrzW" -m mark --mark 0x10000/0x10000 -j ACCEPT
[3:300] -A cali-OUTPUT -o vxlan.calico -m comment --comment "cali:x" -j RETURN
[40:4000] -A cali-OUTPUT -m comment --comment "cali:IpTGXsDHURPUaLjJ" -m conntrack ! --ctstate DNAT -j cali-to-host-endpoint
[40:4000] -A cali-to-host-endpoint -o ens160 -m comment --comment "cali:y" -g cali-th-ens160
[30:3000] -A cali-th-ens160 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
[10:1000] -A cali-th-ens160 -j MARK --set-xmark 0x0/0x20000
[10:1000] -A cali-th-ens160 -j cali-po-default.fds-k8s-host-k8s-worker01
[8:800] -A cali-th-ens160 -m mark --mark 0x10000/0x10000 -j RETURN
[1:100] -A cali-th-ens160 -m comment --comment "End of tier default. Drop if no policies passed packet" -m mark --mark 0x0/0x20000 -j DROP
[8:800] -A cali-po-default.fds-k8s-host-k8s-worker01 -p udp -d 10.1.93.102/32 -m multiport --dports 123 -j MARK --set-xmark 0x10000/0x10000
[8:800] -A cali-po-default.fds-k8s-host-k8s-worker01 -m mark --mark 0x10000/0x10000 -j RETURN
[2:200] -A cali-po-default.fds-k8s-host-k8s-worker01 -j DROP
COMMIT
"""


def kernel(**drops):
    text = KERNEL
    for old, new in drops.items():
        text = text.replace(old, new)
    return text


class KernelTests(unittest.TestCase):
    def test_structure_and_drop_counters(self):
        value = K.structure(KERNEL)
        self.assertEqual(value["host_endpoint_chain"], "cali-th-ens160")
        self.assertEqual(value["drop_packets"], 3)
        self.assertFalse(value["legacy_ntp_chain_present"])
        # Counters change, structure digest does not.
        self.assertEqual(value["structure_sha256"],
                         K.structure(KERNEL.replace("[2:200] -A cali-po", "[7:700] -A cali-po"))["structure_sha256"])

    def test_broken_wiring_stops(self):
        cases = {
            "output not first": ("[50:5000] -A OUTPUT -m comment", "[1:1] -A OUTPUT -j ACCEPT\n[50:5000] -A OUTPUT -m comment"),
            "no dispatch": ("-m conntrack ! --ctstate DNAT -j cali-to-host-endpoint", "-j RETURN"),
            "other interface": ("-o ens160 -m comment --comment \"cali:y\"", "-o ens192 -m comment --comment \"cali:y\""),
            "no end-of-tier drop": ("-m mark --mark 0x0/0x20000 -j DROP", "-m mark --mark 0x0/0x20000 -j RETURN"),
            "untracked raw rule": ("[9:9] -A cali-OUTPUT -m comment --comment \"cali:ZbkN6P8OdRcBRPpU\" -j cali-to-host-endpoint",
                                   "[9:9] -A cali-OUTPUT -m comment --comment \"cali:ZbkN6P8OdRcBRPpU\" -j cali-to-host-endpoint\n"
                                   "[0:0] -A cali-to-host-endpoint -o ens160 -j ACCEPT"),
            "no counters": ("[50:5000] -A OUTPUT", "-A OUTPUT"),
        }
        for name, (old, new) in cases.items():
            with self.subTest(name):
                self.assertIn(old, KERNEL)
                with self.assertRaises(K.KernelStop):
                    K.structure(KERNEL.replace(old, new))

    def test_prefix_dispatch_is_followed(self):
        text = KERNEL.replace("-o ens160 -m comment --comment \"cali:y\" -g cali-th-ens160",
                              "-o ens+ -m comment --comment \"cali:y\" -g cali-th-ens160")
        self.assertEqual(K.structure(text)["host_endpoint_chain"], "cali-th-ens160")


def result(argv, stdout="", rc=0, stderr=""):
    return dict(argv=argv, returncode=rc, stdout=stdout, stderr=stderr, outer_timeout=False, elapsed_seconds=0.0)


ADDR = json.dumps([{"addr_info": [{"family": "inet", "local": "10.1.93.105"}]}])
TRACKING = """Reference ID    : 0A015D66 (10.1.93.102)
Stratum         : 4
System time     : 0.000012000 seconds fast of NTP time
Last offset     : -0.000020000 seconds
Leap status     : Normal
"""


class Runner:
    """Fake node: counters advance by `idle` per idle window and `probe` per probe."""
    def __init__(self, host="k8s-worker01", idle=0, probe=2, answered=False, firewalld="inactive",
                 sources="^* 10.1.93.102  3  6  377  10  +1us[+1us] +/- 1ms\n", documents=None):
        self.host, self.idle, self.probe, self.answered = host, idle, probe, answered
        self.firewalld, self.sources, self.documents = firewalld, sources, documents or {}
        self.drops, self.saves, self.calls = 3, 0, []

    def __call__(self, argv, timeout=20):
        self.calls.append(argv)
        if argv[:3] == ["ip", "-j", "-4"]:
            return result(argv, ADDR.replace("10.1.93.105", G.HOSTS[self.host]))
        if argv[:2] == ["systemctl", "is-active"]:
            return result(argv, self.firewalld + "\n", 0 if self.firewalld == "active" else 3)
        if argv[0] == "/usr/sbin/iptables-save":
            return result(argv, KERNEL.replace("[2:200] -A cali-po", "[%d:0] -A cali-po" % (self.drops - 1)))
        if argv[0].endswith("chronyd"):
            self.drops += self.probe
            text = "System clock wrong by 0.000100 seconds (ignored)\n" if self.answered else "No suitable source\n"
            return result(argv, "", 0 if self.answered else 1, text)
        if argv[:3] == ["chronyc", "-n", "tracking"]:
            return result(argv, TRACKING)
        if argv[:3] == ["chronyc", "-n", "sources"]:
            return result(argv, self.sources)
        if "kubectl" in argv[0]:
            return result(argv, json.dumps(self.documents[argv[4]]))
        raise AssertionError(argv)


def params(host="k8s-worker01", gate="negative"):
    return dict(gate=gate, phase="packets", run_id="fixture-001", source_head="a" * 40,
                inventory_hostname=host, ansible_host=G.HOSTS[host], source_upstreams=UPSTREAMS,
                kubeconfig="/etc/kubernetes/admin.conf", kubectl_path="/usr/bin/kubectl",
                chronyd_path="/usr/sbin/chronyd", probe_timeout=5, offset_limit_ms=100)


def gate(runner, **kwargs):
    value = G.Gate(params(runner.host, **kwargs), runner=runner, sleeper=lambda s: setattr(runner, "drops", runner.drops + runner.idle))
    G.socket.gethostname = lambda: runner.host
    return value.run()


class GateTests(unittest.TestCase):
    def test_negative_attributed_drop_passes(self):
        receipt = gate(Runner())
        self.assertTrue(receipt["gate_pass"], receipt["errors"])
        # Client: TEST-NET plus both public upstreams (direct public NTP must be blocked).
        self.assertEqual([t["target"] for t in receipt["result"]["targets"]], ["192.0.2.123"] + UPSTREAMS)
        source = gate(Runner(host="k8s-control01"))
        self.assertEqual([t["target"] for t in source["result"]["targets"]], ["192.0.2.123"])

    def test_negative_failures(self):
        for name, runner in {"answered": Runner(answered=True),
                             "background noise only": Runner(idle=2, probe=2),
                             "no drop": Runner(probe=0),
                             "firewalld active": Runner(firewalld="active")}.items():
            with self.subTest(name):
                self.assertFalse(gate(runner)["gate_pass"])

    def test_sample(self):
        self.assertTrue(gate(Runner(), gate="sample")["gate_pass"])
        wrong = Runner(sources="^* 162.159.200.1  3  6  377  10  +1us[+1us] +/- 1ms\n")
        self.assertFalse(gate(wrong, gate="sample")["gate_pass"])

    def test_contract_gate_reads_calico_and_digests(self):
        heps, gnps, felix = objects()
        runner = Runner(host="k8s-control01", documents={
            "hostendpoints.crd.projectcalico.org": heps,
            "globalnetworkpolicies.crd.projectcalico.org": gnps,
            "felixconfigurations.crd.projectcalico.org": felix})
        receipt = gate(runner, gate="contract")
        self.assertTrue(receipt["gate_pass"], receipt["stops"] + receipt["errors"])
        self.assertRegex(receipt["result"]["calico_digest"], "^[0-9a-f]{64}$")
        self.assertTrue(all(argv[3] == "get" for argv in runner.calls if "kubectl" in argv[0]))
        with self.assertRaises(ValueError):
            G.Gate(params("k8s-worker01", gate="contract"), runner=runner).contract()

    def test_binding_is_enforced(self):
        bad = params()
        bad["ansible_host"] = "10.1.93.250"
        with self.assertRaises(ValueError):
            G.Gate(bad, runner=Runner())


if __name__ == "__main__":
    unittest.main()
