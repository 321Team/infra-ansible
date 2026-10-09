"""Synthetic fixtures only. Never call SSH, systemctl, Docker or vmrun."""
import ast
import base64
import datetime
import importlib.util
import json
import os
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "module_utils"))
import fds_shutdown_core as core
from fds_shutdown_guest import Guest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


coord = load("coordinator", "tools/phase1-shutdown.py")
windows = load("workstation", "tools/phase1-workstation.py")
BOOT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def plan():
    bindings = {"schema": core.SCHEMA, "resources": {},
        "workstation_names": {"server%02d" % i: "SERVER%02d" % i for i in range(1, 9)},
        "operator_checks": {k: "SYNTHETIC_FIXTURE_NOT_EVIDENCE" for k in
            ("window_ref", "app_quiesce_ref", "etcd_recovery_ref", "db_recovery_ref", "harbor_recovery_ref")}}
    bindings["operator_checks"].update(full_cluster_outage_confirmed=True, ci_dispatch_paused=True)
    for i, (name, fixed) in enumerate(core.FLEET.items(), 1):
        bindings["resources"][name] = dict(fixed, ssh_user="operator", hostname=name,
            machine_id="%032x" % i, vmx_path="C:/VMs/" + name + "/" + name + ".vmx",
            vmx_uuid="56 4d 00 00 00 00 00 %02x-00 00 00 00 00 00 00 %02x" % (i, i))
    bindings["resources"]["db01"]["database_unit"] = "postgresql.service"
    return {"schema": core.SCHEMA, "operation_id": "fixture-round", "created_at": core.utc(),
        "source_commit": "a" * 40, "bindings": bindings, "binding_digest": core.digest(bindings),
        "fleet": core.FLEET, "phases": core.PHASES}


def receipt(p, name):
    b = p["bindings"]["resources"][name]
    return dict(schema=core.SCHEMA, operation_id=p["operation_id"], binding_digest=p["binding_digest"],
        resource=name, physical_host=b["physical_host"], vmx_uuid=b["vmx_uuid"], vmx_path=b["vmx_path"],
        observed_at=core.utc(), observer="vmrun-list", power_state="POWERED_OFF",
        clean_vmx_exit=True, suspend_state_absent=True)


def ready(p, state):
    value = {"operation_id": p["operation_id"], "binding_digest": p["binding_digest"],
        "observed_at": core.utc(), "status": "READY_FOR_EXPLICIT_PHASE",
        "observations": {n: {"boot_id": BOOT} for n in core.FLEET}}
    core.save(state / "preflight.json", value)
    return value


class Contracts(unittest.TestCase):
    def test_fleet_exact_and_scope_exclusions(self):
        p = core.validate_plan(plan())
        self.assertEqual(17, len(core.FLEET))
        self.assertEqual(list(core.FLEET), sum(core.PHASES.values(), []))
        self.assertNotIn("10.1.93.51", [x["ip"] for x in core.FLEET.values()])
        self.assertEqual(["ansible01", "mgmt-gw01"], core.PHASES["management"])
        self.assertEqual("harbor-log", core.HARBOR_STOP_ORDER[-1])

    def test_invalid_bindings_and_tamper_blocked(self):
        for field, value in [("ip", "10.1.93.51"), ("physical_host", "server02"),
                             ("ssh_user", "root"), ("vmx_path", "C:/VMs/../clone.vmx"),
                             ("machine_id", ""), ("vmx_uuid", "unknown")]:
            with self.subTest(field=field):
                p = plan()
                p["bindings"]["resources"]["harbor01"][field] = value
                with self.assertRaises(core.Stop): core.validate_plan(p)
        p = plan(); p["bindings"]["operator_checks"]["ci_dispatch_paused"] = False
        with self.assertRaises(core.Stop): core.validate_plan(p)

    def test_receipt_requires_clean_external_poweroff_and_fresh_round(self):
        p = plan()
        cases = {"power_state": "SSH_DOWN", "clean_vmx_exit": False, "suspend_state_absent": False,
            "vmx_uuid": "wrong", "operation_id": "other-round", "binding_digest": "b" * 64,
            "observed_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=6)).isoformat()}
        for field, value in cases.items():
            with self.subTest(field=field):
                r = receipt(p, "edge01"); r[field] = value
                with self.assertRaises(core.Stop): core.receipt_for(p, "edge01", r)
        r = receipt(p, "edge01")
        r["observed_at"] = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)).isoformat()
        with self.assertRaises(core.Stop): core.receipt_for(p, "edge01", r)

    def test_private_intent_is_exclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "claim.json"
            core.save(path, {"state": "UNKNOWN"}, exclusive=True)
            with self.assertRaises(FileExistsError): core.save(path, {}, exclusive=True)
            self.assertEqual("UNKNOWN", core.private_json(path)["state"])


