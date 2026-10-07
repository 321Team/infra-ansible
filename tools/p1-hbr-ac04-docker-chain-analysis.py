#!/usr/bin/env python3
"""Offline Docker chain comparison; never a Runtime GO or verifier bypass."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

MAX_BYTES = 1024 * 1024
FIELDS = ('forward_rules', 'docker_user_rules', 'docker_forward_rules',
          'docker_filter_rules', 'docker_nat_rules')
FORWARD_PREFIX = ['-N DOCKER-FORWARD', '-A DOCKER-FORWARD -j DOCKER-CT',
                  '-A DOCKER-FORWARD -j DOCKER-INTERNAL',
                  '-A DOCKER-FORWARD -j DOCKER-BRIDGE']
TAILS = {
    'docker_forward_rules': ['-A DOCKER-FORWARD -i docker0 -j ACCEPT',
        '-A DOCKER-FORWARD -i br-835092bfcbbc -j ACCEPT'],
    'docker_filter_rules': ['-A DOCKER ! -i docker0 -o docker0 -j DROP',
        '-A DOCKER ! -i br-835092bfcbbc -o br-835092bfcbbc -j DROP'],
}


class AnalysisError(Exception):
    pass


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AnalysisError('DUPLICATE_JSON_KEY')
        value[key] = item
    return value


def decode(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise AnalysisError('INPUT_SIZE_LIMIT')
    try:
        obj = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(AnalysisError('NONFINITE_JSON')))
    except (UnicodeError, ValueError, RecursionError):
        raise AnalysisError('INVALID_JSON') from None
    if not isinstance(obj, dict):
        raise AnalysisError('OBJECT_REQUIRED')
    return obj


def read_bounded(path):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError:
        raise AnalysisError('INPUT_READ_FAILED') from None
    if not 0 < len(raw) <= MAX_BYTES:
        raise AnalysisError('INPUT_SIZE_LIMIT')
    return raw


def rule_lines(obj, field):
    value = obj.get(field)
    if (not isinstance(value, list) or not 1 <= len(value) <= 512
            or any(not isinstance(x, str) or not 0 < len(x) <= 2048
                   or '\n' in x or '\r' in x or '\x00' in x for x in value)):
        raise AnalysisError('INVALID_CHAIN_' + field.upper())
    return value


def fixed_tail_swap_candidate(field, original, current):
    """Recognize two literal tails only; never sort an entire chain."""
    pair = TAILS.get(field)
    if pair is None or len(original) != 6 or len(current) != 6:
        return False
    if original[:4] != current[:4]:
        return False
    if field == 'docker_forward_rules' and original[:4] != FORWARD_PREFIX:
        return False
    if field == 'docker_filter_rules':
        if original[0] != '-N DOCKER':
            return False
        if any(not x.startswith('-A DOCKER ') or not x.endswith(' -j ACCEPT')
               for x in original[1:4]):
            return False
    return (original[-2:] in (pair, pair[::-1])
            and current[-2:] == original[-2:][::-1])


def analyze(original_raw, current_raw, expected_original_sha256):
    if not re.fullmatch(r'[0-9a-f]{64}', expected_original_sha256):
        raise AnalysisError('EXPECTED_ORIGINAL_SHA256_REQUIRED')
    original_sha = hashlib.sha256(original_raw).hexdigest()
    if original_sha != expected_original_sha256:
        raise AnalysisError('ORIGINAL_SHA256_MISMATCH')
    original, current = decode(original_raw), decode(current_raw)
    if type(original.get('schema')) is not int or original['schema'] != 3:
        raise AnalysisError('ORIGINAL_SCHEMA_3_REQUIRED')
    comparisons = {}
    for field in FIELDS:
        before, after = rule_lines(original, field), rule_lines(current, field)
        exact = before == after
        comparisons[field] = {
            'exact_match': exact,
            'fixed_tail_swap_candidate': not exact and fixed_tail_swap_candidate(field, before, after),
            'original_line_count': len(before), 'current_line_count': len(after),
            'original_lines_sha256': hashlib.sha256(json.dumps(before, ensure_ascii=False).encode()).hexdigest(),
            'current_lines_sha256': hashlib.sha256(json.dumps(after, ensure_ascii=False).encode()).hexdigest(),
        }
    exact_all = all(x['exact_match'] for x in comparisons.values())
    classified_only = all(x['exact_match'] or x['fixed_tail_swap_candidate'] for x in comparisons.values())
    return {
        'schema': 'HBR-AC04-offline-docker-chain-analysis-1',
        'recorded_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'original_sha256': original_sha,
        'current_sha256': hashlib.sha256(current_raw).hexdigest(),
        'expected_original_sha256_match': True,
        'comparisons': comparisons,
        'exact_docker_chain_match': exact_all,
        'only_fixed_tail_swap_candidates': not exact_all and classified_only,
        'status': ('EXACT_DOCKER_CHAINS_ONLY' if exact_all else
                   'FIXED_TAIL_SWAP_REVIEW_REQUIRED' if classified_only else 'UNSUPPORTED_DRIFT'),
        'chain_scope_only': True, 'capture_freshness_verified': False,
        'full_verifier_pass': False, 'runtime_go': False,
        'ac04_accepted': False, 'runtime_changed': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-state', required=True)
    parser.add_argument('--original-sha256', required=True)
    parser.add_argument('--current-state', required=True)
    args = parser.parse_args(argv)
    try:
        result = analyze(read_bounded(args.original_state),
                         read_bounded(args.current_state), args.original_sha256)
    except AnalysisError as error:
        result = {'schema': 'HBR-AC04-offline-docker-chain-analysis-1',
                  'status': 'INCOMPLETE', 'error': str(error),
                  'full_verifier_pass': False, 'runtime_go': False,
                  'ac04_accepted': False, 'runtime_changed': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'EXACT_DOCKER_CHAINS_ONLY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
