"""Fixture-backed verifier contract for P1-HBR-01 AC-04 nftables v1.1.5."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "p1_hbr_ac04" / "nftables-v1.1.5-list.txt"
VERIFY = ROOT / "playbooks" / "tasks" / "p1-hbr-01-ac04-nft-verify.yml"

EXPECTED_SOURCES = {
    "10.1.93.50",
    "10.1.93.102",
    "10.1.93.105",
    "10.1.93.107",
    "10.1.93.108",
    "10.250.10.20",
}
EXPECTED_META = "type filter hook forward priority -1; policy accept;"
EXPECTED_RULES = [
    'iifname "ens160" ct status 0x20 ct original ip daddr 10.1.93.54 ct protocol 6 '
    'ct original proto-dst 443 ip saddr @approved_v4 counter accept '
    'comment "P1-HBR-01-AC04 approved IPv4"',
    'iifname "ens160" ct status 0x20 ct original ip daddr 10.1.93.54 ct protocol 6 '
    'ct original proto-dst 443 counter drop '
    'comment "P1-HBR-01-AC04 deny unapproved IPv4"',
    'iifname "ens160" meta nfproto 10 ct status 0x20 ct protocol 6 '
    'ct original proto-dst 443 counter drop '
    'comment "P1-HBR-01-AC04 deny IPv6 published 443"',
]


def normalize_rule(line):
    line = re.sub(r"\s+counter packets \d+ bytes \d+\s+", " counter ", line.strip())
    return re.sub(r"\s+", " ", line).strip()


def chain_section(text):
    marker = "=== LIST CHAIN ===\n"
    start = text.index(marker) + len(marker)
    end = text.index("\nCHAIN_RC=0", start)
    return text[start:end]


class P1HbrAc04NftFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FIXTURE.read_text(encoding="utf-8")
        cls.verifier = VERIFY.read_text(encoding="utf-8")

    def test_fixture_is_same_reviewed_nft_version(self):
        self.assertIn("nftables v1.1.5 (Commodore Bullmoose #6)", self.fixture)
        self.assertIn("LOAD_RC=0", self.fixture)
        self.assertIn("TABLE_RC=0", self.fixture)
        self.assertIn("CHAIN_RC=0", self.fixture)

    def test_fixture_approved_set_is_exact(self):
        table = self.fixture.split("=== LIST TABLE ===\n", 1)[1].split("\nTABLE_RC=0", 1)[0]
        match = re.search(r"elements = \{([^}]*)\}", table, re.S)
        self.assertIsNotNone(match)
        observed = set(re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", match.group(1)))
        self.assertEqual(EXPECTED_SOURCES, observed)

    def test_fixture_chain_metadata_and_rules_are_exact(self):
        section = chain_section(self.fixture)
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        meta = [re.sub(r"\s+", " ", x) for x in lines if x.startswith("type filter hook ")]
        rules = [
            normalize_rule(x)
            for x in lines
            if x.startswith("iifname ")
        ]
        self.assertEqual([EXPECTED_META], meta)
        self.assertEqual(EXPECTED_RULES, rules)

    def test_verifier_uses_v115_canonical_list_form(self):
        block = self.verifier.split("hbr_ac04_nft_expected_rules:", 1)[1].split(
            "- name: Normalize reviewed rule contract", 1
        )[0]
        for token in ("ct status 0x20", "ct protocol 6", "meta nfproto 10"):
            self.assertIn(token, block)
        self.assertNotIn("ct status dnat", block)
        self.assertNotIn("ct original protocol tcp", block)
        self.assertNotIn("meta nfproto ipv4", block)

    def test_verifier_fails_closed_on_unvalidated_nft_version(self):
        self.assertIn(
            "hbr_ac04_nft_version in hbr_ac04_nft_supported_versions",
            self.verifier,
        )


if __name__ == "__main__":
    unittest.main()
