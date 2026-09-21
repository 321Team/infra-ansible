#!/usr/bin/python
"""Read-only, topology-bound NTP observations and chronyd -Q path probes.

No service operation, clock correction, or operational file write is performed.
Receipts (including failures) are returned to the controller for preservation.
"""
import datetime
import hashlib
import math
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import time

from ansible.module_utils.fds_ntp_policy import (
    validate_probe_target, validate_public_upstreams,
)

HOSTS = {"k8s-control01": "10.1.93.102", "k8s-control02": "10.1.93.103",
         "k8s-control03": "10.1.93.104", "k8s-worker01": "10.1.93.105",
         "k8s-worker02": "10.1.93.107", "k8s-worker03": "10.1.93.108"}
SOURCE = "k8s-control01"
CLIENTS = [ip for host, ip in HOSTS.items() if host != SOURCE]
OFFSET = re.compile(r"^.*\bSystem clock wrong by ([+-]?[0-9]+(?:\.[0-9]+)?) seconds \(ignored\)\s*$", re.M)


def clean_environment():
    env = {key: value for key, value in os.environ.items()
           if key not in ("LISTEN_FDS", "LISTEN_PID", "LISTEN_FDNAMES", "NOTIFY_SOCKET")}
    env["LC_ALL"] = "C"
    return env


def command(argv, timeout=10):
    started = time.monotonic()
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=False,
                              timeout=timeout, env=clean_environment())
        rc, out, err, expired = done.returncode, done.stdout, done.stderr, False
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
        rc, out, err, expired = 124, decode(exc.stdout), decode(exc.stderr), True
    except OSError as exc:
        rc, out, err, expired = 127, "", str(exc), False
    return {"argv": argv, "returncode": rc, "stdout": out, "stderr": err,
            "outer_timeout": expired, "elapsed_seconds": time.monotonic() - started}


def run_probe(chronyd, target, runner=command, timeout=20, limit_ms=100):
    validate_probe_target(target)
    if type(timeout) is not int or not 1 <= timeout <= 30:
        raise ValueError("Invalid bounded probe timeout")
    if not math.isfinite(limit_ms) or not 0 < limit_ms <= 100:
        raise ValueError("Invalid offset limit")
    result = runner([chronyd, "-4", "-Q", "-t", str(timeout),
                     "server " + target + " iburst", "pidfile /", "port 0",
                     "cmdport 0", "bindcmdaddress /"], timeout=timeout + 5)
    text = result["stdout"] + "\n" + result["stderr"]
    matches = OFFSET.findall(text)
    value = float(matches[0]) if len(matches) == 1 else None
    if value is not None and not math.isfinite(value):
        value = None
    accepted = (result["returncode"] == 0 and not result["outer_timeout"] and value is not None
                and math.isfinite(value) and "Disabled control of system clock" in text)
    return dict(result, method="chronyd_Q", target_address=target, target_port=123,
                sample_accepted=accepted, offset_seconds=value, offset_limit_ms=limit_ms,
                gate_pass=bool(accepted and abs(value) <= limit_ms / 1000.0),
                leap_status="NOT_EXPOSED_BY_Q", stratum="NOT_EXPOSED_BY_Q")


def validate_bindings(args):
    if args["gate"] not in ("diagnose", "pathcheck"):
        raise ValueError("Unknown gate")
    if HOSTS.get(args["inventory_hostname"]) != args["ansible_host"]:
        raise ValueError("Host/IP differs from the exact six-host topology")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", args["run_id"]):
        raise ValueError("Invalid run identifier")
    if not re.fullmatch(r"[0-9a-f]{40}", args["source_head"]) or not re.fullmatch(r"[0-9a-f]{64}", args["input_sha256"]):
        raise ValueError("Invalid source or input digest binding")
    validate_public_upstreams(args["source_upstreams"])


def service_arguments(argv, expected_binary, main_path):
    """Reject clock/source/config overrides; inspect expanded /proc argv, not $OPTIONS."""
    if not argv or os.path.realpath(argv[0]) != os.path.realpath(expected_binary):
        raise ValueError("Running chronyd executable differs from the probed binary")
    index = 1
    while index < len(argv):
        word = argv[index]
        if word in ("-n", "-d", "-4", "-R", "-r"):
            index += 1
            continue
        option = word[:2]
        if option not in ("-F", "-u", "-f"):
            raise ValueError("Unreviewed chronyd argument or command-line directive: " + word)
        if len(word) == 2:
            index += 1
            if index >= len(argv):
                raise ValueError("Missing chronyd option argument")
            value = argv[index]
        else:
            value = word[2:]
        if option == "-f" and value != main_path:
            raise ValueError("Running chronyd uses another configuration file")
        if option == "-F" and not re.fullmatch(r"-?[012]", value):
            raise ValueError("Unreviewed chronyd syscall-filter option")
        if option == "-u" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value):
            raise ValueError("Unreviewed chronyd runtime user")
        index += 1
    return True


