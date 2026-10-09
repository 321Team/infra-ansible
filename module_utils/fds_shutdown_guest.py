"""Role-specific Linux checks and normal stop. No broad deletion or retries."""
import json
import os
import pathlib
import re
import shlex
import subprocess

try:
    from ansible.module_utils.fds_shutdown_core import FLEET, HARBOR_STOP_ORDER, Stop, require
except ImportError:  # Local unit fixtures, no Ansible installation needed.
    from fds_shutdown_core import FLEET, HARBOR_STOP_ORDER, Stop, require


class Guest:
    def __init__(self, name, expected, runner=None, reader=None):
        require(name in FLEET, "Target outside Phase 1 fleet")
        self.name, self.expected, self.role = name, expected, FLEET[name]["role"]
        self.runner = runner or self._run
        self.read = reader or (lambda path: pathlib.Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def _run(argv, timeout=30):
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                    env={"PATH": "/usr/local/bin:/usr/bin:/usr/sbin", "LC_ALL": "C"})
        except subprocess.TimeoutExpired:
            raise Stop("Command deadline exceeded; backend may continue; preserve intent, do not retry")
        require(result.returncode == 0, "Required command failed; no automatic fallback")
        require(len(result.stdout) < 8 * 1024 * 1024, "Observation too large")
        return result.stdout.strip()

    def identity(self):
        require(os.geteuid() == 0, "Normal account with authorized sudo is required")
        require(os.environ.get("SUDO_USER") == self.expected["ssh_user"] and
                os.environ.get("SUDO_UID", "").isdigit() and int(os.environ["SUDO_UID"]) > 0,
                "Become must originate from the measured non-root SSH account via sudo")
        result = {"hostname": self.runner(["/usr/bin/hostname"]),
                  "machine_id": self.read("/etc/machine-id").strip(),
                  "boot_id": self.read("/proc/sys/kernel/random/boot_id").strip()}
        require(result["hostname"] == self.expected["hostname"] and
                result["machine_id"] == self.expected["machine_id"], "Guest identity mismatch")
        require(self.read("/proc/1/comm").strip() == "systemd", "systemd PID1 required")
        return result

    def no_clients(self, ports):
        value = self.runner(["/usr/sbin/ss", "-Htn", "state", "established"])
        for line in value.splitlines():
            cols = line.split()
            require(len(cols) >= 4, "Unexpected ss format")
            require(not any(cols[2].endswith(":" + str(port)) for port in ports), "Active service clients; quiesce first")

    def probe(self, global_checks=False):
        data = self.identity()
        if self.role == "runner":
            active = self.runner(["/usr/bin/systemctl", "list-units", "--state=active,activating", "--type=service", "--no-legend"])
            require(not re.search(r"actions\.runner\.|RunnerService", active, re.I), "Runner service still active; retire first")
            for entry in pathlib.Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    comm = (entry / "comm").read_text().strip()
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
                require(comm not in {"Runner.Listener", "Runner.Worker", "RunnerService", "trivy", "buildkitd"},
                        "Runner/job process present; retire the runner first")
            require(not self.runner(["/usr/bin/docker", "ps", "-q"]), "Running CI containers; preserve/retire first")
        if self.role in {"edge", "harbor"}:
            self.no_clients([80, 443])
        if self.role in {"worker", "control"}:
            props = self.runner(["/usr/bin/systemctl", "show", "kubelet.service", "-p", "ActiveState", "-p", "MainPID"])
            props = dict(x.split("=", 1) for x in props.splitlines())
            pid = props.get("MainPID", "")
            require(props.get("ActiveState") == "active" and pid.isdigit() and int(pid) > 0, "Active kubelet PID required")
            args = self.read("/proc/" + pid + "/cmdline").split("\0")
            configs = [x.split("=", 1)[1] for x in args if x.startswith("--config=")]
            configs += [args[i + 1] for i, x in enumerate(args[:-1]) if x == "--config"]
            require(configs == ["/var/lib/kubelet/config.yaml"] and not any(
                x.startswith("--shutdown-grace-period") or re.search(r"GracefulNodeShutdown=false", x) for x in args),
                "Kubelet live config/CLI differs; do not infer effective grace from an unused file")
            config = self.read("/var/lib/kubelet/config.yaml")
            def duration(key):
                matches = re.findall(r'^' + key + r':\s*"?([0-9]+)s"?\s*(?:#.*)?$', config, re.M)
                require(len(matches) == 1, "Explicit seconds-only kubelet grace setting required: " + key)
                return int(matches[0])
            total, critical = duration("shutdownGracePeriod"), duration("shutdownGracePeriodCriticalPods")
            require(0 < critical < total, "Graceful Node Shutdown is not enabled; no automatic config changes")
            require(not re.search(r"GracefulNodeShutdown:\s*false", config), "GracefulNodeShutdown disabled")
            delay = self.runner(["/usr/bin/busctl", "get-property", "org.freedesktop.login1",
                "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "InhibitDelayMaxUSec"])
            require(re.fullmatch(r"t [0-9]+", delay) and int(delay.split()[1]) >= total * 1000000,
                    "logind inhibitor budget shorter than kubelet shutdown grace")
            raw = self.runner(["/usr/bin/busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                "org.freedesktop.login1.Manager", "ListInhibitors"])
            fields = shlex.split(raw)
            require(len(fields) >= 2 and fields[0] == "a(ssssuu)" and fields[1].isdigit() and
                    len(fields) == 2 + int(fields[1]) * 6, "Unexpected logind inhibitor format")
            inhibitors = [fields[i:i + 6] for i in range(2, len(fields), 6)]
            require(any("shutdown" in row[0].split(":") and row[3] == "delay" and row[5] == pid for row in inhibitors),
                    "Running kubelet does not hold a shutdown delay inhibitor")
            data["node_grace_seconds"] = total
        if self.name == "k8s-control01" and global_checks:
            kubectl = "/usr/bin/kubectl" if pathlib.Path("/usr/bin/kubectl").is_file() else "/usr/local/bin/kubectl"
            pods = json.loads(self.runner([kubectl, "--kubeconfig=/etc/kubernetes/admin.conf", "get", "pods", "-A", "-o", "json"]))
            for pod in pods["items"]:
                meta, status = pod["metadata"], pod.get("status", {})
                daemon = any(x.get("kind") == "DaemonSet" for x in meta.get("ownerReferences", []))
                system = meta["namespace"] in {"kube-system", "kube-public", "kube-node-lease"}
                require(system or daemon or status.get("phase") in {"Succeeded", "Failed"},
                        "Non-system application/monitoring Pod still present; approved quiesce is required")
            data["application_pods_quiesced"] = True
        if self.role == "database":
            unit = self.expected["database_unit"]
            require(re.fullmatch(r"postgresql(?:-[0-9]{1,2})?\.service", unit), "Invalid DB unit")
            props = self.runner(["/usr/bin/systemctl", "show", unit, "-p", "LoadState", "-p", "ActiveState",
                                 "-p", "SendSIGKILL", "-p", "TimeoutStopUSec"])
            props = dict(x.split("=", 1) for x in props.splitlines())
            require(props.get("LoadState") == "loaded" and props.get("ActiveState") == "active", "DB unit is not active")
            require(props.get("SendSIGKILL") == "no" or props.get("TimeoutStopUSec") == "infinity",
                    "DB service can escalate to SIGKILL; review stop policy before use")
            psql = self.expected.get("psql_bin", "/usr/bin/psql")
            require(psql in {"/usr/bin/psql", "/usr/pgsql-15/bin/psql", "/usr/pgsql-16/bin/psql",
                             "/usr/pgsql-17/bin/psql"}, "Unsupported psql binary")
            count = self.runner(["/usr/sbin/runuser", "-u", "postgres", "--", psql, "-X", "-A", "-t", "-d", "postgres", "-c",
                "SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND backend_type = 'client backend';"])
            require(count == "0", "PostgreSQL client sessions remain; no forced disconnect")
        if self.role == "harbor":
            # A recovery/autostart owner needs its separately reviewed
            # HOLD/stop path. Discover it rather than assume it is absent.
            active = self.runner(["/usr/bin/systemctl", "list-units", "--state=active", "--type=service", "--no-legend"])
            require(not re.search(r"harbor.*(?:recover|auto|boot)|fds.*hbr", active, re.I),
                    "Harbor manager active; use reviewed owner stop path")
            installed = self.runner(["/usr/bin/systemctl", "list-unit-files", "--type=service", "--no-legend"])
            require(not re.search(r"harbor.*(?:recover|auto|boot)|fds.*hbr", installed, re.I),
                    "Harbor manager installed; integrate its reviewed graceful stop/HOLD contract first")
            rows = self.runner(["/usr/bin/docker", "ps", "-a", "--format", "{{.ID}} {{.Names}}"])
            ids = dict((name, cid) for cid, name in (line.split() for line in rows.splitlines()))
            require(set(ids) == set(HARBOR_STOP_ORDER) and all(re.fullmatch(r"[0-9a-f]{12,64}", x) for x in ids.values()),
                    "Harbor inventory changed or unrelated containers present")
            data["harbor_ids"] = ids
        return data

    def request(self, observed, operation):
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", operation), "Invalid operation token")
        # Repeat all role checks immediately before submitting a mutation.
        # Do not query the Kubernetes API after losing etcd quorum in this
        # intentional full-cluster shutdown. Global quiesce is checked first.
        current = self.probe()
        require(current["boot_id"] == observed["boot_id"], "Guest rebooted since preflight")
        if self.role == "database":
            self.runner(["/usr/bin/systemctl", "stop", self.expected["database_unit"]], timeout=120)
            props = self.runner(["/usr/bin/systemctl", "show", self.expected["database_unit"], "-p", "ActiveState", "-p", "SubState"])
            require("ActiveState=inactive" in props and "SubState=dead" in props, "DB clean stop not confirmed")
        if self.role == "harbor":
            require(current["harbor_ids"] == observed["harbor_ids"], "Harbor containers changed since preflight")
            for name in HARBOR_STOP_ORDER:
                cid = current["harbor_ids"][name]
                # Docker timeout -1 prevents a daemon SIGKILL escalation. A
                # client deadline is UNKNOWN, not cancellation or permission to retry.
                self.runner(["/usr/bin/docker", "stop", "--timeout", "-1", cid], timeout=120)
                item = json.loads(self.runner(["/usr/bin/docker", "inspect", "--format", "{{json .State}}", cid]))
                require(not item["Running"] and not item.get("OOMKilled") and item["ExitCode"] in {0, 130, 143},
                        "Container graceful stop not confirmed; preserve partial state")
        self.runner(["/usr/bin/systemd-run", "--unit=fds-shutdown-" + operation,
                     "--on-active=5s", "/usr/bin/systemctl", "poweroff"], timeout=30)
        return {"status": "NORMAL_SHUTDOWN_SCHEDULED", "power_state": "NOT_CONFIRMED"}
