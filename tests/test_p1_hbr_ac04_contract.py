"""CI binding for the P1-HBR-01 AC-04 static contract."""
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tools" / "p1-hbr-01-ac04-contract.py"


class P1HbrAc04StaticContractTest(unittest.TestCase):
    def test_static_contract_script_passes(self):
        self.assertTrue(CONTRACT.is_file(), f"missing contract: {CONTRACT}")
        # The contract is intentionally a fail-fast top-level script.
        # Any SystemExit/nonzero-style contract failure becomes a unittest error.
        runpy.run_path(str(CONTRACT), run_name="__p1_hbr_ac04_contract__")

    def test_firewalld_lifecycle_coupling_is_rejected(self):
        original = Path.read_text
        for directive in ("Requires", "BindsTo", "PartOf", "Wants"):
            with self.subTest(directive=directive):
                def unsafe_unit(path, *args, **kwargs):
                    text = original(path, *args, **kwargs)
                    if path.name == "p1-hbr-01-ac04-guard.service.j2":
                        text += "\n" + directive + "=other.service firewalld.service\n"
                    return text
                with patch.object(Path, "read_text", unsafe_unit):
                    with self.assertRaisesRegex(SystemExit, "couple its lifecycle"):
                        runpy.run_path(str(CONTRACT), run_name="__ac04_unsafe_lifecycle__")

    def test_required_docker_guard_cannot_be_weakened(self):
        original = Path.read_text
        def weakened_unit(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            if path.name == "p1-hbr-01-ac04-guard.service.j2":
                text = text.replace("RequiredBy=docker.service", "WantedBy=docker.service")
            return text
        with patch.object(Path, "read_text", weakened_unit):
            with self.assertRaisesRegex(SystemExit, "RequiredBy=docker.service"):
                runpy.run_path(str(CONTRACT), run_name="__ac04_weakened_boot_guard__")


if __name__ == "__main__":
    unittest.main()