def restart_arguments(properties, options_text, expected_binary, main_path):
    """Expand only the reviewed systemd $OPTIONS form without running a shell."""
    environment_files = properties.get("EnvironmentFiles", "")
    if environment_files not in ("", "/etc/sysconfig/chronyd (ignore_errors=yes)"):
        raise ValueError("Unreviewed chronyd EnvironmentFiles")
    matches = re.findall(r"argv\[\]=(.*?)\s*;\s*ignore_errors=", properties.get("ExecStart", ""))
    if len(matches) != 1:
        raise ValueError("Cannot resolve the current ExecStart template")
    assignments = []
    for line in options_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("OPTIONS="):
            raise ValueError("Unreviewed chronyd environment-file directive")
        assignments.append(line[len("OPTIONS="):])
    if len(assignments) > 1:
        raise ValueError("Duplicate chronyd OPTIONS assignments")
    option_words = shlex.split(assignments[0], posix=True) if assignments else []
    # EnvironmentFile quotes surround the whole variable value; shell expansion is forbidden.
    option_value = option_words[0] if len(option_words) == 1 else " ".join(option_words)
    if any(character in option_value for character in ("$", "`", "\\", "\n")):
        raise ValueError("Unreviewed escaping or expansion in chronyd OPTIONS")
    options = shlex.split(option_value, posix=True)
    argv = []
    for word in shlex.split(matches[0], posix=True):
        if word == "$OPTIONS":
            argv.extend(options)
        elif "$" in word or "`" in word:
            raise ValueError("Unreviewed systemd ExecStart expansion")
        else:
            argv.append(word)
    service_arguments(argv, expected_binary, main_path)
    return argv


def tracking_values(text, limit_ms=100):
    def field(pattern):
        values = re.findall(pattern, text, re.M)
        if len(values) != 1:
            raise ValueError("Missing or duplicate tracking field")
        return values[0].strip()
    leap = field(r"^Leap status\s*:\s*([^\r\n]+)$")
    last = float(field(r"^Last offset\s*:\s*([+\-0-9.eE]+)\s+seconds\s*$"))
    current = float(field(r"^System time\s*:\s*([+\-0-9.eE]+)\s+seconds\s+(?:fast|slow) of NTP time\s*$"))
    stratum = int(field(r"^Stratum\s*:\s*([0-9]+)\s*$"))
    if leap != "Normal" or not 1 <= stratum <= 15 or not all(math.isfinite(x) and abs(x) <= limit_ms / 1000.0 for x in (last, current)):
        raise ValueError("Tracking fails Leap Normal, stratum, or 100ms offset policy")
    return dict(leap_status=leap, last_offset_seconds=last, system_time_seconds=current, stratum=stratum)