class Adapter:
    def __init__(self, p, receipts, fail=False):
        self.p, self.receipts, self.fail, self.calls = p, receipts, fail, []

    def call(self, p, name, action, state, observed=None):
        self.calls.append((name, action))
        if action == "request":
            if self.fail: raise core.Stop("Lost response after submission")
            core.save(self.receipts / (name + ".json"), receipt(p, name))
            return {"status": "NORMAL_SHUTDOWN_SCHEDULED"}
        return {"status": "READ_ONLY", "observation": {"boot_id": BOOT}}


class Coordinator(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = core.secure_dir(Path(self.temp.name) / "state")
        self.receipts = core.secure_dir(Path(self.temp.name) / "receipts")
        self.p = plan(); self.confirm = "POWER_OFF:" + self.p["operation_id"] + ":" + self.p["binding_digest"]
        ready(self.p, self.state)

    def test_full_preflight_all_seventeen_no_mutation(self):
        adapter = Adapter(self.p, self.receipts)
        coord.preflight(self.p, self.state, self.receipts, adapter)
        self.assertEqual(17, len(adapter.calls))
        self.assertTrue(all(action == "preflight" for _, action in adapter.calls))
        self.assertFalse(list(self.state.glob("*.intent.json")))

    def test_fixed_order_and_idempotent_off_observation(self):
        adapter = Adapter(self.p, self.receipts)
        coord.execute_phase(self.p, "consumers", self.state, self.receipts, adapter, self.confirm, 1)
        self.assertEqual([("cicd-runner01", "request"), ("edge01", "request")],
                         [x for x in adapter.calls if x[1] == "request"])
        adapter.calls.clear()
        coord.execute_phase(self.p, "consumers", self.state, self.receipts, adapter, self.confirm, 1)
        self.assertEqual([], adapter.calls)

    def test_missing_prior_receipt_wrong_confirmation_management_blocked(self):
        adapter = Adapter(self.p, self.receipts)
        for phase, confirm in [("workers", self.confirm), ("consumers", "yes"), ("management", self.confirm)]:
            with self.subTest(phase=phase):
                with self.assertRaises((core.Stop, OSError)):
                    coord.execute_phase(self.p, phase, self.state, self.receipts, adapter, confirm, 1)
        self.assertEqual([], adapter.calls)

    def test_lost_response_claim_prevents_second_mutation_and_next_target(self):
        adapter = Adapter(self.p, self.receipts, fail=True)
        for _ in range(2):
            with self.assertRaises((core.Stop, FileExistsError)):
                coord.execute_phase(self.p, "consumers", self.state, self.receipts, adapter, self.confirm, 1)
        self.assertEqual(1, adapter.calls.count(("cicd-runner01", "request")))
        self.assertNotIn(("edge01", "request"), adapter.calls)
        with self.assertRaises(core.Stop): coord.preflight(self.p, self.state, self.receipts, adapter)

    def test_boot_changed_blocks_before_claim(self):
        adapter = Adapter(self.p, self.receipts)
        r = ready(self.p, self.state); r["observations"]["cicd-runner01"]["boot_id"] = "old"
        core.save(self.state / "preflight.json", r)
        with self.assertRaises(core.Stop): coord.execute_phase(self.p, "consumers", self.state, self.receipts, adapter, self.confirm, 1)
        self.assertFalse(list(self.state.glob("*.intent.json")))

    def test_receive_round_and_monotonic_observations(self):
        incoming = receipt(self.p, "edge01")
        coord.receive(self.p, self.receipts, [incoming])
        newer = dict(incoming, observed_at=core.utc(), power_state="UNKNOWN")
        coord.receive(self.p, self.receipts, [newer])
        self.assertFalse(coord.already_off(self.p, "edge01", self.receipts))
        with self.assertRaises(core.Stop): coord.receive(self.p, self.receipts, [incoming])
        wrong = receipt(self.p, "db01"); wrong["operation_id"] = "wrong"
        with self.assertRaises(core.Stop): coord.receive(self.p, self.receipts, [wrong])
        self.assertFalse((self.receipts / "db01.json").exists())

    def test_receive_cli_uses_separate_lock_while_executor_waits(self):
        core.save(self.state / "plan.json", self.p)
        locks = []
        def lock(path):
            locks.append(path)
            return coord.contextlib.nullcontext()
        stdin = types.SimpleNamespace(buffer=io.BytesIO(json.dumps([receipt(self.p, "edge01")]).encode()))
        with patch.object(sys, "argv", ["phase1-shutdown.py", "receive", "--state", str(self.state), "--receipts", str(self.receipts)]), \
             patch.object(sys, "stdin", stdin), patch.object(coord, "clean_source", return_value="a" * 40), \
             patch.object(coord, "locked", side_effect=lock), coord.contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, coord.main())
        self.assertEqual([self.receipts], locks)

    @unittest.skipUnless(os.name == "posix", "POSIX key ownership/mode gate")
    def test_existing_ssh_key_metadata_only_and_permissions(self):
        key = self.state / "fixture-key"
        key.write_text("SYNTHETIC NOT A KEY")
        key.chmod(0o600)
        with patch.object(Path, "read_text", side_effect=AssertionError("Do not read private key")), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("Do not read private key")):
            self.assertEqual(key, coord.Ansible.key_path(key))
        key.chmod(0o644)
        with self.assertRaises(core.Stop): coord.Ansible.key_path(key)


