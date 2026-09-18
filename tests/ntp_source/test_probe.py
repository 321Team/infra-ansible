#!/usr/bin/env python3
"""Probe tests: mocked host observations plus optional real chrony on loopback only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket
import struct
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("probe", ROOT / "library/fds_ntp_probe.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
UPSTREAMS = ["162.159.200.1", "162.159.200.123", "129.6.15.28"]  # Fixture inputs, never contacted.


def args(host="k8s-control01", gate="diagnose"):
    return dict(inventory_hostname=host, ansible_host=P.HOSTS[host], gate=gate,
                run_id="fixture-001", source_head="a" * 40, input_sha256="b" * 64,
                source_upstreams=UPSTREAMS, migration_plan={"validated": True})


def result(argv, stdout="", rc=0, stderr=""):
    return dict(argv=argv, returncode=rc, stdout=stdout, stderr=stderr,
                outer_timeout=False, elapsed_seconds=0.001)


class Fixture:
    def __init__(self, settings=None, **changes):
        self.args = settings or args()
        self.changes = changes
        self.calls = []

    def run(self, argv, timeout=10):
        self.calls.append(argv)
        if argv[:4] == ["ip", "-j", "-4", "address"]:
            address = self.changes.get("ip", self.args["ansible_host"])
            return result(argv, json.dumps([{"addr_info": [{"family": "inet", "local": address}]}]))
        if "-Q" in argv:
            offset = self.changes.get("probe_offset", "0.00001")
            return result(argv, stderr="Disabled control of system clock\nSystem clock wrong by %s seconds (ignored)\n" % offset)
        if "-v" in argv:
            return result(argv, self.changes.get("version", "chronyd (chrony) version 4.8 (+NTS)"))
        if "--property=Environment" in argv:
            return result(argv, self.changes.get("inline_environment", ""))
        if argv[:3] == ["systemctl", "show", "chronyd.service"]:
            return result(argv, "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=1234\nExecStart={ argv[]=/usr/sbin/chronyd -n $OPTIONS ; ignore_errors=no }\nEnvironmentFiles=/etc/sysconfig/chronyd (ignore_errors=yes)\nFragmentPath=/usr/lib/systemd/system/chronyd.service\nDropInPaths=" + self.changes.get("override", ""))
        if argv[:3] == ["systemctl", "show", "systemd-timesyncd.service"]:
            if self.changes.get("incomplete_conflict"):
                return result(argv, "", 1, "Failed to connect to bus")
            text = "\n\n".join("Id=%s\nLoadState=not-found\nActiveState=%s" % (unit, self.changes.get("conflict_state", "inactive"))
                               for unit in ("systemd-timesyncd.service", "ntpd.service", "ntpsec.service"))
            return result(argv, text, 1, "Some units not found")
        if "-p" in argv and "-f" in argv:
            lines = ["server " + ip + " iburst" for ip in UPSTREAMS]
            lines += ["allow " + ip + "/32" for ip in P.CLIENTS]
            if self.changes.get("broad_acl"):
                lines.append("allow 10.0.0.0/8")
            return result(argv, "\n".join(lines), self.changes.get("parser_rc", 0))
        if argv == ["chronyc", "tracking"]:
            return result(argv, "Leap status : %s\nLast offset : %s seconds\nSystem time : 0.00001 seconds fast of NTP time\nStratum : 3\n" %
                          (self.changes.get("leap", "Normal"), self.changes.get("last_offset", "0.00001")))
        if argv == ["chronyc", "-n", "sources", "-a"]:
            ips = self.changes.get("runtime_ips", UPSTREAMS)
            return result(argv, "\n".join(("^*" if index == 0 else "^+") + " " + ip + " 2 6 377 1 +0us" for index, ip in enumerate(ips)))
        if argv[0] == "ss":
            return result(argv, 'UNCONN 0 0 0.0.0.0:123 0.0.0.0:* users:(("chronyd",pid=%s,fd=6))' % self.changes.get("listener_pid", "1234"))
        if argv[:2] == ["chronyc", "accheck"]:
            return result(argv, self.changes.get("access", "208 Access allowed") + "\n")
        raise AssertionError("Unexpected command: " + repr(argv))

    def receipt(self):
        fixture = self
        class Observed(P.Observation):
            def inspect_process(self, pid):
                argv = fixture.changes.get("argv", ["/usr/sbin/chronyd", "-n", "-F", "2"])
                self.observations["expanded_exec_argv"] = argv
                self.observations["running_executable"] = "/usr/sbin/chronyd"
                P.service_arguments(argv, self.chronyd, self.main_path)
        def options_text(path):
            if self.changes.get("options_missing"):
                raise FileNotFoundError("optional fixture EnvironmentFile absent")
            return self.changes.get("options_text", 'OPTIONS="-F 2"\n')
        with patch.object(P.socket, "gethostname", return_value=self.changes.get("hostname", self.args["inventory_hostname"])), patch.object(P.Path, "read_bytes", return_value=b"fixture main\n"), patch.object(P.Path, "read_text", options_text):
            return Observed(self.args, self.run).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chronyd", type=Path)
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    results = []
    def check(name, function):
        try:
            detail = function()
            results.append(dict(name=name, passed=True, detail=detail))
        except Exception as exc:
            results.append(dict(name=name, passed=False, error=repr(exc)))
    def good(host, gate):
        receipt = Fixture(args(host, gate)).receipt()
        assert receipt["gate_pass"], receipt["errors"]
        expected = UPSTREAMS if host == P.SOURCE and gate == "diagnose" else [P.HOSTS[P.SOURCE]] if host != P.SOURCE and gate == "pathcheck" else []
        assert [r["target_address"] for r in receipt["probes"]] == expected
        assert all(value is True for value in receipt["observations"]["checks"].values())
        return receipt
    for gate in ("diagnose", "pathcheck"):
        for host in P.HOSTS:
            check(gate + "_" + host, lambda host=host, gate=gate: good(host, gate))
    failures = [dict(hostname="wrong-host"), dict(ip="10.0.0.1"), dict(version="chronyd version 4.7"),
                dict(override="/etc/systemd/system/chronyd.service.d/custom.conf"), dict(conflict_state="active"),
                dict(incomplete_conflict=True), dict(parser_rc=1), dict(argv=["/usr/sbin/chronyd", "-x"]),
                dict(argv=["/usr/sbin/chronyd", "-f", "/tmp/other.conf"]),
                dict(argv=["/usr/sbin/chronyd", "server 1.2.3.4"]), dict(leap="Insert second"),
                dict(last_offset="0.2"), dict(last_offset="1e999"), dict(runtime_ips=UPSTREAMS[:2]),
                dict(broad_acl=True), dict(listener_pid="9999"), dict(access="209 Access denied"),
                dict(options_text='OPTIONS="-f /tmp/other.conf"\n'), dict(options_text='OPTIONS="-F 1"\n'),
                dict(options_text='OPTIONS="-F 2"\nOTHER="unreviewed"\n'), dict(inline_environment="OPTIONS=-x")]
    def reject(settings, changes):
        receipt = Fixture(settings, **changes).receipt()
        assert not receipt["gate_pass"] and receipt["errors"], receipt
        return receipt["errors"]
    for number, changes in enumerate(failures):
        check("reject_observation_%02d" % number, lambda changes=changes: reject(args(gate="pathcheck"), changes))
    check("reject_failed_plan", lambda: reject(dict(args(), migration_plan={"validated": False}), {}))
    check("reject_250ms_probe", lambda: reject(args(), {"probe_offset": "0.250000"}))
    def reject_nonfinite_probe():
        receipt = Fixture(args(), probe_offset="9" * 400).receipt()
        assert not receipt["gate_pass"] and receipt["errors"]
        assert all(probe["offset_seconds"] is None for probe in receipt["probes"])
        json.dumps(receipt, allow_nan=False)
        return receipt["errors"]
    check("reject_nonfinite_probe", reject_nonfinite_probe)
    def optional_environment_absent():
        receipt = Fixture(args(), options_missing=True, argv=["/usr/sbin/chronyd", "-n"]).receipt()
        assert receipt["gate_pass"], receipt["errors"]
        return receipt["observations"]["restart_exec_argv"]
    check("optional_environment_file_absent", optional_environment_absent)
    def reject_binding(changes):
        try:
            P.validate_bindings(dict(args(), **changes))
        except ValueError as exc:
            return str(exc)
        raise AssertionError("Invalid binding accepted")
    for number, changes in enumerate([dict(ansible_host="10.1.93.103"), dict(run_id="../bad"), dict(source_head="a" * 39),
                                      dict(input_sha256="wrong"), dict(source_upstreams=UPSTREAMS[:2]),
                                      dict(source_upstreams=["127.0.0.1"] + UPSTREAMS[:2])]):
        check("reject_binding_%02d" % number, lambda changes=changes: reject_binding(changes))
    if options.chronyd:
        def real_probe(offset, leap):
            packets = []
            def timestamp(value):
                whole = int(value)
                return struct.pack("!II", (whole + 2208988800) & 0xffffffff, int((value - whole) * 2**32))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
                server.bind(("127.0.0.1", 0))
                server.settimeout(0.1)
                stop = threading.Event()
                def serve():
                    while not stop.is_set():
                        try:
                            request, peer = server.recvfrom(4096)
                        except socket.timeout:
                            continue
                        packets.append(peer[1])
                        received = time.time() + offset
                        response = bytearray(48)
                        response[:4] = bytes(((leap << 6) | 36, 2, 6, 236))
                        response[4:12] = struct.pack("!II", 65, 65)
                        response[12:16] = bytes((127, 0, 0, 2))
                        response[16:24] = timestamp(received - 1)
                        response[24:32] = request[40:48]
                        response[32:40] = timestamp(received)
                        response[40:48] = timestamp(time.time() + offset)
                        server.sendto(response, peer)
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                def local_runner(argv, timeout):
                    argv = list(argv)
                    index = argv.index("server 127.0.0.1 iburst")
                    argv[index] += " port " + str(server.getsockname()[1])
                    return P.command(argv, timeout)
                try:
                    receipt = P.run_probe(str(options.chronyd.resolve()), "127.0.0.1", local_runner, timeout=12)
                finally:
                    stop.set()
                    thread.join(timeout=1)
                assert receipt["gate_pass"] is (leap == 0 and offset < 0.1), receipt
                assert receipt["sample_accepted"] is (leap == 0), receipt
                assert packets and all(port != 123 for port in packets)
                return dict(receipt=receipt, source_ports=packets, scope="Loopback mock only; random destination port injected by test runner")
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [(name, executor.submit(real_probe, offset, leap)) for name, offset, leap in
                       [("real_Q_good", 0.0, 0), ("real_Q_bad_offset", 0.25, 0), ("real_Q_unsynchronised", 0.0, 3)]]
            for name, future in futures:
                check(name, future.result)
    import hashlib
    report = dict(scope=__doc__, module_sha256=hashlib.sha256((ROOT / "library/fds_ntp_probe.py").read_bytes()).hexdigest(),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  real_chronyd_loopback_cases=sum(r['name'].startswith('real_Q_') for r in results),
                  results=results, total=len(results), passed=sum(r["passed"] for r in results))
    (options.output / "RESULTS.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    for r in results:
        print("PASS" if r["passed"] else "FAIL", r["name"], r.get("error", ""))
    print("%d/%d passed" % (report["passed"], report["total"]))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
