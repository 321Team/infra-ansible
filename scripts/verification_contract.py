"""Strict, Ansible-independent validation and public CLI process capture."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import uuid

SCHEMA = 1
ENGINES = ('2.16.19', '2.21.3')
NODES = tuple('k8s-' + kind + f'{number:02}' for kind in ('control', 'worker') for number in (1, 2, 3))
COUNTERS = ('ok', 'changed', 'unreachable', 'failed', 'skipped', 'rescued', 'ignored')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def decode(text):
    return json.loads(text, object_pairs_hook=strict_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))


def source_sha(root):
    def git(*args):
        try:
            return subprocess.check_output(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                                            '-C', str(root), *args], text=True, stderr=subprocess.PIPE).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('Cannot read source Git metadata') from exc
    if Path(git('rev-parse', '--show-toplevel')).resolve() != Path(root).resolve():
        raise ValueError('Source must be the Git repository root')
    sha = git('rev-parse', 'HEAD')
    if not re.fullmatch('[0-9a-f]{40}', sha) or git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('A clean Git checkout is required for source attribution')
    return sha


def context(code_sha, engine, stage_id, *, run_id=None):
    if engine not in ENGINES or not re.fullmatch('[0-9a-f]{40}', code_sha):
        raise ValueError('Invalid engine or code SHA')
    return {'schema_version': SCHEMA, 'run_id': run_id or str(uuid.uuid4()),
            'code_sha': code_sha, 'engine': engine, 'stage_id': stage_id}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(stream, metadata, nodes, *, cli_rc, timed_out=False,
             allowed_changes=(0,), require_ssh=False, expected_negative=False):
    """Return REVIEW_REQUIRED for every unknown/malformed/incomplete outcome."""
    report = {**metadata, 'expected_nodes': sorted(nodes), 'completed': False,
              'cli_rc': cli_rc, 'timed_out': timed_out, 'status': 'REVIEW_REQUIRED',
              'expected_negative': expected_negative, 'nodes': [],
              'expected_changed_per_node': list(allowed_changes), 'errors': []}
    try:
        require(type(cli_rc) is int and cli_rc == 0 and not timed_out, 'CLI did not complete successfully')
        require(len(nodes) == 6 and len(set(nodes)) == 6, 'Expected node contract must contain six unique nodes')
        require(Path(stream).stat().st_size <= 32 * 1024 * 1024, 'Event stream exceeds size limit')
        text = Path(stream).read_text(encoding='utf-8')
        require(text.endswith('\n'), 'Truncated event stream')
        events = [decode(line) for line in text.splitlines()]
        require(len(events) >= 3, 'Missing callback events')
        require(all(type(e) is dict and type(e.get('seq')) is int and e['seq'] == i
                    for i, e in enumerate(events)), 'Missing, duplicate, or unordered events')
        require(events[0] == {'type': 'start', 'seq': 0, **metadata}, 'Callback identity mismatch')
        require(type(events[0]['schema_version']) is int, 'Invalid schema version type')
        end = events[-1]
        require(end.get('type') == 'complete' and end.get('completed') is True, 'Missing completion event')
        stats = end['nodes']
        require(type(stats) is list and len(stats) == 6, 'Missing or duplicate node summaries')
        require(sorted(row['host'] for row in stats) == sorted(nodes), 'Unexpected node set')
        require(all(type(row[k]) is int and row[k] >= 0 for row in stats for k in COUNTERS), 'Invalid recap counter')
        report['nodes'] = [{k: row[k] for k in ('host', *COUNTERS)} for row in stats]
        counts = {n: {'completion': 0, 'ssh': 0, 'negative': 0, 'tasks': 0, 'changed': 0} for n in nodes}
        seen = set()
        for event in events[1:-1]:
            require(event.get('type') == 'task', 'Unexpected event type')
            host = event['host']
            require(host in counts, 'Unexpected event host')
            token = (host, event['task_id'])
            require(type(event['task_id']) is str and event['task_id'] and token not in seen, 'Duplicate task result')
            seen.add(token)
            require(event['outcome'] in ('ok', 'failed', 'unreachable', 'skipped'), 'Unknown task outcome')
            require(type(event['action']) is str and event['action'], 'Missing task action')
            require(type(event['ignored']) is bool and type(event['expected_failure']) is bool and
                    type(event['no_log']) is bool, 'Invalid event flags')
            require(not event['no_log'], 'Censored result cannot establish this verification contract')
            negative = expected_negative and event['expected_failure']
            require(not event['expected_failure'] or negative, 'Unexpected negative-test marker')
            for obs in [event, *event.get('items', [])]:
                require(type(obs) is dict, 'Invalid loop item')
                require(type(obs['changed']) is bool and type(obs['failed']) is bool, 'Invalid result flags')
                require(obs['condition'] is None or type(obs['condition']) is bool, 'Expression evaluation error')
                require(obs['rc'] is None or type(obs['rc']) is int, 'Invalid command rc')
                if not negative:
                    require(obs['rc'] in (None, 0), 'Nonzero command rc')
                    require(not obs['failed'] and obs['condition'] is not True, 'Task failure')
            if event['outcome'] != 'skipped' and event['action'].split('.')[-1] in ('command', 'shell', 'raw'):
                command_results = event.get('items', [event])
                require(bool(command_results) and all(type(obs['rc']) is int for obs in command_results), 'Missing command rc')
            counts[host]['changed'] += int(event['changed'])
            if negative:
                # Core sanitizes the callback payload's redundant `failed` key.
                # The failed hook supplies the outcome; the raw flag stays an
                # observation, not an additional proof requirement.
                require(event['outcome'] == 'failed' and event['ignored'] and event['rc'] == 7 and
                        event['condition'] is True and event['action'] == 'ansible.builtin.command' and
                        'items' not in event,
                        'Expected failure was not proven')
                counts[host]['negative'] += 1
            else:
                require(event['outcome'] in ('ok', 'skipped') and not event['ignored'], 'Failure, ignored error, or unreachable node')
            if event['outcome'] == 'ok':
                counts[host]['tasks'] += 1
            if 'completion' in event:
                require(event['outcome'] == 'ok' and event['completion'] == {
                    'run_id': metadata['run_id'], 'stage_id': metadata['stage_id'], 'completed': True}, 'Invalid node completion')
                require(event['completion']['completed'] is True, 'Invalid completion type')
                counts[host]['completion'] += 1
            if 'ssh_verified' in event:
                proof = event['ssh_verified']
                require(event['outcome'] == 'ok' and proof == {'host': host, 'effective_user': 'root',
                    'managed_key_count': 1, 'restricted_key_count': 1, 'authorized_keys_unchanged': True}, 'Invalid SSH proof')
                require(type(proof['managed_key_count']) is int and type(proof['restricted_key_count']) is int,
                        'SSH counts must be integers')
                require(proof['authorized_keys_unchanged'] is True, 'Invalid unchanged-file proof type')
                counts[host]['ssh'] += 1
        for row in stats:
            require(all(type(row[k]) is int and row[k] >= 0 for k in COUNTERS), 'Invalid recap counter')
            require(row['ok'] > 1 and row['changed'] in allowed_changes, 'Missing work or unexpected change count')
            require(row['failed'] == row['unreachable'] == row['rescued'] == 0, 'Failed, unreachable, or rescued work')
            require(row['ignored'] == int(expected_negative), 'Unexpected ignored count')
            count = counts[row['host']]
            require(row['changed'] == count['changed'], 'Task and summary change counts disagree')
            require(count['tasks'] > 1 and count['completion'] == 1, 'Missing or duplicate node completion')
            require(count['negative'] == int(expected_negative), 'Missing or duplicate negative proof')
            require(count['ssh'] == int(require_ssh), 'Missing, duplicate, or unexpected SSH proof')
        report.update(completed=True, nodes=stats,
                      status='EXPECTED_FAILURE_CONFIRMED' if expected_negative else 'PASS')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Do not include malformed source content in diagnostics.
        report['errors'] = [str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
                            else type(exc).__name__]
    return report


def capture(command, cwd, env, timeout):
    """Preserve stdout/stderr bytes, including timeout output; stop process groups."""
    try:
        process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=os.name == 'posix')
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return process.returncode, False, stdout, stderr
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            stdout, stderr = process.communicate()
            return 124, True, stdout, stderr
    except OSError:
        return 127, False, b'', b'Unable to start verification process.\n'


def stage(command, root, directory, env, metadata, nodes=NODES, *, timeout=600,
          allowed_changes=(0,), require_ssh=False, expected_negative=False):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / 'context.json', metadata)
    child = env.copy()
    # Empty strings are not "disabled": old core resolves log_path to cwd,
    # while new core interprets an empty callback list as a blank plugin name.
    child.pop('ANSIBLE_CALLBACKS_ENABLED', None)
    child.pop('ANSIBLE_LOG_PATH', None)
    child.update(ANSIBLE_STDOUT_CALLBACK='fds_verification',
                 ANSIBLE_CALLBACK_PLUGINS=str(Path(root) / 'callback_plugins'),
                 FDS_VERIFICATION_CONTEXT=str(directory / 'context.json'),
                 FDS_VERIFICATION_OUTPUT=str(directory / 'events.jsonl'))
    rc, timed_out, stdout, stderr = capture(command, root, child, timeout)
    (directory / 'stdout.log').write_bytes(stdout)
    (directory / 'stderr.log').write_bytes(stderr)
    report = validate(directory / 'events.jsonl', metadata, nodes, cli_rc=rc, timed_out=timed_out,
                      allowed_changes=allowed_changes, require_ssh=require_ssh, expected_negative=expected_negative)
    report['origin'] = {'kind': 'ansible-playbook callback', 'command': [str(x) for x in command],
                        'cwd': str(root), 'artifacts': {p.name: digest(p) for p in directory.iterdir() if p.is_file()}}
    write_json(directory / 'report.json', report)
    return report


def completion_play(metadata, hosts='k8s_nodes'):
    return {'name': 'Record verification scope completion', 'hosts': hosts, 'gather_facts': False,
            'become': False, 'tasks': [{'name': 'Record completed node', 'tags': ['fds_stage_complete'],
                'ansible.builtin.debug': {'msg': {'run_id': metadata['run_id'], 'stage_id': metadata['stage_id'], 'completed': True}}}]}


def runtime_command(python, root, engine):
    pins = [line for line in (Path(root) / 'tests' / ('requirements-verification-' + engine + '.txt')).read_text().splitlines()
            if line and not line.startswith('#')]
    probe = ('import importlib.metadata as m,json,sys; pins=json.loads(sys.argv[1]); '
             'actual={p.split("==")[0]:m.version(p.split("==")[0]) for p in pins}; '
             'print(json.dumps({"python":sys.version,"packages":actual})); '
             'assert sys.version_info[:2] == (3,12); '
             'assert all(actual[p.split("==")[0]]==p.split("==")[1] for p in pins)')
    return [python, '-I', '-c', probe, json.dumps(pins)]


def clean_environment(root, output):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ANSIBLE_', 'FDS_VERIFICATION_', 'PR3_REVIEW_'))
           and k not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(ANSIBLE_CONFIG=str(Path(root) / 'ansible.cfg'), ANSIBLE_NOCOLOR='1',
               PYTHONDONTWRITEBYTECODE='1', ANSIBLE_HOST_KEY_CHECKING='True',
               ANSIBLE_SSH_ARGS='-C -o ControlMaster=no -o ControlPersist=no -o ControlPath=none',
               ANSIBLE_SSH_USETTY='False', ANSIBLE_LOCAL_TEMP=str(Path(output) / 'ansible-local'),
               ANSIBLE_DISPLAY_ARGS_TO_STDOUT='False', ANSIBLE_DIFF_ALWAYS='False')
    return env