class GuestFixtures(unittest.TestCase):
    def make(self, name, changes=None):
        p = plan(); expected = p["bindings"]["resources"][name]; calls = []
        files = {"/etc/machine-id": expected["machine_id"], "/proc/1/comm": "systemd",
            "/proc/sys/kernel/random/boot_id": BOOT,
            "/proc/123/cmdline": "/usr/bin/kubelet\0--config=/var/lib/kubelet/config.yaml\0",
            "/var/lib/kubelet/config.yaml": "shutdownGracePeriod: 120s\nshutdownGracePeriodCriticalPods: 30s\n"}
        files.update(changes or {})
        ids = {n: "%012x" % i for i, n in enumerate(core.HARBOR_STOP_ORDER, 1)}
        def run(argv, timeout=30):
            calls.append(argv)
            if argv == ["/usr/bin/hostname"]: return expected["hostname"]
            if argv[0] == "/usr/sbin/ss": return ""
            if argv[0] == "/usr/bin/busctl":
                return 'a(ssssuu) 1 "shutdown" "kubelet" "fixture grace" "delay" 0 123' if "ListInhibitors" in argv else "t 120000000"
            if "get" in argv and "pods" in argv: return '{"items": []}'
            if "list-units" in argv: return ""
            if argv[:3] == ["/usr/bin/docker", "ps", "-a"]: return "\n".join(c + " " + n for n, c in ids.items())
            if "inspect" in argv: return '{"Running": false, "OOMKilled": false, "ExitCode": 0}'
            if "show" in argv:
                if "kubelet.service" in argv: return "ActiveState=active\nMainPID=123"
                return "ActiveState=inactive\nSubState=dead" if "SubState" in argv else \
                    "LoadState=loaded\nActiveState=active\nSendSIGKILL=no\nTimeoutStopUSec=90s"
            if argv[0] == "/usr/sbin/runuser": return "0"
            return ""
        guest = Guest(name, expected, runner=run, reader=lambda path: files[path])
        return guest, calls, run

    def setUp(self):
        self.uid = patch.object(os, "geteuid", return_value=0, create=True); self.uid.start(); self.addCleanup(self.uid.stop)
        env = patch.dict(os.environ, {"SUDO_USER": "operator", "SUDO_UID": "1000"}); env.start(); self.addCleanup(env.stop)

    def test_wrong_identity_never_stops(self):
        guest, calls, _ = self.make("harbor01", {"/etc/machine-id": "0" * 32})
        with self.assertRaises(core.Stop): guest.probe()
        self.assertFalse(any("stop" in x or "poweroff" in x for x in calls))

    def test_direct_root_or_other_sudo_account_is_blocked(self):
        guest, _, _ = self.make("harbor01")
        with patch.dict(os.environ, {"SUDO_USER": "root", "SUDO_UID": "0"}):
            with self.assertRaises(core.Stop): guest.probe()

    def test_harbor_recovery_manager_cannot_be_raced(self):
        guest, calls, original = self.make("harbor01")
        guest.runner = lambda argv, timeout=30: "harbor-recovery.service enabled" if "list-unit-files" in argv else original(argv, timeout)
        with self.assertRaises(core.Stop): guest.probe()
        self.assertFalse(any("stop" in x or "poweroff" in x for x in calls))

    def test_zero_kubelet_grace_and_short_inhibitor_block(self):
        guest, _, _ = self.make("k8s-worker01", {"/var/lib/kubelet/config.yaml":
            "shutdownGracePeriod: 0s\nshutdownGracePeriodCriticalPods: 0s\n"})
        with self.assertRaises(core.Stop): guest.probe()

    def test_unused_kubelet_config_or_missing_live_inhibitor_block(self):
        guest, _, _ = self.make("k8s-worker01", {"/proc/123/cmdline": "/usr/bin/kubelet\0--config=/other.yaml\0"})
        with self.assertRaises(core.Stop): guest.probe()
        guest, _, original = self.make("k8s-worker01")
        guest.runner = lambda argv, timeout=30: "a(ssssuu) 0" if "ListInhibitors" in argv else original(argv, timeout)
        with self.assertRaises(core.Stop): guest.probe()
        guest, _, original = self.make("k8s-worker01")
        guest.runner = lambda argv, timeout=30: "t 1000000" if argv[0].endswith("busctl") else original(argv, timeout)
        with self.assertRaises(core.Stop): guest.probe()

    def test_control_api_used_only_global_before_quorum_loss(self):
        guest, calls, _ = self.make("k8s-control01")
        initial = guest.probe(global_checks=True)
        self.assertEqual(1, sum("pods" in x for x in calls))
        guest.request(initial, "fixture-round")
        self.assertEqual(1, sum("pods" in x for x in calls))

    def test_application_pods_block_quiesce(self):
        guest, _, original = self.make("k8s-control01")
        pods = {"items": [{"metadata": {"namespace": "app"}, "status": {"phase": "Running"}}]}
        guest.runner = lambda argv, timeout=30: json.dumps(pods) if "pods" in argv else original(argv, timeout)
        with self.assertRaises(core.Stop): guest.probe(global_checks=True)

    def test_active_harbor_clients_block(self):
        guest, _, original = self.make("harbor01")
        guest.runner = lambda argv, timeout=30: "0 0 10.1.93.54:443 10.1.93.23:1234" if argv[0].endswith("ss") else original(argv, timeout)
        with self.assertRaises(core.Stop): guest.probe()

    def test_harbor_logger_last_no_force_no_removal(self):
        guest, calls, _ = self.make("harbor01")
        observed = guest.probe(); calls.clear()
        guest.request(observed, "fixture-round")
        stops = [x for x in calls if x[:2] == ["/usr/bin/docker", "stop"]]
        self.assertEqual(list(observed["harbor_ids"].values()), [x[-1] for x in stops])
        self.assertTrue(all(x[2:4] == ["--timeout", "-1"] for x in stops))
        self.assertEqual(1, sum("poweroff" in x for x in calls))
        self.assertFalse(any(set(x) & {"down", "rm", "prune", "kill", "--force"} for x in calls))

    def test_invalid_operation_before_any_mutation(self):
        guest, calls, _ = self.make("harbor01")
        observed = guest.probe(); calls.clear()
        with self.assertRaises(core.Stop): guest.request(observed, "bad;token")
        self.assertEqual([], calls)

    def test_harbor_timeout_no_next_container_or_poweroff(self):
        guest, calls, original = self.make("harbor01")
        observed = guest.probe(); calls.clear()
        def run(argv, timeout=30):
            if argv[:2] == ["/usr/bin/docker", "stop"]:
                calls.append(argv); raise core.Stop("backend result unknown")
            return original(argv, timeout)
        guest.runner = run
        with self.assertRaises(core.Stop): guest.request(observed, "fixture-round")
        self.assertEqual(1, sum("stop" in x for x in calls))
        self.assertFalse(any("poweroff" in x for x in calls))

    def test_database_clients_or_kill_escalation_block(self):
        for variant in ("clients", "kill"):
            guest, calls, original = self.make("db01")
            def run(argv, timeout=30):
                if variant == "clients" and argv[0].endswith("runuser"): return "1"
                value = original(argv, timeout)
                return value.replace("SendSIGKILL=no", "SendSIGKILL=yes") if variant == "kill" else value
            guest.runner = run
            with self.assertRaises(core.Stop): guest.probe()
            self.assertFalse(any("stop" in x or "poweroff" in x for x in calls))

    def test_database_stop_failure_prevents_poweroff(self):
        guest, calls, original = self.make("db01"); observed = guest.probe()
        def run(argv, timeout=30):
            if "stop" in argv: raise core.Stop("DB failed to stop")
            return original(argv, timeout)
        guest.runner = run
        with self.assertRaises(core.Stop): guest.request(observed, "fixture-round")
        self.assertFalse(any("poweroff" in x for x in calls))


