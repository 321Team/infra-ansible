"""Shared matrix identities; fail closed on missing, duplicate or extra rows."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verification_contract import ENGINES
from ssh_guard_fixtures import cases, NAMES

CONTRACT_CLI_CASES = ('baseline', 'wording', 'serial', 'ssh_proof', 'ssh_proof_wrong_count',
    'expected_negative', 'expected_expression', 'failure', 'ignored', 'rescued',
    'expression', 'hidden_rc', 'changed', 'transport_error', 'limited_nodes', 'timeout')
EVENT_MUTATIONS = ('missing_complete', 'missing_node', 'duplicate_node', 'wrong_node', 'missing_marker',
    'duplicate_result', 'sequence_gap', 'wrong_code', 'wrong_engine', 'wrong_stage')
DERIVED_CASES = (*EVENT_MUTATIONS, 'truncated', 'duplicate_key', 'whitespace')
GUARD_MUTATIONS = ('and', 'broken-list', 'undefined')
GUARD_VARIANTS = ('baseline', *(f'{kind}-{index}' for index in range(len(NAMES)) for kind in GUARD_MUTATIONS))

def guard_case_count():
    return len(list(cases()))

def complete_matrix(rows, variants, field):
    expected = {(engine, case) for engine in ENGINES for case in variants}
    if not isinstance(rows, list) or len(rows) != len(expected):
        return False
    observed = []
    for row in rows:
        if not isinstance(row, dict) or row.get('passed') is not True:
            return False
        identity = (row.get('engine'), row.get(field))
        if not all(isinstance(x, str) for x in identity):
            return False
        observed.append(identity)
    return len(set(observed)) == len(observed) and set(observed) == expected

def complete_guards(rows):
    return complete_matrix(rows, GUARD_VARIANTS, 'variant')

def complete_contract(rows):
    return complete_matrix(rows, (*CONTRACT_CLI_CASES, *('derived-' + n for n in DERIVED_CASES)), 'case')
