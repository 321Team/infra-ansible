from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks" / "p1-sec-01-b2-collect-58.yml"


class P1SecB2ConditionalCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PLAYBOOK.read_text(encoding="utf-8")

    def test_playbook_yaml_parses(self):
        docs = list(yaml.safe_load_all(self.source))
        self.assertEqual(len(docs), 3)

    def test_async_status_uses_finished_test(self):
        self.assertIn("until: td_done is finished", self.source)
        self.assertNotIn("until: td_done.finished", self.source)

    def test_final_verdict_gate_is_explicit_boolean(self):
        expected = "- (hostvars[item].verdict.failed | default(true)) is false"
        self.assertIn(expected, self.source)
        self.assertNotIn(
            "not ((hostvars[item].verdict | default({'failed': true})).failed | default(true))",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