class FakeWS:
    def __init__(self, p, fail=False): self.p, self.fail, self.vmrun, self.off, self.calls = p, fail, "MOCK_VMRun", set(), []
    def identity(self, binding): pass
    def observe(self, p, name):
        r = receipt(p, name)
        if name in core.PHASES["management"] and name not in self.off: r["power_state"] = "POWERED_ON"
        return r
    def running(self): return set()
    def runner(self, argv, timeout=30):
        self.calls.append(argv)
        if "checkToolsState" in argv: return "running"
        if "stop" in argv:
            if self.fail: raise core.Stop("unknown VM backend result")
            name = next(n for n, b in self.p["bindings"]["resources"].items() if b["vmx_path"] in argv)
            self.off.add(name)
        return ""


class WindowsFinalizer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = core.secure_dir(Path(self.temp.name) / "state")
        self.central = core.secure_dir(Path(self.temp.name) / "central")
        self.receipts = core.secure_dir(Path(self.temp.name) / "receipts")
        self.p = plan(); ready(self.p, self.central)
        self.confirm = "POWER_OFF:" + self.p["operation_id"] + ":" + self.p["binding_digest"]
        for phase in list(core.PHASES)[:-1]:
            core.save(self.central / (phase + ".result.json"), {"operation_id": self.p["operation_id"],
                "binding_digest": self.p["binding_digest"], "phase": phase, "status": "PHASE_EXTERNALLY_CONFIRMED_OFF"})
        for name in core.prior_resources("management"):
            core.save(self.receipts / (name + ".json"), receipt(self.p, name))

    def test_only_final_two_soft_stop_in_correct_order(self):
        ws = FakeWS(self.p)
        result = windows.finalize(self.p, self.state, self.receipts, self.central, ws, self.confirm, 1)
        stops = [x for x in ws.calls if "stop" in x]
        self.assertEqual([self.p["bindings"]["resources"][n]["vmx_path"] for n in core.PHASES["management"]], [x[-2] for x in stops])
        self.assertTrue(all(x[-1] == "soft" for x in stops))
        self.assertEqual("ALL_17_EXTERNALLY_CONFIRMED_OFF", result["status"])

    def test_missing_prerequisite_never_stops_management(self):
        (self.receipts / "edge01.json").unlink()
        ws = FakeWS(self.p)
        with self.assertRaises(core.Stop): windows.finalize(self.p, self.state, self.receipts, self.central, ws, self.confirm, 1)
        self.assertEqual([], ws.calls)

    def test_timeout_claim_no_retry_or_gateway_stop(self):
        ws = FakeWS(self.p, fail=True)
        for _ in range(2):
            with self.assertRaises((core.Stop, FileExistsError)):
                windows.finalize(self.p, self.state, self.receipts, self.central, ws, self.confirm, 1)
        self.assertEqual(1, sum("stop" in x for x in ws.calls))
        self.assertFalse((self.state / "mgmt-gw01.intent.json").exists())

    def test_vmrun_list_failure_cannot_be_off_receipt(self):
        ws = windows.Workstation("MOCK", runner=lambda argv, timeout=30: "Total running VMs: 2\nC:/only.vmx")
        with self.assertRaises(core.Stop): ws.running()

    def test_host_pc_power_commands_and_vm_hard_stop_are_forbidden(self):
        ws = windows.Workstation("MOCK_VMRun")
        commands = [["shutdown.exe", "/s"], ["powershell", "Stop-Computer"],
            [ws.vmrun, "-T", "ws", "stop", "C:/VMs/guest.vmx", "hard"],
            [ws.vmrun, "-T", "ws", "reset", "C:/VMs/guest.vmx", "soft"]]
        with patch.object(windows.subprocess, "run") as backend:
            for argv in commands:
                with self.subTest(argv=argv), self.assertRaises(core.Stop): ws._run(argv)
            backend.assert_not_called()

    def test_gateway_allows_only_explicit_guest_soft_stop(self):
        ws = windows.Workstation("MOCK_VMRun")
        target = str(Path(self.temp.name) / "guest.vmx")
        argv = [ws.vmrun, "-T", "ws", "stop", target, "soft"]
        with patch.object(windows.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout="", stderr="")) as backend:
            ws._run(argv)
            self.assertEqual(argv, backend.call_args.args[0])

    def test_suspended_or_crashed_vm_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            p = plan(); name = "edge01"; b = p["bindings"]["resources"][name]
            vmx = Path(temp) / "vm.vmx"; b["vmx_path"] = str(vmx)
            vmx.write_text('uuid.bios = "' + b["vmx_uuid"] + '"\ncheckpoint.vmState = ""\n')
            (Path(temp) / "vmware.log").write_text('Setting cleanShutdown = "TRUE"\nTransitioned vmx/execState/val to poweredOff\nVMX exit (0).\n')
            ws = windows.Workstation("MOCK", runner=lambda argv, timeout=30: "Total running VMs: 0")
            self.assertEqual("POWERED_OFF", ws.observe(p, name)["power_state"])
            (Path(temp) / "vm.vmss").write_bytes(b"SYNTHETIC_SUSPEND")
            self.assertEqual("UNKNOWN", ws.observe(p, name)["power_state"])
            (Path(temp) / "vm.vmss").unlink()
            (Path(temp) / "vmware.log").write_text("VMX exit (1).\n")
            self.assertEqual("UNKNOWN", ws.observe(p, name)["power_state"])


