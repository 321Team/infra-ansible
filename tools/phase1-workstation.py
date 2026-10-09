#!/usr/bin/env python3
"""Windows VM receipts; explicit normal soft stop of the final two management VMs."""
import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "module_utils"))
from fds_shutdown_core import (FLEET, PHASES, SCHEMA, Stop, prior_resources, private_json,
    receipt_for, require, save, secure_dir, utc, validate_plan)


def normal(path):
    return ntpath.normpath(str(path)).replace("\\", "/").casefold()


class Workstation:
    def __init__(self, vmrun, runner=None):
        self.vmrun = str(vmrun)
        self.runner = runner or self._run

    def _run(self, argv, timeout=30):
        # Host PC must stay on for Remote Desktop. This boundary accepts only
        # VM inspection and a guest VM soft stop; never a shell/host power API.
        require(argv[:3] == [self.vmrun, "-T", "ws"], "Only VMware Workstation guest commands are permitted")
        valid = (len(argv) == 4 and argv[3] == "list") or (len(argv) == 5 and argv[3] == "checkToolsState") or \
                (len(argv) == 6 and argv[3] == "stop" and argv[5] == "soft")
        require(valid, "Host power actions, force stops and other VMware actions are forbidden")
        if len(argv) > 4:
            require(Path(argv[4]).is_absolute() and argv[4].lower().endswith(".vmx"), "Explicit guest VMX target required")
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Stop("VMware command timed out; result UNKNOWN; never retry/hard-stop")
        require(result.returncode == 0, "VMware command failed; result UNKNOWN")
        return result.stdout.strip()

    def running(self):
        rows = self.runner([self.vmrun, "-T", "ws", "list"]).splitlines()
        require(rows and re.fullmatch(r"Total running VMs: [0-9]+", rows[0]), "Unexpected VMware list format")
        count = int(rows[0].rsplit(" ", 1)[1])
        paths = [normal(x) for x in rows[1:]]
        require(count == len(paths) and count == len(set(paths)), "Incomplete/duplicate VMware running list")
        return set(paths)

    @staticmethod
    def identity(binding):
        path = Path(binding["vmx_path"])
        require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)), "VMX missing/linked")
        text = path.read_text(encoding="utf-8")
        ids = re.findall(r'^uuid\.bios\s*=\s*"([^"]+)"\s*$', text, re.M)
        require(ids == [binding["vmx_uuid"]], "VMX BIOS UUID changed; never use a copied VM")
        return text

    def observe(self, plan, name):
        binding = plan["bindings"]["resources"][name]
        text = self.identity(binding)
        running = self.running()
        off = normal(binding["vmx_path"]) not in running
        clean, suspended_absent = False, False
        log_hash = None
        if off:
            folder = Path(binding["vmx_path"]).parent
            checkpoint = re.findall(r'^checkpoint\.vmState\s*=\s*"([^"]*)"\s*$', text, re.M)
            suspended_absent = not list(folder.glob("*.vmss")) and all(not x for x in checkpoint)
            log = folder / "vmware.log"
            if log.is_file() and not log.is_symlink():
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 262144))
                    tail = stream.read()
                log_hash = hashlib.sha256(tail).hexdigest()
                lines = tail.decode("utf-8", errors="replace")
                exits = re.findall(r"VMX exit \(([0-9]+)\)", lines)
                clean = bool(exits and exits[-1] == "0" and
                    'Setting cleanShutdown = "TRUE"' in lines and
                    "Transitioned vmx/execState/val to poweredOff" in lines)
        # Recheck both UUID and current list after reading the clean-exit log.
        self.identity(binding)
        still_off = normal(binding["vmx_path"]) not in self.running()
        return {"schema": SCHEMA, "operation_id": plan["operation_id"], "binding_digest": plan["binding_digest"],
            "resource": name, "physical_host": binding["physical_host"], "vmx_path": binding["vmx_path"],
            "vmx_uuid": binding["vmx_uuid"], "observed_at": utc(), "observer": "vmrun-list",
            "power_state": "POWERED_OFF" if off and still_off and clean and suspended_absent else
                           "POWERED_ON" if not still_off else "UNKNOWN",
            "clean_vmx_exit": clean, "suspend_state_absent": suspended_absent, "vmware_log_tail_sha256": log_hash}


def observe_host(plan, physical_host, receipts, ws):
    records = []
    for name, binding in plan["bindings"]["resources"].items():
        if binding["physical_host"] != physical_host:
            continue
        try:
            record = ws.observe(plan, name)
        except Exception as exc:
            record = {"schema": SCHEMA, "operation_id": plan["operation_id"], "binding_digest": plan["binding_digest"],
                "resource": name, "observed_at": utc(), "power_state": "UNKNOWN", "error_type": type(exc).__name__}
        # Replace an earlier OFF receipt on ON/UNKNOWN, rather than leave an
        # apparently fresh success after restart/observer failure.
        save(receipts / (name + ".json"), record)
        records.append({"resource": name, "power_state": record["power_state"]})
    managed = {normal(b["vmx_path"]) for b in plan["bindings"]["resources"].values() if b["physical_host"] == physical_host}
    unmanaged = sorted(ws.running() - managed)
    return {"resources": records, "unmanaged_running_vms": unmanaged,
            "physical_pc_shutdown": "NOT_IMPLEMENTED"}


