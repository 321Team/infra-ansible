"""Fixed Phase 1 fleet and shutdown contracts. No power command on import."""
import datetime
import hashlib
import json
import os
import ntpath
import pathlib
import re
import stat
import time

SCHEMA = "fds.phase1.shutdown.v1"
# Baseline v3.1.21 §§6.1,6.3,6.4; .56 added by DEC-P1-EGRESS-01.
# .51 is Phase 2 VPN, NOT a Phase 1 CA IP. Offline CA assets and test clones
# have no approved service endpoint in this fleet and are not auto-discovered.
PHASES = {
    "consumers": ["cicd-runner01", "edge01"],
    "workers": ["k8s-worker01", "k8s-worker02", "k8s-worker03"],
    "control-plane": ["k8s-control03", "k8s-control02", "k8s-control01"],
    "data": ["db01", "harbor01"],
    "observation": ["monitor01", "egress-proxy01"],
    "infrastructure": ["k8s-api-lb01", "dns02", "dns01"],
    # External Windows control, so the route stays up until Ansible is off.
    "management": ["ansible01", "mgmt-gw01"],
}
ROWS = [
    ("cicd-runner01", "10.250.10.20", "server01", "runner"),
    ("edge01", "10.1.93.50", "server08", "edge"),
    ("k8s-worker01", "10.1.93.105", "server05", "worker"),
    ("k8s-worker02", "10.1.93.107", "server06", "worker"),
    ("k8s-worker03", "10.1.93.108", "server07", "worker"),
    ("k8s-control03", "10.1.93.104", "server04", "control"),
    ("k8s-control02", "10.1.93.103", "server03", "control"),
    ("k8s-control01", "10.1.93.102", "server02", "control"),
    ("db01", "10.1.93.55", "server08", "database"),
    ("harbor01", "10.1.93.54", "server08", "harbor"),
    ("monitor01", "10.250.10.30", "server01", "monitor"),
    ("egress-proxy01", "10.1.93.56", "server08", "proxy"),
    ("k8s-api-lb01", "10.1.93.109", "server01", "lb"),
    ("dns02", "10.1.93.53", "server08", "dns"),
    ("dns01", "10.1.93.52", "server01", "dns"),
    ("ansible01", "10.250.10.10", "server01", "controller"),
    ("mgmt-gw01", "10.250.10.1", "server01", "gateway"),
]
FLEET = {name: {"ip": ip, "physical_host": host, "role": role} for name, ip, host, role in ROWS}
HARBOR_STOP_ORDER = ["nginx", "harbor-jobservice", "trivy-adapter", "harbor-portal",
                     "harbor-core", "registryctl", "registry", "redis", "harbor-db", "harbor-log"]


class Stop(Exception):
    pass


def require(ok, message):
    if not ok:
        raise Stop(message)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def age(value, now=None):
    stamp = datetime.datetime.fromisoformat(value)
    require(stamp.tzinfo is not None, "Timestamp must include timezone")
    return (now or datetime.datetime.now(datetime.timezone.utc)).timestamp() - stamp.timestamp()


def private_json(path):
    path = pathlib.Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink input path is not permitted")
    require(path.is_file() and not path.is_symlink(), "Input must be a regular nonsymlink file")
    if os.name == "posix":
        info = path.stat()
        require(info.st_uid == os.geteuid() and not stat.S_IMODE(info.st_mode) & 0o077,
                "Input must be owned by current operator and private (0600)")
    require(path.stat().st_size < 2 * 1024 * 1024, "Input too large")
    return json.loads(path.read_text(encoding="utf-8"))


def secure_dir(path):
    path = pathlib.Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink directory is not permitted")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(path.is_dir(), "Directory required")
    if os.name == "posix":
        info = path.stat()
        require(info.st_uid == os.geteuid() and not stat.S_IMODE(info.st_mode) & 0o077,
                "Use an operator-owned 0700 directory")
    return path