class ModuleContract(unittest.TestCase):
    def invoke(self, check_mode, confirm=""):
        class Finished(BaseException):
            def __init__(self, value): self.value = value
        p = plan()
        calls = []
        class FakeModule:
            def __init__(self, **kwargs):
                self.check_mode = check_mode
                self.params = {"plan": p, "resource": "edge01", "action": "request", "confirm": confirm,
                               "observed": {"boot_id": BOOT}}
            def exit_json(self, **kwargs): raise Finished(kwargs)
            def fail_json(self, **kwargs): raise Finished(dict(kwargs, failed=True))
        class FakeGuest:
            def __init__(self, *args): pass
            def probe(self, **kwargs): calls.append("read"); return {"boot_id": BOOT}
            def request(self, *args): calls.append("mutate"); raise AssertionError("Must not mutate")
        basic = types.ModuleType("ansible.module_utils.basic"); basic.AnsibleModule = FakeModule
        guest = types.ModuleType("ansible.module_utils.fds_shutdown_guest"); guest.Guest = FakeGuest
        modules = {"ansible": types.ModuleType("ansible"), "ansible.module_utils": types.ModuleType("ansible.module_utils"),
            "ansible.module_utils.basic": basic, "ansible.module_utils.fds_shutdown_core": core,
            "ansible.module_utils.fds_shutdown_guest": guest}
        with patch.dict(sys.modules, modules):
            module = load("shutdown_module", "library/fds_phase1_shutdown.py")
            try: module.main()
            except Finished as result: return result.value, calls
        raise AssertionError("Module must terminate")

    def test_check_mode_request_is_read_only_without_claim(self):
        result, calls = self.invoke(True)
        self.assertEqual("READ_ONLY", result["status"])
        self.assertFalse(result["changed"])
        self.assertEqual(["read"], calls)

    def test_unconfirmed_request_is_blocked_before_claim(self):
        result, calls = self.invoke(False, "yes")
        self.assertTrue(result["failed"])
        self.assertEqual(["read"], calls)


