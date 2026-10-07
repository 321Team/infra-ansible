import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('analysis', Path(__file__).parents[1] / 'tools/p1-hbr-ac04-docker-chain-analysis.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    # Synthetic rules only; these are not received server evidence.
    return {'schema': 3, 'forward_rules': ['-P FORWARD DROP', '-A FORWARD -j DOCKER-USER', '-A FORWARD -j DOCKER-FORWARD'],
        'docker_user_rules': ['-N DOCKER-USER'],
        'docker_forward_rules': mod.FORWARD_PREFIX + mod.TAILS['docker_forward_rules'],
        'docker_filter_rules': ['-N DOCKER', '-A DOCKER -p tcp --dport 443 -j ACCEPT',
            '-A DOCKER -p tcp --dport 80 -j ACCEPT', '-A DOCKER -p tcp --dport 1514 -j ACCEPT'] + mod.TAILS['docker_filter_rules'],
        'docker_nat_rules': ['-N DOCKER', '-A DOCKER -p tcp --dport 443 -j DNAT --to-destination 192.0.2.1:443']}


class ChainAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.original = fixture()
        self.raw = json.dumps(self.original).encode()
        self.sha = hashlib.sha256(self.raw).hexdigest()

    def run_case(self, current):
        return mod.analyze(self.raw, json.dumps(current).encode(), self.sha)

    def test_exact_is_chain_scope_and_never_go(self):
        result = self.run_case(copy.deepcopy(self.original))
        self.assertEqual(result['status'], 'EXACT_DOCKER_CHAINS_ONLY')
        for field in ('full_verifier_pass', 'runtime_go', 'ac04_accepted', 'capture_freshness_verified'):
            self.assertIs(result[field], False)

    def test_forward_tail_swap_is_review_candidate(self):
        current = copy.deepcopy(self.original)
        current['docker_forward_rules'][-2:] = current['docker_forward_rules'][-2:][::-1]
        result = self.run_case(current)
        self.assertEqual(result['status'], 'FIXED_TAIL_SWAP_REVIEW_REQUIRED')
        self.assertIs(result['exact_docker_chain_match'], False)

    def test_filter_tail_swap_is_review_candidate(self):
        current = copy.deepcopy(self.original)
        current['docker_filter_rules'][-2:] = current['docker_filter_rules'][-2:][::-1]
        self.assertEqual(self.run_case(current)['status'], 'FIXED_TAIL_SWAP_REVIEW_REQUIRED')

    def test_both_swaps_do_not_become_pass(self):
        current = copy.deepcopy(self.original)
        for field in mod.TAILS:
            current[field][-2:] = current[field][-2:][::-1]
        result = self.run_case(current)
        self.assertIs(result['only_fixed_tail_swap_candidates'], True)
        self.assertIs(result['runtime_go'], False)

    def test_reverse_original_order_supported(self):
        field = 'docker_forward_rules'
        before = self.original[field][:4] + self.original[field][-2:][::-1]
        self.assertTrue(mod.fixed_tail_swap_candidate(field, before, self.original[field]))

    def test_prefix_reorder_rejected(self):
        current = copy.deepcopy(self.original)
        current['docker_forward_rules'][1:3] = current['docker_forward_rules'][1:3][::-1]
        self.assertEqual(self.run_case(current)['status'], 'UNSUPPORTED_DRIFT')

    def test_accept_prefix_reorder_rejected(self):
        current = copy.deepcopy(self.original)
        current['docker_filter_rules'][1:3] = current['docker_filter_rules'][1:3][::-1]
        self.assertEqual(self.run_case(current)['status'], 'UNSUPPORTED_DRIFT')

    def test_insert_delete_duplicate_mutations_rejected(self):
        for field in mod.TAILS:
            for change in ('insert', 'delete', 'duplicate'):
                with self.subTest(field=field, change=change):
                    current = copy.deepcopy(self.original)
                    if change == 'insert': current[field].insert(4, '-A DOCKER -j RETURN')
                    elif change == 'delete': current[field].pop()
                    else: current[field][-1] = current[field][-2]
                    self.assertEqual(self.run_case(current)['status'], 'UNSUPPORTED_DRIFT')

    def test_option_interface_or_target_change_rejected(self):
        for replacement in ('-A DOCKER-FORWARD -i docker+ -j ACCEPT',
                '-A DOCKER-FORWARD -i docker0 -j DROP',
                '-A DOCKER-FORWARD -i docker0 -m comment --comment x -j ACCEPT'):
            current = copy.deepcopy(self.original)
            current['docker_forward_rules'][-1] = replacement
            self.assertEqual(self.run_case(current)['status'], 'UNSUPPORTED_DRIFT')

    def test_nat_user_forward_drift_rejected(self):
        for field in ('docker_nat_rules', 'docker_user_rules', 'forward_rules'):
            current = copy.deepcopy(self.original)
            current[field].append('-A DOCKER -j ACCEPT')
            self.assertEqual(self.run_case(current)['status'], 'UNSUPPORTED_DRIFT')

    def test_original_hash_mismatch_and_malformed_hash_rejected(self):
        for sha in ('0'*64, 'not-a-hash'):
            with self.assertRaises(mod.AnalysisError): mod.analyze(self.raw, self.raw, sha)

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(mod.AnalysisError): mod.decode(b'{"schema":3,"schema":3}')

    def test_invalid_json_nonfinite_and_array_rejected(self):
        for raw in (b'broken', b'{"x":NaN}', b'[]', b'\xff'):
            with self.assertRaises(mod.AnalysisError): mod.decode(raw)

    def test_missing_or_malformed_fields_rejected(self):
        for value in (None, [], True, ['line\nsecond'], [''], [None]):
            current = copy.deepcopy(self.original)
            current['docker_filter_rules'] = value
            with self.assertRaises(mod.AnalysisError): self.run_case(current)

    def test_schema_bool_or_other_version_rejected(self):
        for schema in (True, 2, '3'):
            original = copy.deepcopy(self.original); original['schema'] = schema
            raw = json.dumps(original).encode()
            with self.assertRaises(mod.AnalysisError): mod.analyze(raw, self.raw, hashlib.sha256(raw).hexdigest())

    def test_size_limit_and_oversize_file_rejected(self):
        with self.assertRaises(mod.AnalysisError): mod.decode(b' '*(mod.MAX_BYTES+1))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'big'; path.write_bytes(b' '*(mod.MAX_BYTES+1))
            with self.assertRaises(mod.AnalysisError): mod.read_bounded(path)

    def test_cli_candidate_returns_two_and_hides_extra_secrets(self):
        current = copy.deepcopy(self.original)
        current['docker_filter_rules'][-2:] = current['docker_filter_rules'][-2:][::-1]
        current['irrelevant_secret'] = 'MOCK_PRIVATE_CONTENT_DO_NOT_EMIT'
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder)/'original', Path(folder)/'current'
            a.write_bytes(self.raw); b.write_text(json.dumps(current), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = mod.main(['--original-state', str(a), '--original-sha256', self.sha, '--current-state', str(b)])
            self.assertEqual(rc, 2)
            self.assertNotIn('MOCK_PRIVATE_CONTENT_DO_NOT_EMIT', output.getvalue())
            self.assertIs(json.loads(output.getvalue())['runtime_go'], False)

    def test_cli_read_failure_is_categorical(self):
        with tempfile.TemporaryDirectory() as folder:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = mod.main(['--original-state', str(Path(folder)/'private-location'),
                    '--original-sha256', self.sha, '--current-state', str(Path(folder)/'missing')])
            self.assertEqual(rc, 2)
            self.assertNotIn('private-location', output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['error'], 'INPUT_READ_FAILED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
