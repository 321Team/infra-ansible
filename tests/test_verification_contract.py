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


def expected_negative():
    data = baseline()
    for event in data:
        if event.get('task_id') == 'work':
            # Both real pinned callbacks omit `failed` from the result payload.
            # The adapter preserves that as False; the hook still says failed.
            event.update(action='ansible.builtin.command', outcome='failed', ignored=True,
                         expected_failure=True, rc=7, condition=True, failed=False)
    for host in NODES:
        template = next(e for e in data if e.get('host') == host and e.get('task_id') == 'done')
        extra = {k: v for k, v in template.items() if k != 'completion'}
        extra['task_id'] = 'positive'
        data.insert(-1, extra)
    for row in data[-1]['nodes']:
        row['ignored'] = 1
    for index, event in enumerate(data):
        event['seq'] = index
    return data


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
        for raw_failed in (False, True):
            data = expected_negative()
            for event in data:
                if event.get('expected_failure'):
                    event['failed'] = raw_failed
            with self.subTest(raw_failed=raw_failed):
                self.assertEqual(self.check_events(data)['status'], 'REVIEW_REQUIRED')
                self.assertEqual(self.check_events(data, expected_negative=True)['status'], 'EXPECTED_FAILURE_CONFIRMED')

    def test_expected_negative_rejects_wrong_or_incomplete_proof(self):
        for key, value in [('outcome', 'ok'), ('outcome', 'unreachable'), ('ignored', False),
                           ('expected_failure', False), ('rc', 0), ('rc', 8), ('rc', None),
                           ('rc', '7'), ('condition', False), ('condition', None), ('condition', 'invalid'),
                           ('condition', 1), ('failed', None), ('failed', 'false'), ('no_log', True),
                           ('action', 'ansible.builtin.debug'), ('items', []),
                           ('items', [{'rc': 7, 'changed': False, 'failed': True, 'condition': True}])]:
            data = expected_negative()
            data[1][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(self.check_events(data, expected_negative=True)['status'], 'REVIEW_REQUIRED')
        for counter in ('ignored', 'failed', 'unreachable', 'rescued'):
            data = expected_negative()
            data[-1]['nodes'][0][counter] = 2
            with self.subTest(counter=counter):
                self.assertEqual(self.check_events(data, expected_negative=True)['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.check_events(expected_negative(), cli_rc=2, expected_negative=True)['status'], 'REVIEW_REQUIRED')
        self.assertEqual(self.check_events(expected_negative(), timed_out=True, expected_negative=True)['status'], 'REVIEW_REQUIRED')

    def test_ssh_proof_not_stdout_word_count(self):
        data = baseline()
        for event in data:
            if event.get('task_id') == 'work':
                event['ssh_verified'] = {'host': event['host'], 'effective_user': 'root', 'managed_key_count': 1,
                                         'restricted_key_count': 1, 'authorized_keys_unchanged': True}
        self.assertEqual(self.check_events(data, require_ssh=True)['status'], 'PASS')
        for field in ('managed_key_count', 'restricted_key_count'):
            for wrong in ('1', '01', ' 1 ', '1\n', True, 1.0, None, 0, 2):
                mutated = copy.deepcopy(data)
                mutated[1]['ssh_verified'][field] = wrong
                with self.subTest(field=field, wrong=wrong):
                    self.assertEqual(self.check_events(mutated, require_ssh=True)['status'], 'REVIEW_REQUIRED')

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
        self.assertNotIn('ANSIBLE_LOG_PATH', env)
        self.assertNotIn('ANSIBLE_CALLBACKS_ENABLED', env)

    def test_blank_or_inherited_settings_do_not_reach_real_child(self):
        for inherited in ('', 'unexpected-override'):
            with self.subTest(inherited=inherited), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'stage'
                env = {**os.environ, 'ANSIBLE_LOG_PATH': inherited, 'ANSIBLE_CALLBACKS_ENABLED': inherited}
                command = [sys.executable, '-c',
                           'import os,json; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith(("ANSIBLE_", "FDS_VERIFICATION_"))}))']
                report = stage(command, ROOT, output, env, META)
                child = json.loads((output / 'stdout.log').read_text())
                self.assertNotIn('ANSIBLE_LOG_PATH', child)
                self.assertNotIn('ANSIBLE_CALLBACKS_ENABLED', child)
                self.assertEqual(child['ANSIBLE_STDOUT_CALLBACK'], 'fds_verification')
                self.assertEqual(child['FDS_VERIFICATION_CONTEXT'], str(output / 'context.json'))
                self.assertEqual(report['status'], 'REVIEW_REQUIRED')  # Python is not an Ansible callback.

    def test_cli_matrix_fixture_construction_and_derived_cases(self):
        spec = importlib.util.spec_from_file_location('contract_matrix', ROOT / 'tests/run-verification-contract-matrix.py')
        suite = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(suite)
        for case in ('baseline', 'wording', 'serial', 'ssh_proof', 'ssh_proof_wrong_count',
                     'expected_negative', 'expected_expression', 'failure', 'ignored', 'rescued',
                     'expression', 'hidden_rc', 'changed', 'transport_error', 'limited_nodes', 'timeout'):
            plays = suite.make_play(case, Path('/fixture/python'), META)
            self.assertEqual(plays[0]['connection'], 'local')
            self.assertFalse(plays[0]['become'])
            self.assertFalse(plays[0]['gather_facts'])
            self.assertEqual(plays[-1]['tasks'][0]['tags'], ['fds_stage_complete'])
            if case in ('ssh_proof', 'ssh_proof_wrong_count'):
                self.assertEqual(plays[0]['tasks'][-1], suite.ssh_proof_task())
                self.assertEqual(plays[0]['vars']['p1_managed_key_count']['stdout'],
                                 '2\n' if case == 'ssh_proof_wrong_count' else '1\n')
        mutations = list(suite.corruptions(baseline()))
        self.assertEqual(len(mutations), 13)
        for name, raw in mutations:
                self.assertEqual(self.check_events(raw=raw)['status'], 'PASS' if name == 'whitespace' else 'REVIEW_REQUIRED')

    def test_ssh_proof_fixture_extracts_current_source(self):
        spec = importlib.util.spec_from_file_location('contract_matrix', ROOT / 'tests/run-verification-contract-matrix.py')
        suite = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(suite)
        original = suite.ssh_proof_task()
        # Mutating the source must also mutate the generated fixture: it cannot
        # silently test a separate hard-coded proof while real-node output drifts.
        changed = copy.deepcopy(original)
        changed['ansible.builtin.debug']['msg'] = {'host': '{{ inventory_hostname }}', 'managed_key_count': '{{ 1 | int }}'}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'tests/ssh-server-readonly.yml'
            source.parent.mkdir()
            for tasks in ([changed], [], [changed, changed]):
                source.write_text(suite.yaml.safe_dump([{'tasks': tasks}]), encoding='utf-8')
                with patch.object(suite, 'ROOT', Path(directory)):
                    if len(tasks) == 1:
                        fixture = suite.make_play('ssh_proof', Path('/fixture/python'), META)
                        self.assertEqual(fixture[0]['tasks'][-1], changed)
                    else:
                        with self.assertRaises(ValueError):
                            suite.ssh_proof_task()


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
                    # Model the actual sanitized failed callback payload, with
                    # no `failed` key. The failed hook must remain authoritative.
                    task.tags = ['fds_expected_failure']
                    task.action = 'ansible.builtin.command'
                    raw.update(rc=7, changed=False, failed_when_result=True)
                    callback.v2_runner_on_failed(result, ignore_errors=True)
                    callback.v2_playbook_on_stats(SimpleNamespace(processed={'fixture-1': 1}, summarize=lambda _: {
                        'ok': 1, 'changed': 0, 'unreachable': 0, 'failures': 0, 'skipped': 0, 'rescued': 0, 'ignored': 0}))
                text = (root / 'events.jsonl').read_text(encoding='utf-8')
                self.assertNotIn('DO_NOT_EXPORT', text)
                self.assertEqual(decode(text.splitlines()[0]), {'type': 'start', 'seq': 0, **meta})
                negative = decode(text.splitlines()[2])
                self.assertEqual({k: negative[k] for k in ('outcome', 'ignored', 'expected_failure', 'rc', 'failed', 'condition')},
                                 {'outcome': 'failed', 'ignored': True, 'expected_failure': True,
                                  'rc': 7, 'failed': False, 'condition': True})
                with self.assertRaises(FileExistsError):
                    callback.v2_playbook_on_start(None)


if __name__ == '__main__':
    unittest.main()
