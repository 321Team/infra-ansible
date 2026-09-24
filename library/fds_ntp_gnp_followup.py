#!/usr/bin/python
"""CR-P1-NTP-01-01 follow-up gates for Calico-enforced NTP (Plan A).

Gates (all run from ansible01 through the playbook; none changes policy,
service state, clock or files on the node):
  contract  k8s-control01: read HEP/GNP/FelixConfiguration with kubectl get
            and evaluate the declarative UDP/123 contract for all six hosts.
  kernel    each node: firewalld inactive and the Felix ens160 HostEndpoint
            egress wiring present (iptables-save -c, read only).
  negative  each node: chronyd -Q to non-approved targets must get no reply
            and the HostEndpoint DROP counters must rise above an idle window.
  sample    each node: chronyc tracking/sources against the approved topology.
Receipts (including failures) are returned for preservation on the controller.
"""
import datetime
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import time

from ansible.module_utils.fds_ntp_gnp_contract import ContractFail, ContractStop, validate
from ansible.module_utils.fds_ntp_hep_kernel import KernelStop, parse, drop_packets, structure
from ansible.module_utils.fds_ntp_policy import validate_public_upstreams

HOSTS = {"k8s-control01": "10.1.93.102", "k8s-control02": "10.1.93.103",
         "k8s-control03": "10.1.93.104", "k8s-worker01": "10.1.93.105",
         "k8s-worker02": "10.1.93.107", "k8s-worker03": "10.1.93.108"}
SOURCE = "k8s-control01"
# RFC 5737 TEST-NET-1: never an approved peer; any reply would itself be a finding.
NEGATIVE_UNAPPROVED = "192.0.2.123"
CALICO_RESOURCES = (("hostendpoints", "hostendpoints.crd.projectcalico.org"),
                    ("globalnetworkpolicies", "globalnetworkpolicies.crd.projectcalico.org"),
                    ("felixconfigurations", "felixconfigurations.crd.projectcalico.org"))
VOLATILE_METADATA = ("creationTimestamp", "generation", "resourceVersion", "uid", "managedFields", "annotations")


def clean_environment():
    env = {k: v for k, v in os.environ.items() if k not in ("LISTEN_FDS", "LISTEN_PID", "NOTIFY_SOCKET")}
    env["LC_ALL"] = "C"
    return env


