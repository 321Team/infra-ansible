"""Local-only R1/N1 validation. No GitHub calls or real alert execution."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--bash', required=True)
p.add_argument('--yaml-path', type=Path)
a = p.parse_args()
if a.yaml_path:
    sys.path.insert(0, str(a.yaml_path.resolve()))
import yaml

BASE = 'bd1e7876382eab9c0df322a8a4d44546d2d8fd94'
repo = a.repo.resolve()
workflow = '.github/workflows/ansible-queue-alert.yml'
runbook = 'docs/runbooks/Ansible-CI-Queue-Alert.md'

def old(path):
    return subprocess.run(['git', 'show', BASE + ':' + path], cwd=repo,
                          capture_output=True, check=True).stdout

def sha(data):
    return hashlib.sha256(data).hexdigest()

before = yaml.load(old(workflow), Loader=yaml.BaseLoader)
after = yaml.load((repo / workflow).read_bytes(), Loader=yaml.BaseLoader)
normalized = copy.deepcopy(after)
normalized['on']['schedule'] = before['on']['schedule']
cases = []
values = [('1', True), ('10', True), ('1440', True), ('0010', True), ('0001', True),
          ('', False), (' ', False), ('0', False), ('0000', False), ('1441', False),
          ('9999', False), ('10000', False), ('-1', False), ('1.5', False), ('x', False),
          ('$(exit 99)', False), ('1\n2', False), ('１２', False),
          ('1; echo injected', False), ('999999999999999999999999999999', False)]
stub = 'python3() { printf "%s\\n" MOCK_PYTHON_CALLED; printf "ARG=%s\\n" "$@"; }\n'
for name in ('dry-read', 'notify'):
    steps = after['jobs'][name]['steps']
    indices = [i for i, step in enumerate(steps) if 'run' in step]
    assert len(indices) == 1
    idx = indices[0]
    block = steps[idx]['run']
    # Everything except the added guard and cron must remain identical.
    old_block = before['jobs'][name]['steps'][idx]['run']
    assert block.splitlines()[0] == old_block.splitlines()[0]
    assert block.splitlines()[-1] == old_block.splitlines()[-1]
    normalized['jobs'][name]['steps'][idx]['run'] = old_block
    syntax = subprocess.run([a.bash, '--noprofile', '--norc', '-n'],
                            input=block.encode(), capture_output=True)
    assert syntax.returncode == 0, syntax.stderr
    for value, valid in values:
        env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP') if k in os.environ}
        env.update(PATH=str(Path(a.bash).parent), ALERT_THRESHOLD=value,
                   RUNNER_TEMP='/mock/runner', MSYS_NO_PATHCONV='1')
        result = subprocess.run([a.bash, '--noprofile', '--norc', '-s'], cwd=repo,
                                input=(stub + block).encode(), env=env,
                                capture_output=True, timeout=10)
        out = result.stdout.decode('utf-8')
        err = result.stderr.decode('utf-8')
        assert not err, (name, value, err)
        if valid:
            expected = ['MOCK_PYTHON_CALLED', 'ARG=-I', 'ARG=-B',
                        'ARG=tools/ansible-ci-queue-alert.py', 'ARG=--threshold-minutes',
                        'ARG=' + value, 'ARG=--output', 'ARG=/mock/runner/queue-observation.json']
            if name == 'notify':
                expected.append('ARG=--notify')
            assert result.returncode == 0 and out.splitlines() == expected, (name, value, out)
        else:
            assert result.returncode == 2 and 'MOCK_PYTHON_CALLED' not in out, (name, value, out)
            assert out == ('::error title=Queue alert configuration::'
                           'ANSIBLE_QUEUE_ALERT_THRESHOLD_MINUTES must be set to an integer from 1 to 1440.\n')
        cases.append(dict(job=name, synthetic_threshold=value, expected_valid=valid,
                          rc=result.returncode, status='PASS'))
assert normalized == before, 'Permissions, triggers, actions or notification command changed'

cron = after['on']['schedule'][0]['cron']
assert cron == '7,37 0-14 * * *'
minute, hour, dom, month, dow = cron.split()
assert (dom, month, dow) == ('*', '*', '*')
minutes = [int(x) for x in minute.split(',')]
start, end = map(int, hour.split('-'))
kst = dt.timezone(dt.timedelta(hours=9))
utc_day = dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)
slots = [(utc_day + dt.timedelta(hours=h, minutes=m)).astimezone(kst)
         for h in range(start, end + 1) for m in minutes]
assert len(slots) == 30 and slots[0].strftime('%H:%M') == '09:07'
assert slots[-1].strftime('%H:%M') == '23:37'
assert all((b-a).total_seconds() == 1800 for a,b in zip(slots, slots[1:]))
night_gap_minutes = ((slots[0] + dt.timedelta(days=1)) - slots[-1]).total_seconds() / 60
assert night_gap_minutes == 570

reused = []
for path in ('tools/ansible-ci-queue-alert.py', 'tools/ansible-ci-queue-watch.py',
             'tests/test_runner_queue_alert.py', 'tests/test_runner_queue_watch.py',
             'docs/runbooks/Ansible-CI-Operator-Card.md'):
    current = (repo / path).read_bytes()
    assert current == old(path), path
    reused.append(dict(path=path, sha256=sha(current)))
receipt = json.loads((repo / 'docs/change/validation/runner-queue-alert-20261013/runner-alert-validation.json').read_text())
for entry in receipt['files']:
    assert sha(old(entry['path'])) == entry['sha256']
frozen_dir = 'docs/change/validation/runner-queue-alert-20261013'
for path in (repo / frozen_dir).iterdir():
    if path.is_file():
        assert path.read_bytes() == old(path.relative_to(repo).as_posix())

result = dict(at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), scope='LOCAL_STATIC_AND_BASH_MOCK',
              base_head=BASE, status='PASS', syntax_blocks=2, bash_cases=cases,
              security_structure_preserved=True, notification_core_unchanged=True,
              schedule=dict(cron_utc=cron, first_kst='09:07', last_kst='23:37', daily_slots=len(slots),
                            night_gap_minutes=night_gap_minutes, assumed_minutes_per_job=1,
                            minutes_30_days=len(slots)*30, minutes_14_full_days=len(slots)*14,
                            remaining_org_allowance='NOT_VERIFIED'),
              reused_tests=dict(count=49, skipped=0, rerun=False,
                                source='docs/change/validation/runner-queue-alert-20261013/runner-alert-validation.json',
                                note='Unchanged alert/watch tests and core; prior Windows MOCK plus independent Linux review. Not CI.'),
              unchanged_files=reused,
              changed_files=[dict(path=x,sha256=sha((repo/x).read_bytes())) for x in (workflow,runbook)],
              github_calls=0, real_python_alert_calls=0, runtime='NOT_EXECUTED')
with a.output.open('x', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(json.dumps(dict(status='PASS', bash_cases=len(cases), syntax_blocks=2,
                     schedule=result['schedule'], existing_49_tests='REUSED_NOT_RERUN'), ensure_ascii=False))
