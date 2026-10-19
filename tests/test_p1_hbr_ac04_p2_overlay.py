"""P2 ROSA cold-pull overlay for the P1-HBR-01 AC-04 guard (fds-project-baseline#13).

Offline only. Two parts:
  * render: without the overlay the guard is byte-identical to the reviewed P1 guard; with it,
    only one interval set and one accept rule are added, before the unapproved IPv4 drop.
  * verifier: the live nft verifier task is evaluated with Jinja (Ansible-like filters/tests)
    against nft list outputs written in the nftables 1.1.5 canonical form of the existing
    fixture. The P2 lines follow that form; they are not a capture from a real nft run.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
import unittest

from jinja2 import Environment, StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'templates/p1-hbr-01-ac04.nft.j2'
VERIFY = ROOT / 'playbooks/tasks/p1-hbr-01-ac04-nft-verify.yml'
OVERLAY = ROOT / 'inventory/overlays/hbr-p2-rosa-coldpull.yml'
# Reviewed P1 guard source after the .50 retirement (fds-project-baseline#13 6184139707).
P1_GUARD_SHA256 = '6bef425bfb72e2f64e938c913028c29b2033b4c13633db27ac4e24e729aaa5b0'


def load_values(overlay=False):
    values = yaml.safe_load((ROOT / 'inventory/group_vars/hbr.yml').read_text(encoding='utf-8'))
    if overlay:
        values.update(yaml.safe_load(OVERLAY.read_text(encoding='utf-8')))
    return values


def render(values):
    # Match ansible.builtin.template's trim_blocks default.
    env = Environment(undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    return env.from_string(TEMPLATE.read_text(encoding='utf-8')).render(**values)


class P2Render(unittest.TestCase):
    def test_without_overlay_guard_is_the_reviewed_p1_guard(self):
        self.assertEqual(load_values()['hbr_ac04_p2_sources'], [])
        self.assertEqual(sha256(render(load_values()).encode()).hexdigest(), P1_GUARD_SHA256)

    def test_overlay_adds_only_one_set_and_one_rule(self):
        p1, p2 = render(load_values()), render(load_values(overlay=True))
        block = re.search(r'\n    set p2_rosa_v4 \{.*?\n    \}\n', p2, re.S).group(0)
        rule = re.search(r'\n        iifname[^\n]*P2-ROSA-COLDPULL[^\n]*\n\n', p2).group(0)
        self.assertEqual(p2.replace(block, '\n', 1).replace(rule, '\n', 1).replace('    }\n\n\n', '    }\n\n'), p1)
        self.assertIn('flags interval', block)
        self.assertEqual(re.findall(r'(?:\d{1,3}\.){3}\d{1,3}/\d+', p2), ['10.20.10.0/24'])
        self.assertEqual(p2.count('counter accept'), 2)
        self.assertEqual(p2.count('counter drop'), 2)
        self.assertLess(p2.index('P1-HBR-01-AC04 approved IPv4'), p2.index('P2-ROSA-COLDPULL'))
        self.assertLess(p2.index('P2-ROSA-COLDPULL'), p2.index('P1-HBR-01-AC04 deny unapproved IPv4'))
        p2_rule = rule.strip()
        for token in ('iifname "ens160"', 'ct status dnat', 'ct original ip daddr 10.1.93.54',
                      'ct original protocol tcp', 'ct original proto-dst 443', 'ip saddr @p2_rosa_v4'):
            self.assertIn(token, p2_rule)

    def test_p1_sources_are_not_touched_by_the_overlay(self):
        p1, p2 = load_values(), load_values(overlay=True)
        self.assertEqual(p1['hbr_ac04_sources'], p2['hbr_ac04_sources'])
        elements = re.search(r'set approved_v4 \{.*?elements = \{([^}]*)\}', render(p2), re.S).group(1)
        self.assertNotIn('10.20.', elements)

    def test_overlay_scope_and_hard_expiry(self):
        overlay = yaml.safe_load(OVERLAY.read_text(encoding='utf-8'))
        self.assertEqual(overlay, {'hbr_ac04_p2_sources': [{
            'cidr': '10.20.10.0/24', 'classification': 'P2_TEMP_ROSA_COLDPULL',
            'owner': 'rosa-worker-private_a', 'hard_expiry_kst': '2026-10-23T23:59:00+09:00'}]})


# ---------------------------------------------------------------- verifier evaluation
P1_RULES = [
    'iifname "ens160" ct status 0x20 ct original ip daddr 10.1.93.54 ct protocol 6 ct original proto-dst 443 '
    'ip saddr @approved_v4 counter packets 3 bytes 180 accept comment "P1-HBR-01-AC04 approved IPv4"',
    'iifname "ens160" ct status 0x20 ct original ip daddr 10.1.93.54 ct protocol 6 ct original proto-dst 443 '
    'counter packets 7 bytes 420 drop comment "P1-HBR-01-AC04 deny unapproved IPv4"',
    'iifname "ens160" meta nfproto 10 ct status 0x20 ct protocol 6 ct original proto-dst 443 '
    'counter packets 0 bytes 0 drop comment "P1-HBR-01-AC04 deny IPv6 published 443"',
]
P2_RULE = ('iifname "ens160" ct status 0x20 ct original ip daddr 10.1.93.54 ct protocol 6 ct original proto-dst 443 '
           'ip saddr @p2_rosa_v4 counter packets 0 bytes 0 accept comment "P2-ROSA-COLDPULL approved worker subnet"')
P1_SET = ('\tset approved_v4 {\n\t\ttype ipv4_addr\n\t\telements = { 10.1.93.102, 10.1.93.105,\n'
          '\t\t\t     10.1.93.107, 10.1.93.108,\n\t\t\t     10.250.10.20 }\n\t}\n')


def p2_set(cidr='10.20.10.0/24'):
    return f'\tset p2_rosa_v4 {{\n\t\ttype ipv4_addr\n\t\tflags interval\n\t\telements = {{ {cidr} }}\n\t}}\n'


def live(rules, sets):
    chain = ('\tchain forward_guard {\n\t\ttype filter hook forward priority -1; policy accept;\n'
             + ''.join('\t\t' + r + '\n' for r in rules) + '\t}\n')
    table = 'table inet p1_hbr_ac04 {\n' + '\n'.join(sets + [chain]) + '}\n'
    return {'table': table, 'chain': 'table inet p1_hbr_ac04 {\n' + chain + '}\n',
            'approved_v4': 'table inet p1_hbr_ac04 {\n' + P1_SET + '}\n',
            'p2_rosa_v4': ('table inet p1_hbr_ac04 {\n' + sets[1] + '}\n') if len(sets) > 1 else None}


def environment():
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters['regex_findall'] = lambda s, p: re.findall(p, s)
    env.filters['regex_replace'] = lambda s, p, r: re.sub(p, r, s)
    env.tests['search'] = lambda s, p: re.search(p, s) is not None
    env.tests['match'] = lambda s, p: re.match(p, s) is not None
    return env


def template(env, value, facts):
    if isinstance(value, list):
        return [template(env, v, facts) for v in value]
    if isinstance(value, str) and '{{' in value:
        return env.from_string(value).render(**facts)
    return value


def run_verifier(values, state):
    """Evaluate the verifier task list; returns the list of failed assert expressions."""
    env, facts = environment(), dict(values, hbr_ac04_nft_version='1.1.5')
    for task in yaml.safe_load(VERIFY.read_text(encoding='utf-8')):
        if 'when' in task and not env.compile_expression(task['when'])(**facts):
            facts[task['register']] = {'skipped': True}
            continue
        if 'ansible.builtin.command' in task:
            argv = task['ansible.builtin.command']['argv']
            if argv[:2] == ['nft', '-c']:
                out = {'rc': 0, 'stdout': ''}
            else:
                kind = argv[3]
                key = 'table' if kind == 'table' else 'chain' if kind == 'chain' else argv[-1]
                text = state[key]
                if text is None:
                    out = {'rc': 1, 'stdout': ''}  # Ansible would fail the task here: treat as STOP
                    return ['nft list failed: ' + key]
                out = {'rc': 0, 'stdout': text, 'stdout_lines': text.splitlines()}
            facts[task['register']] = out
        elif 'ansible.builtin.set_fact' in task:
            for name, expr in task['ansible.builtin.set_fact'].items():
                facts[name] = template(env, expr, facts)
        elif 'ansible.builtin.assert' in task:
            return [x for x in task['ansible.builtin.assert']['that']
                    if not env.compile_expression(x)(**facts)]
    raise AssertionError('verifier has no assert task')


class P2Verifier(unittest.TestCase):
    def test_p1_only_guard_passes_without_overlay(self):
        self.assertEqual(run_verifier(load_values(), live(P1_RULES, [P1_SET])), [])

    def test_p2_guard_passes_with_overlay(self):
        rules = P1_RULES[:1] + [P2_RULE] + P1_RULES[1:]
        self.assertEqual(run_verifier(load_values(overlay=True), live(rules, [P1_SET, p2_set()])), [])

    def test_leftover_p2_after_removal_is_a_stop(self):
        rules = P1_RULES[:1] + [P2_RULE] + P1_RULES[1:]
        self.assertTrue(run_verifier(load_values(), live(rules, [P1_SET, p2_set()])))

    def test_overlay_without_live_p2_is_a_stop(self):
        self.assertTrue(run_verifier(load_values(overlay=True), live(P1_RULES, [P1_SET])))

    def test_p2_rule_after_the_drop_is_a_stop(self):
        rules = P1_RULES[:2] + [P2_RULE] + P1_RULES[2:]
        self.assertTrue(run_verifier(load_values(overlay=True), live(rules, [P1_SET, p2_set()])))

    def test_live_p2_set_with_other_subnet_is_a_stop(self):
        rules = P1_RULES[:1] + [P2_RULE] + P1_RULES[1:]
        self.assertTrue(run_verifier(load_values(overlay=True), live(rules, [P1_SET, p2_set('10.20.0.0/16')])))

    def test_broadened_overlay_is_a_stop(self):
        values = load_values(overlay=True)
        for change in ({'cidr': '10.20.0.0/16'}, {'classification': 'BASELINE_ALLOW'}):
            v = deepcopy(values)
            v['hbr_ac04_p2_sources'][0].update(change)
            rules = P1_RULES[:1] + [P2_RULE] + P1_RULES[1:]
            self.assertTrue(run_verifier(v, live(rules, [P1_SET, p2_set(v['hbr_ac04_p2_sources'][0]['cidr'])])), change)
        v = deepcopy(values)
        v['hbr_ac04_p2_sources'].append({'cidr': '10.20.10.0/24', 'classification': 'P2_TEMP_ROSA_COLDPULL'})
        self.assertTrue(run_verifier(v, live(P1_RULES[:1] + [P2_RULE] + P1_RULES[1:], [P1_SET, p2_set()])))


if __name__ == '__main__':
    unittest.main()