class Observation:
    def __init__(self, args, runner=command):
        validate_bindings(args)
        self.args, self.runner = args, runner
        self.errors, self.observations, self.probes = [], {"checks": {}}, []
        self.chronyd = args.get("chronyd_path", "/usr/sbin/chronyd")
        self.main_path = args.get("main_path", "/etc/chrony.conf")

    def observe(self, name, argv, timeout=10, required=True):
        result = self.runner(argv, timeout=timeout)
        self.observations[name] = result
        if required and result["returncode"] != 0:
            self.errors.append(name + " command failed")
        return result

    def inspect_process(self, pid):
        raw = Path("/proc/%d/cmdline" % pid).read_bytes()
        if len(raw) > 65536 or not raw.endswith(b"\0"):
            raise ValueError("Invalid expanded chronyd process argv")
        argv = [value.decode("utf-8") for value in raw[:-1].split(b"\0")]
        self.observations["expanded_exec_argv"] = argv
        self.observations["running_executable"] = os.readlink("/proc/%d/exe" % pid)
        if os.path.realpath(self.observations["running_executable"]) != os.path.realpath(self.chronyd):
            raise ValueError("Running chronyd binary differs from the selected executable")
        service_arguments(argv, self.chronyd, self.main_path)

    def inspect_restart(self, properties):
        environment = self.runner(["systemctl", "show", "chronyd.service", "--property=Environment", "--value"], timeout=10)
        # Do not copy potentially unrelated environment variable values into evidence.
        inline = environment["stdout"].strip()
        self.observations["service_inline_environment"] = {
            "returncode": environment["returncode"], "empty": not inline,
            "accepted_empty_options_default": environment["returncode"] == 0 and inline == "OPTIONS=",
        }
        # Accept only systemctl's exact empty OPTIONS default. EnvironmentFile
        # supplies its reviewed override below; all other inline values still stop.
        if environment["returncode"] != 0 or inline not in ("", "OPTIONS="):
            raise ValueError("Inline chronyd Environment needs a separate restart review")
        options = ""
        if properties.get("EnvironmentFiles"):
            try:
                options = Path("/etc/sysconfig/chronyd").read_text()
            except FileNotFoundError:
                pass  # The reviewed unit marks this file optional.
            if len(options) > 65536:
                raise ValueError("Unexpectedly large chronyd environment file")
        argv = restart_arguments(properties, options, self.chronyd, self.main_path)
        self.observations["restart_exec_argv"] = argv
        self.observations["chronyd_options_sha256"] = hashlib.sha256(options.encode()).hexdigest()
        if argv != self.observations["expanded_exec_argv"]:
            raise ValueError("Running argv and next-restart argv differ; review configuration drift")

    def run(self):
        a = self.args
        observed_hostname = socket.gethostname()
        self.observations["hostname"] = observed_hostname
        if observed_hostname.split(".")[0] != a["inventory_hostname"]:
            self.errors.append("Observed hostname differs from inventory binding")
        addresses = self.observe("local_ipv4", ["ip", "-j", "-4", "address", "show"])
        try:
            import json
            values = [item["local"] for link in json.loads(addresses["stdout"])
                      for item in link.get("addr_info", []) if item.get("family") == "inet"]
            if a["ansible_host"] not in values:
                self.errors.append("Expected host IP is not configured locally")
        except (ValueError, KeyError, TypeError):
            self.errors.append("Could not parse local IPv4 addresses")
        self.observations["checks"]["host_identity"] = not self.errors
        version = self.observe("chronyd_version", [self.chronyd, "-v"])
        self.observations["checks"]["chrony_version"] = version["returncode"] == 0 and bool(re.search(r"\bversion 4\.8(?:\s|$)", version["stdout"] + version["stderr"]))
        if not self.observations["checks"]["chrony_version"]:
            self.errors.append("Expected reviewed chrony 4.8")
        service_errors_before = len(self.errors)
        service = self.observe("chronyd_service", ["systemctl", "show", "chronyd.service",
            "--property=LoadState,ActiveState,SubState,MainPID,ExecStart,FragmentPath,DropInPaths,EnvironmentFiles"])
        properties = dict(line.split("=", 1) for line in service["stdout"].splitlines() if "=" in line)
        self.observations["service_properties"] = properties
        try:
            if properties.get("LoadState") != "loaded" or properties.get("ActiveState") != "active":
                raise ValueError("chronyd must be loaded and active")
            if properties.get("DropInPaths", "") or properties.get("FragmentPath") not in ("/usr/lib/systemd/system/chronyd.service", "/lib/systemd/system/chronyd.service"):
                raise ValueError("Service override or nonstandard unit needs separate review")
            pid = int(properties.get("MainPID", "0"))
            if pid <= 0:
                raise ValueError("chronyd MainPID is missing")
            self.inspect_process(pid)
            self.inspect_restart(properties)
        except (ValueError, OSError, UnicodeError) as exc:
            self.errors.append(str(exc))
        self.observations["checks"]["service_contract"] = len(self.errors) == service_errors_before
        conflict_errors_before = len(self.errors)
        conflicts = self.observe("competing_time_services", ["systemctl", "show", "systemd-timesyncd.service",
            "ntpd.service", "ntpsec.service", "--property=Id,LoadState,ActiveState"], required=False)
        load_states = re.findall(r"^LoadState=(.+)$", conflicts["stdout"], re.M)
        if (set(re.findall(r"^Id=(.+)$", conflicts["stdout"], re.M)) !=
                {"systemd-timesyncd.service", "ntpd.service", "ntpsec.service"}
                or len(re.findall(r"^ActiveState=.+$", conflicts["stdout"], re.M)) != 3
                or len(load_states) != 3 or any(state not in ("loaded", "not-found", "masked") for state in load_states)
                or (conflicts["returncode"] != 0 and "not-found" not in load_states)):
            self.errors.append("Competing time-service observations are incomplete")
        if re.search(r"^ActiveState=(?:active|activating)\s*$", conflicts["stdout"], re.M):
            self.errors.append("A competing time synchronisation service is active")
        self.observations["checks"]["no_competing_service"] = len(self.errors) == conflict_errors_before
        effective = self.observe("effective_config", [self.chronyd, "-p", "-f", self.main_path], timeout=30)
        self.observations["checks"]["effective_parse"] = effective["returncode"] == 0
        try:
            self.observations["main_sha256"] = hashlib.sha256(Path(self.main_path).read_bytes()).hexdigest()
        except OSError as exc:
            self.errors.append("Cannot read main configuration: " + str(exc))
        if a["gate"] == "diagnose":
            self.observations["migration_plan"] = a.get("migration_plan", {})
            self.observations["checks"]["migration_plan"] = a.get("migration_plan", {}).get("validated") is True
            if not self.observations["checks"]["migration_plan"]:
                self.errors.append("Read-only paired migration plan did not validate")
        if a["gate"] == "pathcheck" and a["inventory_hostname"] == SOURCE:
            source_errors_before = len(self.errors)
            tracking = self.observe("tracking", ["chronyc", "tracking"])
            try:
                self.observations["tracking_values"] = tracking_values(tracking["stdout"])
            except (ValueError, OverflowError) as exc:
                self.errors.append(str(exc))
            sources = self.observe("sources", ["chronyc", "-n", "sources", "-a"])
            rows = re.findall(r"^([\^=#][*+?x~-])\s+(\S+)\s+.*$", sources["stdout"], re.M)
            if len(rows) != len(a["source_upstreams"]) or sorted(ip for state, ip in rows) != sorted(a["source_upstreams"]) or sum(state == "^*" for state, ip in rows) != 1:
                self.errors.append("Source runtime must contain exactly the approved two or three upstreams with one selected")
            directives = [line.split() for line in effective["stdout"].splitlines() if line.split()]
            source_lines = [line for line in directives if line[0].lower() in ("server", "pool", "peer", "refclock", "sourcedir", "local", "manual")]
            if sorted(source_lines) != sorted([["server", ip, "iburst"] for ip in a["source_upstreams"]]):
                self.errors.append("Source effective configuration differs from approved fixed upstreams")
            allows = [line for line in directives if line[0].lower() in ("allow", "deny")]
            if sorted(allows) != sorted([["allow", ip + "/32"] for ip in CLIENTS]):
                self.errors.append("Source effective ACL differs from exactly five client /32 rules")
            listener = self.observe("ntp_listener", ["ss", "-H", "-u", "-l", "-n", "-p", "sport = :123"])
            if not any("chronyd" in line and ("pid=" + properties.get("MainPID", "missing") + ",") in line
                       for line in listener["stdout"].splitlines()):
                self.errors.append("Current chronyd process has no observed UDP/123 listener")
            for ip in CLIENTS:
                access = self.observe("accheck_" + ip, ["chronyc", "accheck", ip])
                if access["stdout"].strip() != "208 Access allowed":
                    self.errors.append("Source access check did not allow " + ip)
            self.observations["checks"]["source_runtime_acl_listener"] = len(self.errors) == source_errors_before
        targets = (a["source_upstreams"] if a["gate"] == "diagnose" and a["inventory_hostname"] == SOURCE else
                   [HOSTS[SOURCE]] if a["gate"] == "pathcheck" and a["inventory_hostname"] != SOURCE else [])
        # Do not send packets from a misbound host or unsupported service/configuration.
        if not self.errors:
            self.probes = [run_probe(self.chronyd, target, self.runner) for target in targets]
            for probe in self.probes:
                if not probe["gate_pass"]:
                    self.errors.append("NTP packet/offset probe failed for " + probe["target_address"])
        return {"schema_version": 1, "gate": a["gate"], "run_id": a["run_id"],
                "source_head": a["source_head"], "input_sha256": a["input_sha256"],
                "inventory_hostname": a["inventory_hostname"], "ansible_host": a["ansible_host"],
                "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "expected_probe_targets": targets, "probes": self.probes,
                "observations": self.observations, "errors": self.errors,
                "gate_pass": not self.errors and len(self.probes) == len(targets)}


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        "gate": {"choices": ["diagnose", "pathcheck"], "required": True},
        "run_id": {"type": "str", "required": True},
        "source_head": {"type": "str", "required": True},
        "input_sha256": {"type": "str", "required": True},
        "inventory_hostname": {"type": "str", "required": True},
        "ansible_host": {"type": "str", "required": True},
        "source_upstreams": {"type": "list", "elements": "str", "required": True},
        "migration_plan": {"type": "dict", "default": {}},
        "chronyd_path": {"type": "path", "default": "/usr/sbin/chronyd"},
        "main_path": {"type": "path", "default": "/etc/chrony.conf"},
    }, supports_check_mode=True)
    try:
        receipt = Observation(module.params).run()
        module.exit_json(changed=False, receipt=receipt)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        module.fail_json(changed=False, msg=str(exc))


if __name__ == "__main__":
    main()