def finalize(plan, state, receipts, central, ws, confirm, timeout=300):
    require(confirm == "POWER_OFF:" + plan["operation_id"] + ":" + plan["binding_digest"], "Explicit confirmation mismatch")
    ready = private_json(central / "preflight.json")
    require(ready.get("operation_id") == plan["operation_id"] and ready.get("binding_digest") == plan["binding_digest"] and
            ready.get("status") == "READY_FOR_EXPLICIT_PHASE" and set(ready["observations"]) == set(FLEET), "Central preflight handoff required")
    for phase in list(PHASES)[:-1]:
        record = private_json(central / (phase + ".result.json"))
        require(record.get("operation_id") == plan["operation_id"] and record.get("binding_digest") == plan["binding_digest"] and
                record.get("phase") == phase and record.get("status") == "PHASE_EXTERNALLY_CONFIRMED_OFF",
                "Central phase handoff incomplete: " + phase)
    for name in PHASES["management"]:
        # Revalidate all prerequisites before each management VM stop.
        for previous in prior_resources("management") + PHASES["management"][:PHASES["management"].index(name)]:
            receipt_for(plan, previous, private_json(receipts / (previous + ".json")))
        current = ws.observe(plan, name)
        save(receipts / (name + ".json"), current)
        if current["power_state"] == "POWERED_OFF":
            continue
        require(current["power_state"] == "POWERED_ON", "Management power state UNKNOWN; HOLD")
        binding = plan["bindings"]["resources"][name]
        require(ready["observations"][name].get("status") != "EXTERNALLY_CONFIRMED_OFF", "Previously off management VM restarted")
        tools = ws.runner([ws.vmrun, "-T", "ws", "checkToolsState", binding["vmx_path"]])
        require(tools == "running", "VMware Tools unavailable; no hard fallback")
        # O_EXCL claims in the shared round directory also guard concurrent
        # finalizers. Preserve after failure/deadline; never resubmit blindly.
        save(state / (name + ".intent.json"), {"resource": name, "operation_id": plan["operation_id"],
            "binding_digest": plan["binding_digest"], "claimed_at": utc(), "method": "vmrun-stop-soft"}, exclusive=True)
        ws.identity(binding)
        ws.runner([ws.vmrun, "-T", "ws", "stop", binding["vmx_path"], "soft"], timeout=timeout)
        deadline = time.monotonic() + timeout
        while True:
            receipt = ws.observe(plan, name)
            save(receipts / (name + ".json"), receipt)
            if receipt["power_state"] == "POWERED_OFF":
                receipt_for(plan, name, receipt)
                save(state / (name + ".result.json"), receipt)
                break
            require(time.monotonic() < deadline, "Management Powered Off deadline exceeded; HOLD")
            time.sleep(2)
    result = observe_host(plan, "server01", receipts, ws)
    # Every host observer must still be publishing; do not claim fleet success
    # from phase reports or stale receipts alone.
    for name in FLEET:
        receipt_for(plan, name, private_json(receipts / (name + ".json")))
    result.update(schema=SCHEMA, operation_id=plan["operation_id"], binding_digest=plan["binding_digest"],
                  status="ALL_17_EXTERNALLY_CONFIRMED_OFF", finished_at=utc())
    save(state / "FINAL_RESULT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["observe", "finalize"])
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--physical-host", required=True, choices=sorted({x["physical_host"] for x in FLEET.values()}))
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--vmrun", type=Path, default=Path(r"C:\Program Files\VMware\VMware Workstation\vmrun.exe"))
    parser.add_argument("--watch-seconds", type=int, default=0)
    parser.add_argument("--export", type=Path, help="Private receipt array for approved SSH stdin transfer")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--central-handoff", type=Path)
    parser.add_argument("--confirm")
    parser.add_argument("--wait-seconds", type=int, default=300)
    args = parser.parse_args()
    try:
        require(os.name == "nt", "Run on the VM's Windows Workstation host")
        require(args.vmrun.is_absolute() and args.vmrun.is_file() and args.vmrun.name.casefold() == "vmrun.exe",
                "Installed absolute vmrun.exe path required")
        plan = validate_plan(private_json(args.plan))
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        require(sha == plan["source_commit"] and not
                subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip(),
                "Use the same clean reviewed source SHA as the controller")
        require(os.environ.get("COMPUTERNAME", "").casefold() ==
                plan["bindings"]["workstation_names"][args.physical_host].casefold(), "Wrong physical Windows host")
        receipts = secure_dir(args.receipts)
        ws = Workstation(args.vmrun)
        if args.command == "observe":
            require(0 <= args.watch_seconds <= 3600, "Watch limit must be 0..3600 seconds")
            deadline = time.monotonic() + args.watch_seconds
            while True:
                result = observe_host(plan, args.physical_host, receipts, ws)
                if args.export:
                    require(args.export.parent.is_dir(), "Export parent must be an approved private directory")
                    save(args.export, [private_json(receipts / (x["resource"] + ".json")) for x in result["resources"]])
                print(json.dumps(result, indent=2), flush=True)
                if time.monotonic() >= deadline:
                    return 0 if all(x["power_state"] != "UNKNOWN" for x in result["resources"]) else 2
                time.sleep(5)
        require(args.physical_host == "server01" and args.state and args.central_handoff and args.confirm,
                "Finalization requires server01 and private state/central handoff/confirmation")
        require(1 <= args.wait_seconds <= 900 and args.watch_seconds == 0, "Invalid finalizer limits")
        state = secure_dir(args.state)
        require(not state.is_relative_to(ROOT), "Private state outside checkout required")
        result = finalize(plan, state, receipts, args.central_handoff, ws, args.confirm, args.wait_seconds)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Stop) else type(exc).__name__
        print("HOLD: " + reason + "; preserve claims; no automatic retry", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
