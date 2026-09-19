#!/usr/bin/python
"""Narrow, opt-in chrony main/drop-in transaction for CR-P1-NTP-01-01.

Each file is replaced atomically; the pair is NOT a filesystem-atomic unit.
The immutable baseline and invocation rescue cover different recovery points.
No service operation or network request is performed by this module.
"""
import base64
import datetime
import errno
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from ansible.module_utils.fds_ntp_policy import validate_public_upstreams

OBSERVED_MAIN_SHA256 = "147346c1b876b87dfad3bd436c62bc137c36723137ed5b647cf376a9f54e66aa"
BASELINE_NAME = "original-ntp-pair.json"
LEGACY_NAME = "original-ntp-dropin.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_directory(path, required=False, protected=False):
    """Reject symlink traversal, including an existing ancestor of a new dir."""
    path = Path(path)
    for part in reversed([path] + list(path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if part == path and required:
                raise ValueError("Required directory absent: %s" % path)
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
            raise ValueError("Unsafe directory type/owner: %s" % part)
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o022 and not (part != path and mode & stat.S_ISVTX):
            raise ValueError("Unsafe writable ancestor directory: %s" % part)
        if "system.posix_acl_default" in os.listxattr(part, follow_symlinks=False):
            raise ValueError("Default directory ACL needs a separate metadata-preservation review: %s" % part)
        if part == path:
            if mode & 0o022 or (protected and mode != 0o700):
                raise ValueError("Unsafe directory permissions: %s" % path)
    return path.exists()


def read_file(path, required=False):
    check_directory(Path(path).parent, required=True)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if required:
            raise ValueError("Required file absent: %s" % path)
        return {"existed": False, "content_b64": "", "sha256": digest(b""),
                "uid": 0, "gid": 0, "mode": "0644", "selinux_b64": None}
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0:
        raise ValueError("Unsafe file type/link/owner: %s" % path)
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError("Unsafe writable configuration: %s" % path)
    # O_NOFOLLOW closes the lstat/open symlink replacement window.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("File changed while opening: %s" % path)
        extra_xattrs = set(os.listxattr(fd)) - {"security.selinux"}
        if extra_xattrs:
            raise ValueError("Unsupported file ACL/xattrs require separate review: %s (%s)" % (path, ", ".join(sorted(extra_xattrs))))
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read()
        try:
            context = os.getxattr(fd, "security.selinux")
        except OSError as exc:
            if exc.errno not in (errno.ENODATA, errno.ENOTSUP):
                raise
            context = None
        after = os.fstat(fd)
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
            raise ValueError("File changed while reading: %s" % path)
    finally:
        os.close(fd)
    return {"existed": True, "content_b64": base64.b64encode(data).decode("ascii"),
            "sha256": digest(data), "uid": info.st_uid, "gid": info.st_gid,
            "mode": "%04o" % stat.S_IMODE(info.st_mode),
            "selinux_b64": base64.b64encode(context).decode("ascii") if context else None}


def contents(state):
    return base64.b64decode(state["content_b64"], validate=True)


def make_main(original, role, dropin_path):
    if digest(original) != OBSERVED_MAIN_SHA256:
        raise ValueError("Main configuration does not match the observed source SHA256")
    if role in ("client", "source"):
        removed = {b"pool 2.centos.pool.ntp.org iburst\n", b"sourcedir /run/chrony-dhcp\n"}
        lines = original.splitlines(keepends=True)
        if any(lines.count(line) != 1 for line in removed):
            raise ValueError("Observed client source lines are not unique")
        original = b"".join(line for line in lines if line not in removed)
    return original + ("\n# CR-P1-NTP-01-01 exact managed include\ninclude %s\n" % dropin_path).encode("ascii")


def make_dropin(role, source_ip, client_ips, source_upstreams=None):
    header = b"# CR-P1-NTP-01-01 managed NTP configuration\n"
    if role == "source":
        upstreams = validate_public_upstreams(source_upstreams)
        return header + "".join("server %s iburst\n" % ip for ip in upstreams).encode("ascii") + "".join("allow %s/32\n" % ip for ip in client_ips).encode("ascii")
    return header + ("server %s iburst\n" % source_ip).encode("ascii")


class Transaction:
    def __init__(self, args, check_mode=False, default_context=None):
        self.args = args
        self.check_mode = check_mode
        self.default_context = default_context
        self.main = Path(args.get("main_path", "/etc/chrony.conf"))
        self.dropin = Path(args["dropin_path"])
        self.state_dir = Path(args["state_dir"])
        self.baseline = self.state_dir / BASELINE_NAME
        self.legacy = self.state_dir / LEGACY_NAME
        self.role = args["role"]
        self.mutation_started = False
        self.restore_status = "not_needed"
        for path in (self.main, self.dropin, self.state_dir):
            if not path.is_absolute() or str(path) != os.path.normpath(str(path)) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path)):
                raise ValueError("Only normalized absolute paths without glob/whitespace are supported")
        if self.main == self.dropin or self.state_dir in self.main.parents or self.state_dir in self.dropin.parents:
            raise ValueError("Configuration and state paths must be distinct")
        if args["change_id"] != "CR-P1-NTP-01-01" or self.role not in ("source", "client"):
            raise ValueError("Unexpected change identity or host role")
        # This migration is bound to the reviewed topology, not a source selector.
        if args["source_ip"] != "10.1.93.102" or set(args["client_ips"]) != {"10.1.93.103", "10.1.93.104", "10.1.93.105", "10.1.93.107", "10.1.93.108"} or len(args["client_ips"]) != 5:
            raise ValueError("Topology differs from the reviewed source and five clients")
        for ip in [args["source_ip"]] + args["client_ips"]:
            ipaddress.IPv4Address(ip)
        if self.role == "source" and args.get("action", "plan") in ("plan", "apply"):
            validate_public_upstreams(args.get("source_upstreams", []))

    def identity(self):
        return {"schema_version": 2, "change_id": self.args["change_id"],
                "inventory_hostname": self.args["inventory_hostname"], "role": self.role,
                "main_path": str(self.main), "dropin_path": str(self.dropin),
                "observed_main_sha256": OBSERVED_MAIN_SHA256}

    def snapshot(self):
        parent_exists = check_directory(self.dropin.parent)
        main = read_file(self.main, required=True)
        dropin = read_file(self.dropin) if parent_exists else {"existed": False,
            "content_b64": "", "sha256": digest(b""), "uid": 0, "gid": 0,
            "mode": "0644", "selinux_b64": None}
        return dict(self.identity(), captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    main=main, dropin=dropin, dropin_parent_existed=parent_exists)

    def validate_snapshot(self, value, baseline=False):
        if not isinstance(value, dict) or any(value.get(k) != v for k, v in self.identity().items()):
            raise ValueError("Pair snapshot identity/schema mismatch")
        if type(value.get("dropin_parent_existed")) is not bool:
            raise ValueError("Invalid parent-directory snapshot")
        for name in ("main", "dropin"):
            item = value.get(name)
            if not isinstance(item, dict) or type(item.get("existed")) is not bool:
                raise ValueError("Invalid file existence snapshot")
            if not isinstance(item.get("content_b64"), str) or base64.b64encode(contents(item)).decode("ascii") != item["content_b64"] or digest(contents(item)) != item.get("sha256"):
                raise ValueError("Invalid content checksum/base64 snapshot")
            if not item["existed"] and contents(item):
                raise ValueError("Absent file has content")
            if any(type(item.get(key)) is not int or item[key] < 0 for key in ("uid", "gid")) or item["uid"] != 0:
                raise ValueError("Invalid file ownership snapshot")
            if not isinstance(item.get("mode"), str) or not re.fullmatch(r"[0-7]{4}", item["mode"]) or int(item["mode"], 8) & 0o022:
                raise ValueError("Invalid file permission snapshot")
            label = item.get("selinux_b64")
            if label is not None and (not isinstance(label, str) or base64.b64encode(base64.b64decode(label, validate=True)).decode("ascii") != label):
                raise ValueError("Invalid SELinux context snapshot")
        if not value["main"]["existed"]:
            raise ValueError("Main configuration cannot be absent")
        if value["dropin"]["existed"] and not value["dropin_parent_existed"]:
            raise ValueError("Existing drop-in has no parent directory in snapshot")
        if baseline and value["main"]["sha256"] != OBSERVED_MAIN_SHA256:
            raise ValueError("Immutable baseline is not the observed native main configuration")
        return value

    def read_baseline(self, required=False):
        exists = check_directory(self.state_dir, required=required, protected=True)
        if not exists:
            return None
        if os.path.lexists(self.legacy):
            raise ValueError("Legacy schema 1 baseline requires separate review; no automatic conversion")
        value = read_file(self.baseline, required=required)
        if not value["existed"]:
            return None
        if value["mode"] != "0600":
            raise ValueError("Pair baseline must be root-owned mode 0600")
        return self.validate_snapshot(json.loads(contents(value)), baseline=True)

    def candidate(self, original):
        candidate = json.loads(json.dumps(original))
        for name, data in (("main", make_main(contents(original["main"]), self.role, str(self.dropin))),
                           ("dropin", make_dropin(self.role, self.args["source_ip"], self.args["client_ips"], self.args.get("source_upstreams")))):
            candidate[name].update(existed=True, content_b64=base64.b64encode(data).decode("ascii"), sha256=digest(data))
            if not original[name]["existed"] and self.default_context is not None:
                label = self.default_context(str(self.main if name == "main" else self.dropin))
                candidate[name]["selinux_b64"] = base64.b64encode(label).decode("ascii") if label else None
        candidate["dropin_parent_existed"] = True
        return candidate

    def parse_pair(self, pair):
        """A private stage substitutes ONLY this managed include's exact path."""
        with tempfile.TemporaryDirectory(prefix="fds-ntp-stage-") as directory:
            stage = Path(directory)
            main_data = contents(pair["main"])
            exact = ("include %s\n" % self.dropin).encode("ascii")
            if exact in main_data:
                if main_data.count(exact) != 1 or not pair["dropin"]["existed"]:
                    raise ValueError("Invalid exact managed include/drop-in pair")
                (stage / "managed.conf").write_bytes(contents(pair["dropin"]))
                main_data = main_data.replace(exact, ("include %s\n" % (stage / "managed.conf")).encode("ascii"))
            (stage / "chrony.conf").write_bytes(main_data)
            result = subprocess.run([self.args.get("chronyd_path", "chronyd"), "-p", "-f", str(stage / "chrony.conf")],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
            if result.returncode:
                raise ValueError("Staged combined chronyd parser rejected configuration: %s" % result.stderr.decode("utf-8", "replace")[:2000])
            return digest(result.stdout)

    def ensure_directory(self, path, mode):
        check_directory(path)
        missing = []
        cursor = Path(path)
        while not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        for directory in reversed(missing):
            directory.mkdir(mode=mode)
            os.chmod(directory, mode)
            if self.default_context is not None:
                label = self.default_context(str(directory))
                if label:
                    os.setxattr(directory, "security.selinux", label)
        check_directory(path, required=True)

    def write_file(self, path, item):
        """Prepare complete bytes/metadata/SELinux label before same-dir rename."""
        path = Path(path)
        check_directory(path.parent, required=True)
        read_file(path)  # Refuse a newly introduced symlink/hardlink before mutation.
        if not item["existed"]:
            if path.exists():
                path.unlink()
            return
        fd, temporary = tempfile.mkstemp(prefix=".fds-ntp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(contents(item))
                stream.flush()
                os.fchown(stream.fileno(), item["uid"], item["gid"])
                os.fchmod(stream.fileno(), int(item["mode"], 8))
                label = base64.b64decode(item["selinux_b64"]) if item.get("selinux_b64") else None
                if label is None and self.default_context is not None:
                    label = self.default_context(str(path))
                if label:
                    os.setxattr(stream.fileno(), "security.selinux", label)
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def persist_baseline(self, value):
        self.ensure_directory(self.state_dir, 0o700)
        check_directory(self.state_dir, required=True, protected=True)
        if os.path.lexists(self.legacy):
            raise ValueError("Legacy baseline appeared before pair baseline creation")
        data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
        # link() publishes only the completed fsynced private file; never replaces baseline.
        fd, temporary = tempfile.mkstemp(prefix=".pair-baseline-", dir=str(self.state_dir))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o600)
                os.fsync(stream.fileno())
            os.link(temporary, self.baseline)
        finally:
            os.unlink(temporary)
        directory_fd = os.open(self.state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return self.read_baseline(required=True)

    @staticmethod
    def same_files(left, right):
        return all(left[name] == right[name] for name in ("main", "dropin", "dropin_parent_existed"))

    def restore_pair(self, pair):
        self.validate_snapshot(pair)
        self.parse_pair(pair)
        check_directory(self.dropin.parent)
        # Native main removes its managed include before a newly-created drop-in disappears.
        self.write_file(self.main, pair["main"])
        if pair["dropin"]["existed"]:
            self.ensure_directory(self.dropin.parent, 0o755)
            self.write_file(self.dropin, pair["dropin"])
        elif self.dropin.parent.exists():
            self.write_file(self.dropin, pair["dropin"])
        if not pair["dropin_parent_existed"] and self.dropin.parent.exists():
            try:
                self.dropin.parent.rmdir()
            except OSError as exc:
                if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise

    def run(self):
        action = self.args.get("action", "plan")
        if action == "plan" or self.check_mode:
            return self._run()
        if action == "apply":
            # Do not create even a state directory for an invalid plan.
            plan_args = dict(self.args, action="plan")
            Transaction(plan_args, default_context=self.default_context)._run()
            self.ensure_directory(self.state_dir, 0o700)
        else:
            self.read_baseline(required=True)
        check_directory(self.state_dir, required=True, protected=True)
        descriptor = os.open(self.state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Another pair transaction holds the state-directory lock") from exc
            # Reread baseline and pair under the shared per-host mutation lock.
            return self._run()
        finally:
            os.close(descriptor)

    def _run(self):
        action = self.args.get("action", "plan")
        if action not in ("plan", "apply", "restore", "rollback"):
            raise ValueError("Invalid transaction action")
        baseline = self.read_baseline(required=action == "rollback")
        before = self.snapshot()
        if action in ("restore", "rollback"):
            target = baseline if action == "rollback" else self.validate_snapshot(self.args.get("snapshot"))
            self.parse_pair(target)
            changed = not self.same_files(before, target)
            if changed and not self.check_mode:
                if not self.same_files(before, self.snapshot()):
                    raise ValueError("Pair drifted before restoration")
                self.mutation_started = True
                self.restore_status = "in_progress"
                self.restore_pair(target)
                self.restore_status = "restored"
            return {"changed": changed, "restored": True, "snapshot": before}
        original = baseline or before
        self.validate_snapshot(original, baseline=True)
        candidate = self.candidate(original)
        native = before["main"]["sha256"] == OBSERVED_MAIN_SHA256
        if not native and (baseline is None or not self.same_files(before, candidate)):
            raise ValueError("Current main/drop-in drift or migrated configuration without immutable baseline")
        parser_digest = self.parse_pair(candidate)
        changed = not self.same_files(before, candidate)
        result = {"changed": changed if action == "apply" else False, "would_change": changed,
                  "snapshot": before, "main_sha256": candidate["main"]["sha256"],
                  "dropin_sha256": candidate["dropin"]["sha256"], "parser_stdout_sha256": parser_digest,
                  "baseline_present": baseline is not None, "layout": "native" if native else "migrated"}
        if self.args.get("_diff"):
            result["diff"] = [{"before_header": str(path), "after_header": str(path),
                               "before": contents(before[name]).decode("utf-8"),
                               "after": contents(candidate[name]).decode("utf-8")}
                              for name, path in (("main", self.main), ("dropin", self.dropin))
                              if before[name] != candidate[name]]
        if action == "plan" or self.check_mode or not changed:
            return result
        if not self.same_files(before, self.snapshot()):
            raise ValueError("Current pair drifted after staged validation")
        if baseline is None:
            self.persist_baseline(before)
        # Validate immutable identity again immediately before replacing operational files.
        self.read_baseline(required=True)
        if not self.same_files(before, self.snapshot()):
            raise ValueError("Current pair drifted before commit")
        try:
            self.mutation_started = True
            self.ensure_directory(self.dropin.parent, 0o755)
            self.write_file(self.dropin, candidate["dropin"])
            self.write_file(self.main, candidate["main"])
        except Exception as exc:
            self.restore_status = "in_progress"
            try:
                self.restore_pair(before)
            except Exception as recovery:
                self.restore_status = "failed"
                raise RuntimeError("PAIR WRITE FAILED; RESTORE FAILED: %s; %s" % (exc, recovery)) from exc
            self.restore_status = "restored"
            raise RuntimeError("Pair write failed; invocation snapshot restored: %s" % exc) from exc
        return result


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        "action": {"choices": ["plan", "apply", "restore", "rollback"], "default": "plan"},
        "main_path": {"type": "path", "default": "/etc/chrony.conf"},
        "dropin_path": {"type": "path", "required": True},
        "state_dir": {"type": "path", "required": True},
        "change_id": {"type": "str", "required": True},
        "inventory_hostname": {"type": "str", "required": True},
        "role": {"choices": ["source", "client"], "required": True},
        "source_ip": {"type": "str", "required": True},
        "client_ips": {"type": "list", "elements": "str", "required": True},
        "source_upstreams": {"type": "list", "elements": "str", "default": []},
        "chronyd_path": {"type": "path", "default": "chronyd"},
        "snapshot": {"type": "dict", "default": None, "no_log": True},
    }, supports_check_mode=True)

    def default_context(path):
        if not module.selinux_enabled():
            return None
        context = module.selinux_default_context(path)
        if not context or any(part is None for part in context):
            raise ValueError("SELinux default context unavailable for %s" % path)
        return ":".join(context).encode("utf-8") + b"\0"

    transaction = None
    try:
        args = dict(module.params, _diff=module._diff)
        transaction = Transaction(args, module.check_mode, default_context)
        module.exit_json(**transaction.run())
    except Exception as exc:
        module.fail_json(msg=str(exc), changed=bool(transaction and transaction.mutation_started),
                         restoration=transaction.restore_status if transaction else "not_needed")


if __name__ == "__main__":
    main()
