"""Controller-local tests only, in a fresh user-owned source directory."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess

root = Path(__file__).resolve().parent
assert socket.gethostname() == 'ansible01' and os.getuid() == 1000
result = root / 'results'
result.mkdir()
records = []
stamp = lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()
def invoke(label, argv):
    start = stamp()
    proc = subprocess.run(argv, cwd=root, capture_output=True, timeout=600,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    (result / (label + '.stdout')).write_bytes(proc.stdout)
    (result / (label + '.stderr')).write_bytes(proc.stderr)
    records.append(dict(label=label, argv=argv, cwd=str(root), start=start, end=stamp(), rc=proc.returncode))
    print(json.dumps({'label': label, 'rc': proc.returncode}), flush=True)
    return proc.returncode

invoke('shell-syntax', ['bash', '-n', 'scripts/cr-p1-ans-01-01-run.sh'])
for version in ('2.16.19', '2.21.3'):
    bindir = Path('/home/server01_ansible/ansible-candidate.8oCqVUwx/result/runtime/venv-' + version + '/bin')
    invoke(version + '-version', [str(bindir / 'ansible-playbook'), '--version'])
    pattern = 'test_*.py' if version == '2.16.19' else 'test_dns*.py'
    label = '-all-unit' if version == '2.16.19' else '-dns-tests'
    invoke(version + label, [str(bindir / 'python'), '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', pattern, '-v'])
    paths = sorted(p.relative_to(root).as_posix() for p in (root / 'playbooks').glob('*.yml'))
    paths += ['tests/ssh-server-readonly.yml', 'tests/test-dns-resolver-normalization.yml']
    for index, relative in enumerate(paths):
        invoke(version + '-syntax-' + str(index), [str(bindir / 'ansible-playbook'), '-i', 'localhost,', '--syntax-check', relative])
report = {'schema': 'fds.worker02.dns-session.validation.v1', 'host': socket.gethostname(),
          'uid': os.getuid(), 'records': records, 'result': 'PASS' if all(r['rc'] == 0 for r in records) else 'FAIL',
          'managed_host_operations': 'NOT_RUN', 'fixture_connections': 'LOCAL_ONLY',
          'dns_operations': 'SIMULATED', 'snapshot_io': 'REAL_TEMPORARY_FILES_AS_UID1000',
          'source_hashes': json.loads((root / 'source-hashes.json').read_text())}
(result / 'VALIDATION.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'result': report['result'], 'records': len(records), 'directory': str(root)}), flush=True)
raise SystemExit(report['result'] != 'PASS')
