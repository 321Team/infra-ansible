#!/usr/bin/env python3
"""Diagnose, gate and optionally apply one reviewed NTP rollout; retain failures."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

CHANGE_ID = "CR-P1-NTP-01-01"
HOSTS = {"k8s-control01": "10.1.93.102", "k8s-control02": "10.1.93.103",
         "k8s-control03": "10.1.93.104", "k8s-worker01": "10.1.93.105",
         "k8s-worker02": "10.1.93.107", "k8s-worker03": "10.1.93.108"}
SOURCE = "k8s-control01"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_tool(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: %s" % key)
        result[key] = value
    return result


def read_json_bytes(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError("Unsafe input/evidence file: %s" % path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("Input changed while opening")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(1048577)
        if len(data) > 1048576:
            raise ValueError("Input/evidence exceeds the 1 MiB limit")
    finally:
        os.close(descriptor)
    return data, json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    path.chmod(0o600)


class RolloutInterrupted(Exception):
    pass


class Rollout:
    def __init__(self, args, repo_root=None):
        self.args = args
        self.repo = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
        self.root = None
        self.lock_fd = None
        self.records = []
        self.summary = {"schema_version": 1, "change_id": CHANGE_ID, "status": "INITIALIZING",
                        "apply_requested": bool(args.apply), "source_applied": False,
                        "source_phase_started": False,
                        "clients_started": False, "runtime_acceptance": "REVIEW_REQUIRED"}
        self.tree = None
        self.input = None
        self.input_hash = None
        self.vars_hash = None
        self.controller_ready = False
        self.source_bound = False
        self.active_process = None
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("ANSIBLE_", "PYTHON", "CR_NTP_", "GIT_"))}
        self.env.update(LANG="C.UTF-8", LC_ALL="C.UTF-8", ANSIBLE_NOCOLOR="1",
                        ANSIBLE_CONFIG=str(self.repo / "ansible.cfg"))
        if os.environ.get("ANSIBLE_PRIVATE_KEY_FILE"):
            self.env["ANSIBLE_PRIVATE_KEY_FILE"] = os.environ["ANSIBLE_PRIVATE_KEY_FILE"]

    def create_evidence(self):
        parent = Path(self.args.evidence_parent or pwd.getpwuid(os.geteuid()).pw_dir).resolve()
        if not parent.is_dir():
            raise ValueError("Evidence parent must be an existing private directory")
        for directory in [parent] + list(parent.parents):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()):
                raise ValueError("Unsafe evidence ancestor directory")
            if stat.S_IMODE(info.st_mode) & 0o022 and not info.st_mode & stat.S_ISVTX:
                raise ValueError("Evidence ancestor directory permits unsafe replacement")
        if parent == self.repo or self.repo in parent.parents:
            raise ValueError("Evidence must be outside the source checkout")
        self.root = Path(tempfile.mkdtemp(prefix="ansible-ntp-rollout-", dir=parent))
        self.root.chmod(0o700)
        for name in ("controller", "gates", "wrapper"):
            (self.root / name).mkdir(mode=0o700)
        self.summary["run_id"] = self.root.name
        self.summary["started_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.summary["source_checkout"] = str(self.repo)

    @staticmethod
    def stop_process(process):
        # A wrapper may leave descendants after its leader exits. Signal the
        # exact private process group, then reap the leader before packaging.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)

    def run_command(self, phase, argv, timeout):
        print("STAGE=%s" % phase, flush=True)
        stem = "%02d-%s" % (len(self.records) + 1, phase)
        stdout_path = self.root / "controller" / (stem + ".stdout.log")
        stderr_path = self.root / "controller" / (stem + ".stderr.log")
        print("STDOUT_LOG=%s\nSTDERR_LOG=%s" % (stdout_path, stderr_path), flush=True)
        started = time.monotonic()
        timed_out = False
        process = None
        interrupted = False
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(argv, cwd=self.repo, env=self.env, stdout=stdout, stderr=stderr,
                                           start_new_session=True,
                                           pass_fds=(self.lock_fd,) if self.lock_fd is not None else ())
                self.active_process = process
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self.stop_process(process)
                except BaseException:
                    interrupted = True
                    self.stop_process(process)
                    raise
        finally:
            self.active_process = None
            record = {"phase": phase, "argv": [str(item) for item in argv],
                      "returncode": process.returncode if process is not None else None,
                      "timed_out": timed_out, "interrupted": interrupted,
                      "elapsed_seconds": round(time.monotonic() - started, 3),
                      "stdout_file": str(stdout_path.relative_to(self.root)),
                      "stderr_file": str(stderr_path.relative_to(self.root))}
            self.records.append(record)
            write_json(self.root / "COMMANDS.json", self.records)
        return dict(record, stdout=stdout_path.read_text(errors="replace"),
                    stderr=stderr_path.read_text(errors="replace"))

    def command_ok(self, phase, argv, timeout=30):
        result = self.run_command(phase, argv, timeout)
        if result["returncode"] != 0 or result.get("timed_out"):
            raise ValueError("%s failed (rc=%s, timeout=%s); see retained logs" %
                             (phase, result["returncode"], result.get("timed_out")))
        return result

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo)] + list(args), env=self.env,
                                capture_output=True, text=True, timeout=15, check=False)
        if result.returncode:
            raise ValueError("Git source verification failed")
        return result.stdout.strip()

    def assert_source(self):
        head = self.git("rev-parse", "--verify", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        dirty = self.git("status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none")
        if dirty or head != self.input["reviewed_source_sha"] or (self.tree is not None and tree != self.tree):
            if self.root:
                write_json(self.root / "SOURCE_BINDING_INVALID.json", {"observed_head": head,
                           "observed_tree": tree, "dirty": bool(dirty)})
            raise ValueError("Checkout HEAD/tree/clean state differs from the reviewed source")
        self.tree = tree
        return {"head": head, "tree": tree, "clean": True}

    def verify_inputs(self):
        raw, value = read_json_bytes(self.root / "RUNTIME_INPUT.json")
        variables, parsed = read_json_bytes(self.root / "ANSIBLE_VARS.json")
        if sha256(raw) != self.input_hash or sha256(variables) != self.vars_hash or value != self.input:
            raise ValueError("Bound runtime inputs changed during execution")
        return parsed

    def load_input(self):
        raw, value = read_json_bytes(Path(self.args.runtime_input))
        expected = {"reviewed_source_sha", "public_upstreams", "source_policy_ref", "network_policy_ref", "recovery_ref"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Runtime input must contain exactly the documented five fields")
        if not isinstance(value["reviewed_source_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["reviewed_source_sha"]):
            raise ValueError("reviewed_source_sha must be the full reviewed and merged commit")
        for key in ("source_policy_ref", "network_policy_ref", "recovery_ref"):
            if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 2048:
                raise ValueError("Missing or invalid existing decision/evidence reference: %s" % key)
            if re.match(r"^(?:PENDING|UNCONFIRMED|TODO|TBD|NOT[ _]RUN|REPLACE(?:_ME)?|CHANGE_ME)(?:\b|_)", value[key].strip(), re.IGNORECASE) or value[key].strip().startswith("<"):
                raise ValueError("Unresolved placeholder is not an existing decision/evidence reference: %s" % key)
        self.input = value
        # Check provenance before importing any repository helper code.
        self.assert_source()
        renderer = load_tool("fds_ntp_egress_contract", self.repo / "tools/render-ntp-egress.py")
        renderer.public_upstreams(value["public_upstreams"])
        self.input_hash = sha256(raw)
        (self.root / "RUNTIME_INPUT.json").write_bytes(raw)
        (self.root / "RUNTIME_INPUT.json").chmod(0o400)
        variables = {"cr_ntp_migrate_main": True, "cr_ntp_source_upstreams": value["public_upstreams"],
                     "cr_ntp_probe_evidence_dir": str(self.root / "gates"),
                     "cr_ntp_probe_run_id": self.summary["run_id"],
                     "cr_ntp_probe_source_head": value["reviewed_source_sha"],
                     "cr_ntp_probe_input_sha256": self.input_hash}
        write_json(self.root / "ANSIBLE_VARS.json", variables)
        (self.root / "ANSIBLE_VARS.json").chmod(0o400)
        self.vars_hash = sha256((self.root / "ANSIBLE_VARS.json").read_bytes())
        self.summary.update(input_sha256=self.input_hash, ansible_vars_sha256=self.vars_hash,
                            public_upstreams=value["public_upstreams"], reviewed_source_sha=value["reviewed_source_sha"])
        self.env.update(CR_NTP_MIGRATE_MAIN="1", CR_NTP_RUNTIME_VARS_FILE=str(self.root / "ANSIBLE_VARS.json"),
                        CR_EVIDENCE_DIR=str(self.root / "wrapper"))

    def prepare(self):
        if self.command_ok("identity-host", ["hostnamectl", "--static"])["stdout"].strip() != "ansible01":
            raise ValueError("Run only on ansible01")
        if self.command_ok("identity-user", ["id", "-un"])["stdout"].strip() != "server01_ansible":
            raise ValueError("Run only as server01_ansible")
        key = self.env.get("ANSIBLE_PRIVATE_KEY_FILE")
        if not key or not os.path.isfile(key) or not os.access(key, os.R_OK):
            raise ValueError("Set ANSIBLE_PRIVATE_KEY_FILE to the existing readable key path")
        if self.command_ok("locale", ["locale", "charmap"])["stdout"].strip().upper().replace("-", "") != "UTF8":
            raise ValueError("Controller C.UTF-8 locale is unavailable")
        self.load_input()
        source = self.assert_source()
        write_json(self.root / "SOURCE.json", source)
        self.source_bound = True
        lock = load_tool("fds_ntp_workflow_lock", self.repo / "tools/ntp-workflow-lock.py")
        self.lock_fd = lock.acquire_lock(os.environ.get(lock.FD_ENV))
        self.env[lock.FD_ENV] = str(self.lock_fd)
        for label, executable in (("ansible", "ansible"), ("playbook", "ansible-playbook"), ("inventory", "ansible-inventory")):
            output = self.command_ok("engine-" + label, [executable, "--version"])["stdout"]
            if not re.search(r"\[core 2[.]16[.]19\]", output.splitlines()[0] if output else ""):
                raise ValueError("All Ansible CLI tools must use the existing core 2.16.19 environment")
        self.controller_ready = True
        inventory = self.command_ok("inventory", ["ansible-inventory", "-i", str(self.repo / "inventory/hosts.yml"),
                                                  "-e", "@" + str(self.root / "ANSIBLE_VARS.json"), "--list"])
        data = json.loads(inventory["stdout"], object_pairs_hook=unique_object)

        def members(group, seen=None):
            seen = set() if seen is None else set(seen)
            if group in seen:
                raise ValueError("Cyclic inventory groups")
            seen.add(group)
            value = data.get(group, {})
            result = set(value.get("hosts", []))
            for child in value.get("children", []):
                result.update(members(child, seen))
            return result

        if members("k8s_nodes") != set(HOSTS):
            raise ValueError("Inventory Kubernetes target set differs from the six reviewed hosts")
        for host, address in HOSTS.items():
            variables = data["_meta"]["hostvars"][host]
            if variables.get("ansible_host") != address or variables.get("cr_ntp_source_upstreams") != self.input["public_upstreams"] or variables.get("cr_ntp_migrate_main") is not True:
                raise ValueError("Resolved inventory/IP/upstream input differs for %s" % host)
        self.assert_source()
        self.verify_inputs()

    def validate_receipts(self, gate):
        receipts = {}
        expected_paths = {"%s--%s.json" % (gate, host) for host in HOSTS}
        actual_paths = {path.name for path in (self.root / "gates").glob(gate + "--*.json")}
        if actual_paths != expected_paths:
            raise ValueError("%s gate is missing host receipts or has unexpected hosts" % gate)
        for host, address in HOSTS.items():
            raw, value = read_json_bytes(self.root / "gates" / (gate + "--" + host + ".json"))
            expected = {"gate": gate, "run_id": self.summary["run_id"],
                        "source_head": self.input["reviewed_source_sha"], "input_sha256": self.input_hash,
                        "inventory_hostname": host, "ansible_host": address, "gate_pass": True}
            if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1 or value.get("errors") != [] or any(value.get(key) != item for key, item in expected.items()) or value.get("gate_pass") is not True:
                raise ValueError("%s receipt identity/binding/result invalid: %s" % (gate, host))
            targets = self.input["public_upstreams"] if gate == "diagnose" and host == SOURCE else ([HOSTS[SOURCE]] if gate == "pathcheck" and host != SOURCE else [])
            probes = value.get("probes")
            if not isinstance(probes, list) or any(not isinstance(item, dict) for item in probes) or sorted(item.get("target_address", "") for item in probes) != sorted(targets) or any(item.get("gate_pass") is not True for item in probes):
                raise ValueError("%s does not contain successful probes for every expected target: %s" % (gate, host))
            for probe in probes:
                offset = probe.get("offset_seconds")
                if (probe.get("target_port") != 123 or type(probe.get("returncode")) is not int
                        or probe["returncode"] != 0 or probe.get("outer_timeout") is not False
                        or probe.get("sample_accepted") is not True
                        or type(offset) not in (int, float) or not math.isfinite(offset) or abs(offset) > 0.1):
                    raise ValueError("%s probe lacks a successful finite <=100ms measurement: %s" % (gate, host))
            observation = value.get("observations")
            if not isinstance(observation, dict) or not observation:
                raise ValueError("%s receipt lacks service/path observations: %s" % (gate, host))
            required_checks = {"host_identity", "chrony_version", "service_contract", "no_competing_service", "effective_parse"}
            if gate == "diagnose":
                required_checks.add("migration_plan")
            elif host == SOURCE:
                required_checks.add("source_runtime_acl_listener")
            checks = observation.get("checks")
            if not isinstance(checks, dict) or any(checks.get(key) is not True for key in required_checks):
                raise ValueError("%s receipt lacks required successful service/path checks: %s" % (gate, host))
            properties = observation.get("service_properties")
            if not isinstance(properties, dict) or properties.get("LoadState") != "loaded" or properties.get("ActiveState") != "active" or not re.fullmatch(r"[1-9][0-9]*", str(properties.get("MainPID", ""))):
                raise ValueError("%s receipt lacks an active loaded service PID: %s" % (gate, host))
            if not isinstance(observation.get("expanded_exec_argv"), list) or not observation["expanded_exec_argv"]:
                raise ValueError("%s receipt lacks the real chronyd command: %s" % (gate, host))
            effective = observation.get("effective_config")
            if not isinstance(effective, dict) or type(effective.get("returncode")) is not int or effective["returncode"] != 0:
                raise ValueError("%s receipt lacks effective config parser output: %s" % (gate, host))
            receipts[host] = sha256(raw)
        write_json(self.root / (gate.upper() + "_GATE.json"), {"gate": gate, "status": "GATE_PASSED",
                                                               "receipts_sha256": receipts})

    def stage(self, phase, playbook=False, gate=False):
        self.assert_source()
        self.verify_inputs()
        if playbook:
            command = ["ansible-playbook", "-i", str(self.repo / "inventory/hosts.yml"),
                       "-e", "@" + str(self.root / "ANSIBLE_VARS.json"),
                       str(self.repo / "playbooks" / ("cr-p1-ntp-01-01-" + phase + ".yml"))]
        else:
            command = ["bash", str(self.repo / "scripts/cr-p1-ntp-01-01-run.sh"), phase]
        result = self.run_command(phase, command, 2100 if phase == "clients" else 900)
        self.assert_source()
        self.verify_inputs()
        if result["returncode"] != 0 or result.get("timed_out"):
            raise ValueError("%s failed; later apply stages were not started" % phase)
        if gate:
            self.validate_receipts(phase)

    def finalize(self):
        if not self.controller_ready or not self.source_bound:
            self.summary["wrapper_finalize"] = "NOT_RUN_CONTROLLER_GUARD"
            return
        try:
            self.assert_source()
            self.verify_inputs()
            result = self.run_command("finalize", ["bash", str(self.repo / "scripts/cr-p1-ntp-01-01-run.sh"), "finalize"], 60)
            self.assert_source()
            self.verify_inputs()
            self.summary["wrapper_finalize"] = "COMPLETED" if result["returncode"] == 0 and not result.get("timed_out") else "FAILED_RETAINED"
        except Exception as exc:
            self.summary["wrapper_finalize"] = "FAILED_RETAINED"
            self.summary["finalize_error"] = str(exc)

    def package(self):
        self.summary["ended_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write_json(self.root / "RESULT.json", self.summary)
        write_json(self.root / "COMMANDS.json", self.records)
        files = []
        for path in sorted(self.root.rglob("*")):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Unexpected non-regular evidence entry")
            if path.is_file() and path != self.root / "SHA256SUMS":
                files.append(path)
        (self.root / "SHA256SUMS").write_text("".join("%s  %s\n" % (sha256(path.read_bytes()), path.relative_to(self.root)) for path in files))
        archive = self.root.with_suffix(".tar.gz")
        with tarfile.open(archive, "w:gz", dereference=False) as stream:
            stream.add(self.root, arcname=self.root.name, recursive=True)
        archive.chmod(0o600)
        sidecar = Path(str(archive) + ".sha256")
        sidecar.write_text("%s  %s\n" % (sha256(archive.read_bytes()), archive.name))
        sidecar.chmod(0o600)
        print("STATUS=%s\nHOME_EVIDENCE=%s\nSHA256_SIDECAR=%s" % (self.summary["status"], archive, sidecar), flush=True)

    def run(self):
        rc = 1
        current_phase = "controller"
        try:
            self.create_evidence()
            self.prepare()
            if self.args.apply and self.env.get("CR_CHANGE_APPROVED") != CHANGE_ID:
                raise ValueError("--apply requires the existing CR_CHANGE_APPROVED=%s setting" % CHANGE_ID)
            for phase, playbook, gate in (("precheck", False, False), ("diagnose", True, True)):
                current_phase = phase
                self.stage(phase, playbook, gate)
            if not self.args.apply:
                self.summary["status"] = "DIAGNOSED_NOT_APPLIED"
                rc = 0
            else:
                current_phase = "source"
                self.summary["source_phase_started"] = True
                self.summary["source_applied"] = None
                self.stage("source")
                self.summary["source_applied"] = True
                current_phase = "pathcheck"
                self.stage("pathcheck", playbook=True, gate=True)
                current_phase = "clients"
                self.summary["clients_started"] = True
                self.stage("clients")
                current_phase = "verify"
                self.stage("verify")
                self.summary["status"] = "ROLLOUT_COMPLETED_REVIEW_REQUIRED"
                rc = 0
        except (Exception, KeyboardInterrupt) as exc:
            self.summary.update(error=str(exc) or type(exc).__name__, failed_phase=current_phase)
            if self.summary["clients_started"]:
                self.summary["status"] = "CLIENTS_STARTED_REVIEW_REQUIRED"
            elif self.summary["source_applied"]:
                self.summary["status"] = "SOURCE_APPLIED_CLIENTS_NOT_STARTED"
            elif current_phase == "source":
                self.summary["status"] = "SOURCE_PHASE_FAILED_REVIEW_REQUIRED"
            else:
                self.summary["status"] = "INCOMPLETE_APPLY_NOT_STARTED"
        finally:
            if self.active_process is not None:
                self.stop_process(self.active_process)
                self.active_process = None
            try:
                if self.root is not None:
                    self.finalize()
                    if self.summary.get("wrapper_finalize") == "FAILED_RETAINED" and rc == 0:
                        self.summary["status"] = "INCOMPLETE_FINALIZATION"
                        rc = 1
                    self.package()
            finally:
                if self.lock_fd is not None:
                    os.close(self.lock_fd)
                    self.lock_fd = None
        return rc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-input", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Continue automatically through gated apply using the existing CR approval")
    parser.add_argument("--evidence-parent", type=Path)
    args = parser.parse_args()
    os.umask(0o077)

    def interrupted(number, frame):
        # Subsequent interrupts must not race the bounded process cleanup/archive.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise RolloutInterrupted("Interrupted by signal %s" % number)

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        return Rollout(args).run()
    except Exception as exc:
        print("STOP: evidence finalization failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
