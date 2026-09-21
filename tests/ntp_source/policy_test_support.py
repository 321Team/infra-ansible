"""Load the exact repository module_utils dependency for direct unit imports.

Ansible integration suites use ANSIBLE_MODULE_UTILS instead, proving transport.
"""
import importlib.util
from pathlib import Path
import sys


def load_policy():
    name = "ansible.module_utils.fds_ntp_policy"
    path = Path(__file__).resolve().parents[2] / "module_utils/fds_ntp_policy.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
