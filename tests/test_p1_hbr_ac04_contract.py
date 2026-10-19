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

    def test_retired_source_or_lost_retained_source_is_rejected(self):
        original = Path.read_text
        mutations = {
            'retired_edge': lambda text: text.replace('hbr_ac04_sources:\n',
                'hbr_ac04_sources:\n  - address: 10.1.93.50\n'),
        }
        for ip in ('10.250.10.20', '10.1.93.105', '10.1.93.107', '10.1.93.108', '10.1.93.102'):
            mutations['lost_' + ip] = lambda text, ip=ip: text.replace('  - address: ' + ip + '\n', '')
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                def changed_source(path, *args, **kwargs):
                    text = original(path, *args, **kwargs)
                    return mutate(text) if path.name == 'hbr.yml' else text
                with patch.object(Path, 'read_text', changed_source):
                    with self.assertRaisesRegex(SystemExit, 'source set drift'):
                        runpy.run_path(str(CONTRACT), run_name='__ac04_retirement_drift__')

    def test_p2_overlay_cannot_be_broadened_or_enabled_by_default(self):
        original = Path.read_text
        mutations = {
            'broad_overlay': ('hbr-p2-rosa-coldpull.yml', lambda t: t.replace('10.20.10.0/24', '10.20.0.0/16'),
                              'P2 overlay drift'),
            'longer_expiry': ('hbr-p2-rosa-coldpull.yml', lambda t: t.replace('2026-10-23T23:59', '2026-11-18T23:59'),
                              'P2 overlay drift'),
            'default_on': ('hbr.yml', lambda t: t.replace('hbr_ac04_p2_sources: []',
                                                          'hbr_ac04_p2_sources:\n  - cidr: 10.20.10.0/24'),
                           'default to empty'),
        }
        for label, (name, mutate, message) in mutations.items():
            with self.subTest(label=label):
                def changed(path, *args, **kwargs):
                    text = original(path, *args, **kwargs)
                    return mutate(text) if path.name == name else text
                with patch.object(Path, 'read_text', changed):
                    with self.assertRaisesRegex(SystemExit, message):
                        runpy.run_path(str(CONTRACT), run_name='__ac04_p2_overlay_drift__')


if __name__ == "__main__":
    unittest.main()