def save(path, value, exclusive=False):
    path = pathlib.Path(path)
    require(not path.is_symlink(), "State path must not be symlink")
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        temp = path.with_name(path.name + ".pending-" + str(os.getpid()))
        save(temp, value, exclusive=True)
        os.replace(temp, path)
    if os.name == "posix":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def validate_bindings(data):
    require(data.get("schema") == SCHEMA, "Wrong binding schema")
    resources = data.get("resources", {})
    require(set(resources) == set(FLEET), "Exactly the approved 17 Phase 1 resources are required")
    uuids, ids, paths = set(), set(), set()
    for name, binding in resources.items():
        require(binding.get("ip") == FLEET[name]["ip"], "IP mismatch: " + name)
        require(binding.get("physical_host") == FLEET[name]["physical_host"], "Owner mismatch: " + name)
        require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", binding.get("ssh_user", ""))
                and binding["ssh_user"] != "root", "Normal SSH account required: " + name)
        key = binding.get("ssh_key_file", "")
        require(isinstance(key, str) and (not key or (key.startswith("/") and
                not any(x in key for x in ("\n", "\r", "\0")))), "Invalid private SSH key path: " + name)
        require(re.fullmatch(r"[0-9a-f]{32}", binding.get("machine_id", "")), "Fresh machine-id required: " + name)
        require(re.fullmatch(r"(?:[0-9a-f]{2} ){7}[0-9a-f]{2}-(?:[0-9a-f]{2} ){7}[0-9a-f]{2}",
                             binding.get("vmx_uuid", "")), "Measured VMX BIOS UUID required: " + name)
        require(binding["vmx_uuid"] not in uuids and binding["machine_id"] not in ids, "Duplicate VM identity")
        uuids.add(binding["vmx_uuid"])
        ids.add(binding["machine_id"])
        require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,63}", binding.get("hostname", "")),
                "Measured guest hostname required: " + name)
        require(re.match(r"^[A-Za-z]:[\\/]", binding.get("vmx_path", "")) and
                binding["vmx_path"].lower().endswith(".vmx") and
                not any(x in binding["vmx_path"] for x in ("\n", "\r", "\0")) and
                ntpath.normpath(binding["vmx_path"]).replace("\\", "/") == binding["vmx_path"].replace("\\", "/"),
                "Absolute local Workstation VMX path required: " + name)
        key = (binding["physical_host"], binding["vmx_path"].replace("\\", "/").casefold())
        require(key not in paths, "Duplicate VMX path")
        paths.add(key)
    hosts = {x["physical_host"] for x in FLEET.values()}
    names = data.get("workstation_names", {})
    require(set(names) == hosts and all(re.fullmatch(r"[A-Za-z0-9_-]{1,63}", x) for x in names.values()) and
            len({x.casefold() for x in names.values()}) == len(hosts), "Measured Windows computer names required")
    refs = data.get("operator_checks", {})
    for key in ("window_ref", "app_quiesce_ref", "etcd_recovery_ref", "db_recovery_ref", "harbor_recovery_ref"):
        require(isinstance(refs.get(key), str) and refs[key].strip() and len(refs[key]) <= 512,
                "Operator evidence reference required: " + key)
    require(refs.get("full_cluster_outage_confirmed") is True and refs.get("ci_dispatch_paused") is True,
            "Full fleet outage and dispatch pause must be explicitly confirmed")
    unit = resources["db01"].get("database_unit", "")
    require(re.fullmatch(r"postgresql(?:-[0-9]{1,2})?\.service", unit), "Measured PostgreSQL service unit required")
    return data


def validate_plan(plan):
    require(plan.get("schema") == SCHEMA, "Wrong plan schema")
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", plan.get("operation_id", "")), "Invalid operation ID")
    require(re.fullmatch(r"[0-9a-f]{40}", plan.get("source_commit", "")), "Full reviewed source SHA required")
    validate_bindings(plan["bindings"])
    require(plan.get("binding_digest") == digest(plan["bindings"]), "Plan binding was changed")
    require(plan.get("fleet") == FLEET and plan.get("phases") == PHASES, "Fleet/ordering changed")
    require(0 <= age(plan["created_at"]) <= 24 * 3600, "Plan expired; create a new reviewed round")
    return plan


def receipt_for(plan, name, receipt, max_age=300):
    binding = plan["bindings"]["resources"][name]
    require(receipt.get("schema") == SCHEMA and receipt.get("operation_id") == plan["operation_id"], "Wrong receipt round")
    require(receipt.get("binding_digest") == plan["binding_digest"], "Receipt binding changed")
    require(receipt.get("observer") == "vmrun-list" and receipt.get("resource") == name, "Wrong observer/target")
    require(receipt.get("physical_host") == binding["physical_host"] and receipt.get("vmx_uuid") == binding["vmx_uuid"],
            "Hypervisor identity mismatch")
    require(receipt.get("vmx_path", "").replace("\\", "/").casefold() == binding["vmx_path"].replace("\\", "/").casefold(),
            "Hypervisor path mismatch")
    require(0 <= age(receipt["observed_at"]) <= max_age, "Receipt expired/future")
    require(receipt.get("power_state") == "POWERED_OFF", "Actual hypervisor Powered Off is required")
    require(receipt.get("clean_vmx_exit") is True and receipt.get("suspend_state_absent") is True,
            "List absence alone is insufficient (could be suspended/crashed)")
    return receipt


def prior_resources(phase):
    require(phase in PHASES, "Unknown phase")
    result = []
    for key, resources in PHASES.items():
        if key == phase:
            return result
        result.extend(resources)
    raise Stop("Unknown phase")


def wait_receipt(plan, name, directory, timeout=300):
    deadline = time.monotonic() + timeout
    path = pathlib.Path(directory) / (name + ".json")
    while True:
        if path.is_file():
            try:
                value = private_json(path)
                receipt_for(plan, name, value)
                return value
            except (Stop, ValueError, KeyError):
                pass  # No mutation/retry. An observer may atomically replace a stale receipt.
        require(time.monotonic() < deadline, "Powered Off confirmation timeout: " + name)
        time.sleep(2)
