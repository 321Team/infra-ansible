#!/usr/bin/env python3
"""Offline plan / read-only preflight / explicitly confirmed, one-phase stop."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "module_utils"))
from fds_shutdown_core import (FLEET, PHASES, SCHEMA, Stop, age, digest, prior_resources,
    private_json, receipt_for, require, save, secure_dir, utc, validate_bindings, validate_plan, wait_receipt)


@contextlib.contextmanager
def locked(state):
    require(os.name == "posix", "Run the coordinator on the Linux Ansible controller")
    import fcntl
    path = state / "coordinator.lock"
    require(not path.is_symlink(), "Invalid lock path")
    with open(path, "a", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Stop("Another coordinator is running")
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def clean_source():
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(re.fullmatch(r"[0-9a-f]{40}", sha), "Full source SHA required")
    require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip(),
            "Use a clean reviewed checkout; private inputs/state belong outside it")
    return sha


class Ansible:
    def __init__(self, engine_dir, version, ssh_key_file, ask_become=False):
        self.engine = Path(engine_dir)
        require(self.engine.is_absolute() and version in {"2.16.19", "2.21.3"}, "Explicit pinned engine required")
        self.version, self.ask_become = version, ask_become
        self.key = self.key_path(ssh_key_file)
        text = subprocess.check_output([str(self.engine / "ansible-playbook"), "--version"], text=True)
        require(text.splitlines()[0] == "ansible-playbook [core " + version + "]", "Engine version mismatch")

    @staticmethod
    def key_path(value):
        path = Path(value)
        require(path.is_absolute() and path.is_file() and not path.is_symlink(), "Approved existing SSH key path required")
        info = path.stat()
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, "SSH key must be operator-owned and private")
        return path

    def call(self, plan, name, action, state, observed=None):
        binding = plan["bindings"]["resources"][name]
        key = self.key_path(binding.get("ssh_key_file") or self.key)
        folder = secure_dir(state / (action + "-" + name + "-" + utc().replace(":", "-")))
        inventory = {"all": {"children": {"phase1_shutdown_target": {"hosts": {name: {
            "ansible_host": binding["ip"], "ansible_user": binding["ssh_user"],
            "ansible_python_interpreter": "/usr/bin/python3",
            "ansible_ssh_private_key_file": str(key),
            "ansible_ssh_common_args": "-o StrictHostKeyChecking=yes -o BatchMode=yes"}}}}}}
        save(folder / "inventory.json", inventory)
        params = {"shutdown_plan": plan, "shutdown_resource": name, "shutdown_action": action,
            "shutdown_observed": observed or {}, "shutdown_result_path": str(folder / "result.json"),
            "shutdown_confirm": "POWER_OFF:" + plan["operation_id"] + ":" + plan["binding_digest"] if action == "request" else ""}
        save(folder / "inputs.json", params)
        command = [str(self.engine / "ansible-playbook"), "-i", str(folder / "inventory.json"),
            "-e", "@" + str(folder / "inputs.json"), str(ROOT / "playbooks/phase1-safe-shutdown.yml")]
        if self.ask_become:
            command.append("--ask-become-pass")
        env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / "ansible.cfg"), ANSIBLE_SSH_USETTY="false")
        # Do not inherit ambient Ansible passwords, arbitrary callback plugins,
        # inventory/connection or disabled host-key settings.
        env = {k: v for k, v in env.items() if not k.startswith("ANSIBLE_") or
               k in {"ANSIBLE_CONFIG", "ANSIBLE_SSH_USETTY"}}
        result = subprocess.run(command, cwd=ROOT, env=env, timeout=1800)
        save(folder / "invocation.json", {"action": action, "resource": name, "rc": result.returncode,
            "finished_at": utc(), "engine": self.version, "source_commit": plan["source_commit"]})
        require(result.returncode == 0 and (folder / "result.json").is_file(),
                "Ansible failed/lost response: preserve evidence; NOT a power-off confirmation")
        return private_json(folder / "result.json")


def already_off(plan, name, receipts):
    path = receipts / (name + ".json")
    if not path.is_file():
        return False
    try:
        receipt_for(plan, name, private_json(path))
        return True
    except (Stop, KeyError, ValueError):
        return False


def receive(plan, receipts, records):
    """Approved SSH stdin transfer; no new mount/account/share is created."""
    require(isinstance(records, list) and 1 <= len(records) <= 17, "Receipt array required")
    names = set()
    for record in records:
        name = record.get("resource")
        require(name in FLEET and name not in names, "Unknown/duplicate receipt resource")
        names.add(name)
        require(record.get("schema") == SCHEMA and record.get("operation_id") == plan["operation_id"] and
                record.get("binding_digest") == plan["binding_digest"], "Receipt round mismatch")
        require(0 <= age(record["observed_at"]) <= 300, "Incoming receipt expired/future")
        require(record.get("power_state") in {"POWERED_OFF", "POWERED_ON", "UNKNOWN"}, "Invalid power state")
        if record["power_state"] == "POWERED_OFF":
            receipt_for(plan, name, record)
        path = receipts / (name + ".json")
        if path.exists():
            old = private_json(path)
            require(age(record["observed_at"]) <= age(old["observed_at"]), "Do not overwrite a newer observation")
    # Validate the entire array before writing. Each file is atomic; an I/O
    # failure can leave a partial transfer and must not be reported complete.
    for record in records:
        path = receipts / (record["resource"] + ".json")
        save(path, record)
    return {"status": "RECEIPTS_IMPORTED_ONLY", "resources": sorted(names)}


def preflight(plan, state, receipts, adapter):
    require(not list(state.glob("*.intent.json")), "Mutations already claimed; do not refresh global preflight mid-shutdown")
    observations = {}
    for name in FLEET:
        if already_off(plan, name, receipts):
            observations[name] = {"status": "EXTERNALLY_CONFIRMED_OFF"}
        else:
            result = adapter.call(plan, name, "preflight", state)
            require(result.get("status") == "READ_ONLY", "Unexpected preflight status")
            observations[name] = result["observation"]
    record = {"schema": SCHEMA, "operation_id": plan["operation_id"], "binding_digest": plan["binding_digest"],
              "observed_at": utc(), "observations": observations, "status": "READY_FOR_EXPLICIT_PHASE"}
    save(state / "preflight.json", record)
    return record


def execute_phase(plan, phase, state, receipts, adapter, confirm, timeout=300):
    require(phase in PHASES and phase != "management", "Management phase is Windows-only")
    require(confirm == "POWER_OFF:" + plan["operation_id"] + ":" + plan["binding_digest"], "Confirmation does not match plan")
    ready = private_json(state / "preflight.json")
    require(ready.get("operation_id") == plan["operation_id"] and ready.get("binding_digest") == plan["binding_digest"] and
            ready.get("status") == "READY_FOR_EXPLICIT_PHASE" and set(ready["observations"]) == set(FLEET), "Full fleet preflight required")
    if not list(state.glob("*.intent.json")):
        require(0 <= age(ready["observed_at"]) <= 300, "Initial full-fleet preflight expired")
    results = []
    for name in PHASES[phase]:
        for previous in prior_resources(phase) + PHASES[phase][:PHASES[phase].index(name)]:
            receipt_for(plan, previous, private_json(receipts / (previous + ".json")))
        if already_off(plan, name, receipts):
            results.append({"resource": name, "status": "EXTERNALLY_CONFIRMED_OFF"})
            continue
        require(ready["observations"][name].get("status") != "EXTERNALLY_CONFIRMED_OFF",
                "A previously off VM is running/unknown; new review required")
        # Read-only repeat before exclusive durable claim; guest repeats once
        # more before normal stop. Claims are NEVER automatically removed.
        fresh = adapter.call(plan, name, "inspect", state)["observation"]
        require(fresh["boot_id"] == ready["observations"][name]["boot_id"], "Guest boot changed since full preflight")
        claim = state / (name + ".intent.json")
        save(claim, {"operation_id": plan["operation_id"], "binding_digest": plan["binding_digest"],
            "claimed_at": utc(), "resource": name, "source_commit": plan["source_commit"]}, exclusive=True)
        result = adapter.call(plan, name, "request", state, fresh)
        require(result.get("status") == "NORMAL_SHUTDOWN_SCHEDULED", "Shutdown was not acknowledged; HOLD")
        receipt = wait_receipt(plan, name, receipts, timeout)
        record = {"resource": name, "status": "EXTERNALLY_CONFIRMED_OFF", "receipt": receipt}
        save(state / (name + ".result.json"), record)
        results.append(record)
    record = {"schema": SCHEMA, "operation_id": plan["operation_id"], "binding_digest": plan["binding_digest"],
        "phase": phase, "finished_at": utc(), "status": "PHASE_EXTERNALLY_CONFIRMED_OFF", "results": results}
    save(state / (phase + ".result.json"), record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="Offline only; never contacts servers")
    p.add_argument("--bindings", required=True, type=Path)
    p.add_argument("--operation-id", required=True)
    p.add_argument("--state", required=True, type=Path)
    p = sub.add_parser("receive", help="Read bounded JSON receipt array from stdin; no server calls")
    p.add_argument("--state", required=True, type=Path)
    p.add_argument("--receipts", required=True, type=Path)
    for action in ("preflight", "execute"):
        p = sub.add_parser(action)
        p.add_argument("--state", required=True, type=Path)
        p.add_argument("--receipts", required=True, type=Path)
        p.add_argument("--engine-dir", required=True)
        p.add_argument("--engine-version", required=True, choices=["2.16.19", "2.21.3"])
        p.add_argument("--ssh-key-file", required=True, type=Path, help="Existing approved key, never copied/read into evidence")
        p.add_argument("--ask-become-pass", action="store_true")
        if action == "execute":
            p.add_argument("--phase", required=True, choices=list(PHASES)[:-1])
            p.add_argument("--confirm", required=True)
            p.add_argument("--wait-seconds", type=int, default=300)
    args = parser.parse_args()
    try:
        state = secure_dir(args.state)
        require(not state.is_relative_to(ROOT), "Private state must be outside checkout")
        if args.command == "receive":
            # Receipt imports must continue while execute holds its coordinator
            # lock waiting for external confirmation. Use a separate lock.
            sha = clean_source()
            plan = validate_plan(private_json(state / "plan.json"))
            require(plan["source_commit"] == sha, "Source changed since plan")
            receipts = secure_dir(args.receipts)
            with locked(receipts):
                payload = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
                require(len(payload) <= 2 * 1024 * 1024, "Receipt transfer too large")
                print(json.dumps(receive(plan, receipts, json.loads(payload)), indent=2))
            return 0
        with locked(state):
            sha = clean_source()
            if args.command == "plan":
                bindings = validate_bindings(private_json(args.bindings))
                plan = {"schema": SCHEMA, "operation_id": args.operation_id, "source_commit": sha, "created_at": utc(),
                    "binding_digest": digest(bindings), "bindings": bindings, "fleet": FLEET, "phases": PHASES}
                validate_plan(plan)
                save(state / "plan.json", plan, exclusive=True)
                print(json.dumps({"status": "OFFLINE_PLAN_ONLY", "fleet": PHASES,
                    "confirm": "POWER_OFF:" + plan["operation_id"] + ":" + plan["binding_digest"]}, indent=2))
                return 0
            plan = validate_plan(private_json(state / "plan.json"))
            require(plan["source_commit"] == sha, "Source changed since plan")
            receipts = secure_dir(args.receipts)
            adapter = Ansible(args.engine_dir, args.engine_version, args.ssh_key_file, args.ask_become_pass)
            if args.command == "preflight":
                record = preflight(plan, state, receipts, adapter)
            else:
                require(1 <= args.wait_seconds <= 900, "Wait limit must be 1..900 seconds")
                record = execute_phase(plan, args.phase, state, receipts, adapter, args.confirm, args.wait_seconds)
            print(json.dumps({k: v for k, v in record.items() if k not in {"observations", "results"}}, indent=2))
            return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Stop) else type(exc).__name__
        print("HOLD: " + reason + "; preserve state; no automatic retry", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
