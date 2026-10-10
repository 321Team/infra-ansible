#!/usr/bin/python
"""Single measured guest only; use the coordinator for ordering and evidence."""
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.fds_shutdown_core import PHASES, Stop, require, validate_plan
from ansible.module_utils.fds_shutdown_guest import Guest


def main():
    module = AnsibleModule(argument_spec={
        "plan": {"type": "dict", "required": True, "no_log": True},
        "resource": {"type": "str", "required": True},
        "action": {"type": "str", "choices": ["preflight", "inspect", "request"], "default": "preflight"},
        "observed": {"type": "dict", "default": {}},
        "confirm": {"type": "str", "default": ""},
    }, supports_check_mode=True)
    try:
        p = module.params
        plan = validate_plan(p["plan"])
        require(p["resource"] in plan["bindings"]["resources"], "Unknown resource")
        guest = Guest(p["resource"], plan["bindings"]["resources"][p["resource"]])
        observed = guest.probe(global_checks=p["action"] == "preflight")
        if p["action"] != "request" or module.check_mode:
            module.exit_json(changed=False, observation=observed, status="READ_ONLY")
        require(p["resource"] not in PHASES["management"], "Management VMs require Windows finalizer")
        require(p["confirm"] == "POWER_OFF:" + plan["operation_id"] + ":" + plan["binding_digest"],
                "Explicit round/digest confirmation required")
        # Controller claims prevent replay. Preserve a separate guest claim so
        # a different controller/state directory cannot submit a second stop.
        import os
        import json
        import re
        require(re.fullmatch(r"[0-9a-f-]{36}", observed["boot_id"]), "Invalid boot identity")
        claim = "/run/fds-phase1-shutdown-" + observed["boot_id"] + ".intent"
        fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"operation_id": plan["operation_id"], "binding_digest": plan["binding_digest"]}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        result = guest.request(p["observed"], plan["operation_id"])
        module.exit_json(changed=True, **result)
    except Exception as exc:
        # Do not include raw command stdout/stderr, env or passwords in errors.
        reason = str(exc) if isinstance(exc, Stop) else type(exc).__name__
        module.fail_json(msg="HOLD: " + reason + "; preserve intent/evidence; no automatic retry")


if __name__ == "__main__":
    main()
