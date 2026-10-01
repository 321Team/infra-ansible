"""CI binding for the P1-HBR-01 AC-04 static contract."""
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tools" / "p1-hbr-01-ac04-contract.py"


class P1HbrAc04StaticContractTest(unittest.TestCase):
    def test_static_contract_script_passes(self):
        self.assertTrue(CONTRACT.is_file(), f"missing contract: {CONTRACT}")
        # The contract is intentionally a fail-fast top-level script.
        # Any SystemExit/nonzero-style contract failure becomes a unittest error.
        runpy.run_path(str(CONTRACT), run_name="__p1_hbr_ac04_contract__")


if __name__ == "__main__":
    unittest.main()
