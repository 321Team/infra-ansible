"""Offline candidate rendering, distinct from the preserved six-source Runtime fixture."""
from copy import deepcopy
from pathlib import Path
import re
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
RETAINED = {'10.250.10.20', '10.1.93.105', '10.1.93.107', '10.1.93.108', '10.1.93.102'}


class RetirementRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = yaml.safe_load((ROOT / 'inventory/group_vars/hbr.yml').read_text(encoding='utf-8'))
        # Match ansible.builtin.template's trim_blocks default.
        cls.template = Environment(undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True).from_string(
            (ROOT / 'templates/p1-hbr-01-ac04.nft.j2').read_text(encoding='utf-8'))
        cls.rendered = cls.template.render(**cls.values)

    def test_exact_retained_set_and_classifications(self):
        members = self.values['hbr_ac04_sources']
        self.assertEqual(len(members), 5)
        self.assertEqual({x['address'] for x in members}, RETAINED)
        self.assertEqual({x['address'] for x in members if x['classification'] == 'BASELINE_ALLOW'}, RETAINED - {'10.1.93.102'})
        control = next(x for x in members if x['address'] == '10.1.93.102')
        self.assertEqual(control['classification'], 'TEMP_MANAGEMENT_EXCEPTION')
        self.assertIn('remaining', control['expiry_condition'])
        elements = re.search(r'elements = \{([^}]*)\}', self.rendered, re.S).group(1)
        addresses = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', elements)
        self.assertEqual(len(addresses), 5)
        self.assertEqual(set(addresses), RETAINED)

    def test_only_edge_member_changes_in_rendered_guard(self):
        before = deepcopy(self.values)
        before['hbr_ac04_sources'].insert(4, {'address': '10.1.93.50'})
        prior_render = self.template.render(**before)
        expected = prior_render.replace('            10.1.93.50,', '')
        self.assertNotEqual(prior_render, expected)
        self.assertEqual(self.rendered, expected)

    def test_existing_drop_paths_and_unrelated_surfaces_stay_exact(self):
        self.assertIn('type filter hook forward priority -1; policy accept;', self.rendered)
        self.assertEqual(self.rendered.count('counter accept'), 1)
        self.assertEqual(self.rendered.count('counter drop'), 2)
        self.assertEqual(self.rendered.count('ct original proto-dst 443'), 3)
        self.assertEqual(self.rendered.count('ct original ip daddr 10.1.93.54'), 2)
        self.assertIn('meta nfproto ipv6', self.rendered)
        for forbidden in ('flush ruleset', 'table inet firewalld', 'DOCKER', '30080', 'dport 80'):
            self.assertNotIn(forbidden, self.rendered)
        self.assertEqual(self.values['hbr_ac04_denied_same_l2_source'], '10.1.93.26')
        self.assertEqual(self.values['hbr_ac04_mgmt_negative_source'], '10.250.10.10')


if __name__ == '__main__':
    unittest.main()