def command(argv, timeout=20):
    started = time.monotonic()
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=False,
                              timeout=timeout, env=clean_environment())
        rc, out, err, expired = done.returncode, done.stdout, done.stderr, False
    except subprocess.TimeoutExpired as exc:
        def text(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
        rc, out, err, expired = 124, text(exc.stdout), text(exc.stderr), True
    except OSError as exc:
        rc, out, err, expired = 127, "", str(exc), False
    return {"argv": argv, "returncode": rc, "stdout": out, "stderr": err,
            "outer_timeout": expired, "elapsed_seconds": time.monotonic() - started}


def canonical_digest(documents):
    """Digest of labels/spec only, for start/end drift comparison in one run."""
    projection = {}
    for key, document in sorted(documents.items()):
        projection[key] = sorted(
            [{"kind": item.get("kind"), "name": item.get("metadata", {}).get("name"),
              "labels": item.get("metadata", {}).get("labels") or {}, "spec": item.get("spec")}
             for item in document.get("items", [])], key=lambda x: str(x["name"]))
    return hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()


def tracking_values(text, limit_ms):
    def field(pattern):
        values = re.findall(pattern, text, re.M)
        if len(values) != 1:
            raise ValueError("Missing or duplicate tracking field")
        return values[0].strip()
    leap = field(r"^Leap status\s*:\s*([^\r\n]+)$")
    last = float(field(r"^Last offset\s*:\s*([+\-0-9.eE]+)\s+seconds\s*$"))
    current = float(field(r"^System time\s*:\s*([+\-0-9.eE]+)\s+seconds\s+(?:fast|slow) of NTP time\s*$"))
    reference = field(r"^Reference ID\s*:\s*\S+\s+\(([^)]*)\)\s*$")
    values = dict(leap_status=leap, last_offset_seconds=last, system_time_seconds=current,
                  reference=reference)
    if leap != "Normal" or not all(math.isfinite(x) and abs(x) <= limit_ms / 1000.0 for x in (last, current)):
        raise ValueError("Tracking fails Leap Normal or %dms offset policy: %r" % (limit_ms, values))
    return values


class Gate:
    def __init__(self, params, runner=command, sleeper=time.sleep):
        self.p, self.runner, self.sleep = params, runner, sleeper
        self.errors, self.stops, self.observations = [], [], {}
        if params["inventory_hostname"] not in HOSTS or HOSTS[params["inventory_hostname"]] != params["ansible_host"]:
            raise ValueError("Inventory binding is outside the reviewed six-host topology")
        if not re.fullmatch(r"[0-9a-f]{40}", params["source_head"]) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", params["run_id"]):
            raise ValueError("Malformed run binding")
        self.upstreams = validate_public_upstreams(params["source_upstreams"])

    def observe(self, name, argv, timeout=20):
        result = self.runner(argv, timeout=timeout)
        self.observations[name] = result
        return result

    def identity(self):
        host = self.p["inventory_hostname"]
        self.observations["hostname"] = socket.gethostname()
        if self.observations["hostname"].split(".")[0] != host:
            self.errors.append("Observed hostname differs from inventory binding")
        addresses = self.observe("local_ipv4", ["ip", "-j", "-4", "address", "show"])
        try:
            local = [a["local"] for link in json.loads(addresses["stdout"])
                     for a in link.get("addr_info", []) if a.get("family") == "inet"]
        except (ValueError, KeyError, TypeError):
            local = []
        if self.p["ansible_host"] not in local:
            self.errors.append("Expected host IP is not configured locally")

    # --- contract -------------------------------------------------------
    def contract(self):
        if self.p["inventory_hostname"] != SOURCE:
            raise ValueError("Contract gate runs only on " + SOURCE)
        documents = {}
        for key, resource in CALICO_RESOURCES:
            result = self.observe("kubectl_" + key, [self.p["kubectl_path"], "--kubeconfig", self.p["kubeconfig"],
                                                     "get", resource, "-o", "json", "--request-timeout=20s"], timeout=30)
            if result["returncode"] != 0:
                self.stops.append("kubectl get %s failed" % resource)
                continue
            try:
                documents[key] = json.loads(result["stdout"])
            except ValueError:
                self.stops.append("kubectl get %s returned non-JSON" % resource)
        if self.stops:
            return {}
        report = {}
        try:
            report = validate(documents["hostendpoints"], documents["globalnetworkpolicies"],
                              documents["felixconfigurations"], HOSTS, SOURCE, self.upstreams)
        except ContractStop as exc:
            self.stops.append("STOP " + str(exc))
        except ContractFail as exc:
            self.errors.append("FAIL " + str(exc))
        return {"hosts": report, "calico_digest": canonical_digest(documents)}

    # --- kernel ---------------------------------------------------------
    def kernel(self):
        state = self.observe("firewalld_active", ["systemctl", "is-active", "firewalld"])
        if state["stdout"].strip() != "inactive":
            self.errors.append("firewalld must be inactive after Gate 2 (observed %r)" % state["stdout"].strip())
        saved = self.observe("iptables_save", ["/usr/sbin/iptables-save", "-c"], timeout=30)
        if saved["returncode"] != 0:
            self.stops.append("iptables-save -c failed")
            return {}
        try:
            return structure(saved["stdout"])
        except KernelStop as exc:
            self.errors.append("FAIL " + str(exc))
            return {}

    def _drops(self, chain):
        saved = self.runner(["/usr/sbin/iptables-save", "-c"], timeout=30)
        if saved["returncode"] != 0:
            raise KernelStop("iptables-save -c failed during counter sampling")
        return drop_packets(parse(saved["stdout"]), chain)

    # --- negative -------------------------------------------------------
    def negative(self):
        kernel = self.kernel()
        if self.errors or self.stops:
            return {"kernel": kernel, "targets": []}
        chain, timeout = kernel["host_endpoint_chain"], self.p["probe_timeout"]
        targets = [NEGATIVE_UNAPPROVED] + ([] if self.p["inventory_hostname"] == SOURCE else list(self.upstreams))
        results = []
        try:
            for target in targets:
                results.append(self._negative_one(chain, target, timeout))
        except KernelStop as exc:
            self.stops.append("STOP " + str(exc))
        return {"kernel": kernel, "targets": results}

    def _negative_one(self, chain, target, timeout):
        """Idle window then probe window of equal length; attribute by delta."""
        before = self._drops(chain)
        self.sleep(timeout)
        idle = self._drops(chain)
        probe = self.runner([self.p["chronyd_path"], "-4", "-Q", "-t", str(timeout),
                             "server " + target + " iburst", "pidfile /", "port 0",
                             "cmdport 0", "bindcmdaddress /"], timeout=timeout + 5)
        after = self._drops(chain)
        text = probe["stdout"] + "\n" + probe["stderr"]
        answered = bool(re.search(r"System clock wrong by", text))
        idle_delta, probe_delta = idle - before, after - idle
        passed = (not answered) and probe_delta >= idle_delta + 1
        if not passed:
            self.errors.append("Negative UDP/123 to %s not attributed to HostEndpoint DROP "
                               "(answered=%s idle=%d probe=%d)" % (target, answered, idle_delta, probe_delta))
        return {"target": target, "probe": probe, "answered": answered,
                "drop_packets": [before, idle, after], "idle_delta": idle_delta,
                "probe_delta": probe_delta, "gate_pass": passed}

    # --- sample ---------------------------------------------------------
    def sample(self):
        tracking = self.observe("tracking", ["chronyc", "-n", "tracking"])
        sources = self.observe("sources", ["chronyc", "-n", "sources", "-a"])
        values = {}
        try:
            values = tracking_values(tracking["stdout"], self.p["offset_limit_ms"])
        except (ValueError, OverflowError) as exc:
            self.errors.append(str(exc))
        rows = re.findall(r"^([\^=#][*+?x~-])\s+(\S+)\s+", sources["stdout"], re.M)
        selected = [ip for state, ip in rows if state == "^*"]
        expected = self.upstreams if self.p["inventory_hostname"] == SOURCE else [HOSTS[SOURCE]]
        if sorted(ip for _, ip in rows) != sorted(expected) or len(selected) != 1:
            self.errors.append("Sources must be exactly %s with one selected; observed %r" % (expected, rows))
        return {"tracking": values, "selected": selected, "sources": rows}

    def run(self):
        self.identity()
        gate = self.p["gate"]
        result = {} if self.errors else getattr(self, gate)()
        return {"schema_version": 1, "gate": gate, "phase": self.p["phase"], "run_id": self.p["run_id"],
                "source_head": self.p["source_head"], "inventory_hostname": self.p["inventory_hostname"],
                "ansible_host": self.p["ansible_host"],
                "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "result": result, "observations": self.observations,
                "stops": self.stops, "errors": self.errors,
                "gate_pass": not self.errors and not self.stops}


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        "gate": {"choices": ["contract", "kernel", "negative", "sample"], "required": True},
        "phase": {"choices": ["start", "packets", "end"], "required": True},
        "run_id": {"type": "str", "required": True},
        "source_head": {"type": "str", "required": True},
        "inventory_hostname": {"type": "str", "required": True},
        "ansible_host": {"type": "str", "required": True},
        "source_upstreams": {"type": "list", "elements": "str", "required": True},
        "kubeconfig": {"type": "path", "default": "/etc/kubernetes/admin.conf"},
        "kubectl_path": {"type": "path", "default": "/usr/bin/kubectl"},
        "chronyd_path": {"type": "path", "default": "/usr/sbin/chronyd"},
        "probe_timeout": {"type": "int", "default": 10},
        "offset_limit_ms": {"type": "int", "default": 100},
    }, supports_check_mode=True)
    params = module.params
    if not 3 <= params["probe_timeout"] <= 20 or not 1 <= params["offset_limit_ms"] <= 100:
        module.fail_json(changed=False, msg="Probe timeout or offset limit outside reviewed bounds")
    try:
        module.exit_json(changed=False, receipt=Gate(params).run())
    except (ValueError, OSError, TypeError, KeyError) as exc:
        module.fail_json(changed=False, msg=str(exc))


if __name__ == "__main__":
    main()