class AnsiblePackaging(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("ansible"), "Ansible unavailable; run in both pinned Linux engines")
    def test_custom_module_dependency_bundle_without_executing_it(self):
        from ansible.executor.module_common import modify_module
        from ansible.parsing.dataloader import DataLoader
        from ansible.template import Templar
        from ansible.plugins.loader import init_plugin_loader, module_utils_loader
        init_plugin_loader()
        module_utils_loader.add_directory(str(ROOT / "module_utils"))
        built = modify_module(module_name="fds_phase1_shutdown", module_path=str(ROOT / "library/fds_phase1_shutdown.py"),
            module_args={"plan": {}, "resource": "edge01", "action": "preflight"}, templar=Templar(loader=DataLoader()),
            task_vars={"ansible_python_interpreter": "/usr/bin/python3"})
        source, style = (built.b_module_data, built.module_style) if hasattr(built, "b_module_data") else built[:2]
        self.assertEqual("new", style)
        # 2.16/2.21 use different wrapper variable names. Inspect literal ZIP
        # bytes, without evaluating or executing the generated wrapper.
        archives = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)) or len(node.value) < 100:
                continue
            try:
                raw = node.value.encode("ascii") if isinstance(node.value, str) else node.value
                data = base64.b64decode(raw, validate=True)
            except (ValueError, UnicodeError):
                continue
            if zipfile.is_zipfile(io.BytesIO(data)): archives.append(data)
        self.assertEqual(1, len(archives))
        with zipfile.ZipFile(io.BytesIO(archives[0])) as archive:
            for name in ("fds_shutdown_core", "fds_shutdown_guest"):
                self.assertIn("ansible/module_utils/" + name + ".py", archive.namelist())


if __name__ == "__main__": unittest.main()
