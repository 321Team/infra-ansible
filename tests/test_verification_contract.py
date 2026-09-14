"""Synthetic contract and process tests; not a real Ansible engine result."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verification_contract import NODES, capture, clean_environment, context, decode, stage, validate

META = context('a' * 40, '2.16.19', 'fixture', run_id='fixture-run')


def baseline():
    events = [{'type': 'start', **META}]
    for host in NODES:
        common = {'type': 'task', 'host': host, 'action': 'ansible.builtin.debug', 'outcome': 'ok',
                  'ignored': False, 'expected_failure': False, 'no_log': False,
                  'rc': None, 'changed': False, 'failed': False, 'condition': None}
        events.append({**common, 'task_id': 'work'})
        events.append({**common, 'task_id': 'done', 'completion': {
            'run_id': META['run_id'], 'stage_id': META['stage_id'], 'completed': True}})
    events.append({'type': 'complete', 'completed': True, 'nodes': [
        {'host': host, 'ok': 2, 'changed': 0, 'failed': 0, 'unreachable': 0,
         'skipped': 0, 'rescued': 0, 'ignored': 0} for host in NODES]})
    for index, event in enumerate(events):
        event['seq'] = index
    return events


class ContractTests(unittest.TestCase):
    def check_events(self, events=None, *, raw=None, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            path.write_text(raw if raw is not None else ''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
            return validate(path, META, NODES, cli_rc=kwargs.pop('cli_rc', 0), **kwargs)

    def test_complete_success_and_whitespace(self):
        data = baseline()
        self.assertEqual(self.check_events(data)['status'], 'PASS')
        raw = ''.join('  ' + json.dumps(e, separators=(',  ', ' : ')) + ' \n' for e in data)
        self.assertEqual(self.check_events(raw=raw)['status'], 'PASS')

    def test_identity_cannot_be_relabelled(self):
        for key, wrong in [('schema_version', 2), ('schema_version', True), ('engine', '2.21.3'), ('code_sha', 'b' * 40),
                           ('stage_id', 'other'), ('run_id', 'stale')]:
            data = baseline()
            data[0][key] = wrong
            with self.subTest(key=key):
                self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')

    def test_node_and_completion_mutations(self):
        mutations = {
            'missing_node': lambda x: x[-1]['nodes'].pop(),
            'duplicate_node': lambda x: x[-1]['nodes'].__setitem__(0, x[-1]['nodes'][1]),
            'wrong_node': lambda x: x[-1]['nodes'][0].update(host='unexpected'),
            'unknown_event_host': lambda x: x[1].update(host='unexpected'),
            'missing_marker': lambda x: x[2].pop('completion'),
            'duplicate_marker': lambda x: x[1].update(completion=x[2]['completion']),
            'false_marker': lambda x: x[2]['completion'].update(completed=False),
            'integer_marker': lambda x: x[2]['completion'].update(completed=1),
            'wrong_marker': lambda x: x[2]['completion'].update(stage_id='other'),
            'duplicate_task': lambda x: x[2].update(task_id=x[1]['task_id']),
            'missing_work': lambda x: x[-1]['nodes'][0].update(ok=1),
            'incomplete': lambda x: x[-1].update(completed=False),
            'sequence_gap': lambda x: x[1].update(seq=55),
            'unexpected_type': lambda x: x[1].update(type='complete'),
        }
        for name, mutate in mutations.items():
            data = baseline()
            mutate(data)
            with self.subTest(name=name):
                self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')

    def test_bad_types_failures_and_counts(self):
        for key, value in [('failed', True), ('ignored', True), ('no_log', True), ('condition', 'invalid'),
                           ('rc', 1), ('rc', False), ('changed', 'false'), ('outcome', 'failed'),
                           ('outcome', 'unreachable'), ('expected_failure', True)]:
            data = baseline()
            data[1][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')
        for counter in ('failed', 'unreachable', 'rescued', 'ignored', 'changed'):
            data = baseline()
            data[-1]['nodes'][0][counter] = 1
            self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')
        data = baseline()
        data[-1]['nodes'][0]['failed'] = False
        self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')

    def test_expected_change_counts_match_events(self):
        data = baseline()
        data[1]['changed'] = True
        data[-1]['nodes'][0]['changed'] = 1
        self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.check_events(data, allowed_changes=(0, 1))['status'], 'PASS')
        data[-1]['nodes'][0]['changed'] = 0
        self.assertEqual(self.check_events(data, allowed_changes=(0, 1))['status'], 'REVIEW_REQUIRED')

    def test_command_and_loop_rc_are_required(self):
        data = baseline()
        data[1]['action'] = 'ansible.builtin.command'
        self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')
        data[1]['rc'] = 0
        self.assertEqual(self.check_events(data)['status'], 'PASS')
        data[1]['items'] = []
        self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')
        data[1]['items'] = [{'rc': 8, 'failed': False, 'changed': False, 'condition': False}]
        self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')

    def test_expected_negative_requires_exact_proof(self):
        data = baseline()
        for event in data:
            if event.get('task_id') == 'work':
                event.update(outcome='failed', ignored=True, expected_failure=True, rc=7, condition=True, failed=True)
                # A second successful task is required in addition to completion.
        for host in NODES:
            template = next(e for e in data if e.get('host') == host and e.get('task_id') == 'done')
            extra = {k: v for k, v in template.items() if k != 'completion'}
            extra['task_id'] = 'positive'
            data.insert(-1, extra)
        for row in data[-1]['nodes']:
            row['ignored'] = 1
        for index, event in enumerate(data):
            event['seq'] = index
        self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.check_events(data, expected_negative=True)['status'], 'EXPECTED_FAILURE_CONFIRMED')
        data[1]['condition'] = 'invalid'
        self.assertEqual(self.check_events(data, expected_negative=True)['status'], 'REVIEW_REQUIRED')

    def test_ssh_proof_not_stdout_word_count(self):
        data = baseline()
        for event in data:
            if event.get('task_id') == 'work':
                event['ssh_verified'] = {'host': event['host'], 'effective_user': 'root', 'managed_key_count': 1,
                                         'restricted_key_count': 1, 'authorized_keys_unchanged': True}
        self.assertEqual(self.check_events(data, require_ssh=True)['status'], 'PASS')
        data[1]['ssh_verified']['managed_key_count'] = True
        self.assertEqual(self.check_events(data, require_ssh=True)['status'], 'REVIEW_REQUIRED')

    def test_incomplete_malformed_and_duplicate_json(self):
        raw = ''.join(json.dumps(e) + '\n' for e in baseline())
        for bad in [raw[:-1], raw[:-50], '', '{}\n', raw.replace('"seq": 0', '"seq": 0, "seq": 0'),
                    raw.replace('"changed": 0', '"changed": NaN')]:
            self.assertEqual(self.check_events(raw=bad)['status'], 'REVIEW_REQUIRED')
        with self.assertRaises(ValueError):
            decode('{"a":1,"a":2}')

    def test_nonzero_and_timeout_override_success_stream(self):
        self.assertEqual(self.check_events(baseline(), cli_rc=2)['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.check_events(baseline(), timed_out=True)['status'], 'REVIEW_REQUIRED')

    def test_real_process_bytes_exit_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, '-c', 'import os; os.write(1, bytes([255, 10])); os.write(2, b"err"); raise SystemExit(7)']
            self.assertEqual(capture(command, directory, os.environ.copy(), 10), (7, False, b'\xff\n', b'err'))
            rc, timeout, stdout, _ = capture([sys.executable, '-u', '-c', 'import time; print("partial"); time.sleep(30)'],
                                            directory, os.environ.copy(), 0.5)
            self.assertEqual((rc, timeout), (124, True))
            self.assertIn(b'partial', stdout)

    def test_success_looking_stdout_and_stale_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'stage'
            command = [sys.executable, '-c', 'print("PLAY RECAP / SSH_READONLY_PASS " * 6)']
            report = stage(command, ROOT, output, os.environ.copy(), META)
            self.assertEqual(report['status'], 'REVIEW_REQUIRED')
            self.assertIn('stdout.log', report['origin']['artifacts'])
            before = (output / 'report.json').read_bytes()
            with self.assertRaises(FileExistsError):
                stage(command, ROOT, output, os.environ.copy(), META)
            self.assertEqual((output / 'report.json').read_bytes(), before)

    def test_ambient_plugins_and_log_overrides_removed(self):
        with patch.dict(os.environ, {'ANSIBLE_CALLBACKS_ENABLED': 'other', 'ANSIBLE_LOG_PATH': 'secret',
                                     'ANSIBLE_LIMIT': 'one', 'FDS_VERIFICATION_OUTPUT': 'stale', 'PYTHONPATH': 'other'}):
            env = clean_environment(ROOT, ROOT.parent / 'output')
        self.assertNotIn('ANSIBLE_LIMIT', env)
        self.assertNotIn('FDS_VERIFICATION_OUTPUT', env)
        self.assertEqual(env['ANSIBLE_LOG_PATH'], '')

    def test_cli_matrix_fixture_construction_and_derived_cases(self):
        spec = importlib.util.spec_from_file_location('contract_matrix', ROOT / 'tests/run-verification-contract-matrix.py')
        suite = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(suite)
        for case in ('baseline', 'wording', 'serial', 'expected_negative', 'failure', 'ignored', 'rescued',
                     'expression', 'hidden_rc', 'changed', 'transport_error', 'limited_nodes', 'timeout'):
            plays = suite.make_play(case, Path('/fixture/python'), META)
            self.assertEqual(plays[0]['connection'], 'local')
            self.assertFalse(plays[0]['become'])
            self.assertFalse(plays[0]['gather_facts'])
            self.assertEqual(plays[-1]['tasks'][0]['tags'], ['fds_stage_complete'])
        mutations = list(suite.corruptions(baseline()))
        self.assertEqual(len(mutations), 13)
        for name, raw in mutations:
            self.assertEqual(self.check_events(raw=raw)['status'], 'PASS' if name == 'whitespace' else 'REVIEW_REQUIRED')


class CallbackProjectionTests(unittest.TestCase):
    def test_both_pinned_callback_interfaces_and_secret_exclusion(self):
        for engine in ('2.16.19', '2.21.3'):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                meta = {**META, 'engine': engine}
                (root / 'context.json').write_text(json.dumps(meta), encoding='utf-8')
                class Base:
                    def __init__(self):
                        self._display = SimpleNamespace(display=lambda _: None)
                    def get_option(self, name):
                        return str(root / ('context.json' if name == 'context' else 'events.jsonl'))
                modules = {'ansible': SimpleNamespace(), 'ansible.plugins': SimpleNamespace(),
                           'ansible.plugins.callback': SimpleNamespace(CallbackBase=Base),
                           'ansible.release': SimpleNamespace(__version__=engine)}
                with patch.dict(sys.modules, modules):
                    spec = importlib.util.spec_from_file_location('fixture_callback', ROOT / 'callback_plugins/fds_verification.py')
                    plugin = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(plugin)
                    callback = plugin.CallbackModule()
                    callback.v2_playbook_on_start(None)
                    host = SimpleNamespace(get_name=lambda: 'fixture-1')
                    task = SimpleNamespace(tags=[], action='ansible.builtin.debug', _uuid='id', args={'token': 'DO_NOT_EXPORT'})
                    raw = {'stdout': 'DO_NOT_EXPORT', 'stderr': 'DO_NOT_EXPORT', 'msg': 'DO_NOT_EXPORT',
                           'invocation': {'key': 'DO_NOT_EXPORT'}, 'exception': 'DO_NOT_EXPORT'}
                    result = SimpleNamespace(**(dict(host=host, task=task, result=raw) if engine == '2.21.3' else
                                                dict(_host=host, _task=task, _result=raw)))
                    callback.v2_runner_on_ok(result)
                    callback.v2_playbook_on_stats(SimpleNamespace(processed={'fixture-1': 1}, summarize=lambda _: {
                        'ok': 1, 'changed': 0, 'unreachable': 0, 'failures': 0, 'skipped': 0, 'rescued': 0, 'ignored': 0}))
                text = (root / 'events.jsonl').read_text(encoding='utf-8')
                self.assertNotIn('DO_NOT_EXPORT', text)
                self.assertEqual(decode(text.splitlines()[0]), {'type': 'start', 'seq': 0, **meta})
                with self.assertRaises(FileExistsError):
                    callback.v2_playbook_on_start(None)


if __name__ == '__main__':
    unittest.main()
