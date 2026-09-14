"""Allowlisted callback event stream; never serialize module output or task args."""
import json
from pathlib import Path

from ansible.plugins.callback import CallbackBase
from ansible.release import __version__

DOCUMENTATION = r'''
name: fds_verification
type: stdout
short_description: Write the versioned FDS verification event stream
description:
  - Emits task counters and completion markers without module output or arguments.
  - The caller independently validates the stream and CLI exit status.
options:
  context:
    description: Path to the caller-created context JSON.
    type: path
    required: true
    env:
      - name: FDS_VERIFICATION_CONTEXT
  output:
    description: New event stream path; existing files are rejected.
    type: path
    required: true
    env:
      - name: FDS_VERIFICATION_OUTPUT
'''


def fields(result):
    # Match each pinned engine's shipped callback interface. No expression API.
    if __version__ == '2.21.3':
        return result.host, result.task, result.result
    if __version__ == '2.16.19':
        return result._host, result._task, result._result
    raise ValueError('Unsupported verification engine')


def observation(data):
    condition = data.get('failed_when_result')
    return {'rc': data.get('rc'), 'changed': data.get('changed', False),
            'failed': data.get('failed', False),
            'condition': condition if type(condition) is bool or condition is None else 'invalid'}


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'stdout'
    CALLBACK_NAME = 'fds_verification'

    def __init__(self):
        super().__init__()
        self.stream = None
        self.sequence = 0

    def emit(self, event):
        event['seq'] = self.sequence
        self.sequence += 1
        self.stream.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + '\n')
        self.stream.flush()

    def v2_playbook_on_start(self, playbook):
        context = json.loads(Path(self.get_option('context')).read_text(encoding='utf-8'))
        self.stream = Path(self.get_option('output')).open('x', encoding='utf-8', newline='\n')
        self.emit({'type': 'start', 'schema_version': 1, 'engine': __version__,
                   **{k: context[k] for k in ('run_id', 'code_sha', 'stage_id')}})

    def record(self, result, outcome, ignore_errors=False):
        host, task, data = fields(result)
        tags = set(task.tags)
        event = {'type': 'task', 'host': host.get_name(), 'task_id': str(task._uuid),
                 'action': task.action, 'outcome': outcome, 'ignored': bool(ignore_errors),
                 'expected_failure': 'fds_expected_failure' in tags,
                 'no_log': bool(data.get('_ansible_no_log', False)), **observation(data)}
        if 'results' in data:
            event['items'] = [observation(item) for item in data['results']]
        # Only these two known message contracts can leave the callback.
        if 'fds_stage_complete' in tags or 'fds_ssh_verified' in tags:
            message = data.get('msg')
            if isinstance(message, dict) and not event['no_log']:
                if 'fds_stage_complete' in tags:
                    event['completion'] = {k: message.get(k) for k in ('run_id', 'stage_id', 'completed')}
                if 'fds_ssh_verified' in tags:
                    event['ssh_verified'] = {k: message.get(k) for k in
                        ('host', 'effective_user', 'managed_key_count', 'restricted_key_count', 'authorized_keys_unchanged')}
        self.emit(event)
        self._display.display('%s: %s' % (host.get_name(), outcome))

    def v2_runner_on_ok(self, result):
        self.record(result, 'ok')

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self.record(result, 'failed', ignore_errors)

    def v2_runner_on_unreachable(self, result):
        self.record(result, 'unreachable')

    def v2_runner_on_skipped(self, result):
        self.record(result, 'skipped')

    def v2_playbook_on_stats(self, stats):
        nodes = []
        for host in sorted(stats.processed):
            raw = stats.summarize(host)
            nodes.append({'host': host, **{k: raw[k] for k in
                         ('ok', 'changed', 'unreachable', 'skipped', 'rescued', 'ignored')},
                          'failed': raw['failures']})
        self.emit({'type': 'complete', 'completed': True, 'nodes': nodes})
        self.stream.close()
