"""One-shot local-only Ansible fixtures in the operator's isolated work folder."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

root = Path(__file__).resolve().parent
assert socket.gethostname() == 'ansible01'
assert os.getuid() != 0
result = root / 'results'
result.mkdir(exist_ok=True)
records = []
stamp = lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()
def invoke(label, argv, cwd):
    start = stamp()
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=180,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    (result / (label + '.stdout')).write_bytes(proc.stdout)
    (result / (label + '.stderr')).write_bytes(proc.stderr)
    records.append(dict(label=label, argv=argv, cwd=str(cwd), start=start, end=stamp(), rc=proc.returncode))
    return proc.returncode

mutation = root / 'mutation'
(mutation / 'tests').mkdir(parents=True, exist_ok=True)
(mutation / 'playbooks').mkdir(exist_ok=True)
shutil.copyfile(root / 'tests/test_dns_rollback_scope.py', mutation / 'tests/test_dns_rollback_scope.py')
shutil.copyfile(root / 'base-rollback.yml', mutation / 'playbooks/cr-p1-ans-01-01-rollback.yml')
statuses = []
for version in ('2.16.19', '2.21.3'):
    bindir = Path('/home/server01_ansible/ansible-candidate.8oCqVUwx/result/runtime/venv-' + version + '/bin')
    assert (bindir / 'python').is_file() and (bindir / 'ansible-playbook').is_file()
    rc_version = invoke(version + '-version', [str(bindir / 'ansible-playbook'), '--version'], root)
    rc_test = invoke(version + '-scope', [str(bindir / 'python'), '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_dns_rollback_scope.py', '-v'], root)
    rc_syntax = invoke(version + '-syntax', [str(bindir / 'ansible-playbook'), '-i', 'localhost,', '--syntax-check', '-e', 'cr_dns_rollback_host=k8s-worker02', str(root / 'playbooks/cr-p1-ans-01-01-rollback.yml')], root)
    rc_base = invoke(version + '-base-regression', [str(bindir / 'python'), '-B', '-m', 'unittest', 'test_dns_rollback_scope.RollbackScope.test_only_selected_host_collects_facts', '-v'], mutation / 'tests')
    statuses.append(rc_version == 0 and rc_test == 0 and rc_syntax == 0 and rc_base != 0)
report = {'schema': 'fds.dns-rollback-scope-fixture.v1', 'host': socket.gethostname(),
          'uid': os.getuid(), 'records': records, 'result': 'PASS' if all(statuses) else 'FAIL',
          'remote_dns_rollback': 'NOT_RUN', 'fixture_connections': 'LOCAL_ONLY',
          'rollback_tasks': 'REPLACED_WITH_MARKER_OR_FAILURE', 'source_hashes': {}}
for relative in ('tests/test_dns_rollback_scope.py', 'playbooks/cr-p1-ans-01-01-rollback.yml', 'base-rollback.yml', 'run-rollback-scope-validation.py'):
    report['source_hashes'][relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
(result / 'VALIDATION.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'result': report['result'], 'records': len(records), 'remote_dns_rollback': 'NOT_RUN'}))
raise SystemExit(not all(statuses))
