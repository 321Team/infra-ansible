#!/usr/bin/env python3
"""Issue #9: bounded, passive host inventory. Never runs discovered commands."""
import argparse
import configparser
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile

VERSION = '1.0'
MAX_FILE = 256 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILES = 1200
REF = re.compile(r'(?<![A-Za-z0-9_])(?:/[A-Za-z0-9_.+/-]+/)?(?:ansible(?:-playbook|-galaxy|-config)?|python3(?:\.\d+)?|(?:cr-p1-[A-Za-z0-9-]+|p1-k8s-01-gate0)-run\.sh)(?![A-Za-z0-9_.-])')
SECRET_PATH = re.compile(r'(^|/)(?:\.ssh|\.aws|\.gnupg|\.env(?:\..*)?|\.credentials|\.git)(/|$)|(?:private[_-]?key|password|secret|token|credential)', re.I)
ENV_NAMES = ('ANSIBLE_CONFIG', 'ANSIBLE_COLLECTIONS_PATH', 'ANSIBLE_COLLECTIONS_PATHS',
             'ANSIBLE_ROLES_PATH', 'ANSIBLE_LIBRARY', 'ANSIBLE_MODULE_UTILS',
             'ANSIBLE_PYTHON_INTERPRETER', 'VIRTUAL_ENV', 'PYTHONPATH', 'BASH_ENV', 'ENV')
WRAPPERS = ('cr-p1-ans-01-01-run.sh', 'cr-p1-mon-01-01-run.sh',
            'cr-p1-ntp-01-01-run.sh', 'p1-k8s-01-gate0-run.sh', 'verify-ssh-main.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def scan_text(data):
    text = data.decode('utf-8', errors='replace')
    rows = []
    active = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith(('#', ';')):
            continue
        active += 1
        refs = sorted(set(REF.findall(line)))
        if refs:
            rows.append({'line': number, 'references': refs})
    return {'active_lines': active, 'reference_lines': rows,
            'interpretation': 'TEXT_REFERENCES_ONLY_NOT_EXECUTED; indirect/dynamic calls require operator review'}


class Inventory:
    def __init__(self):
        self.used = 0
        self.files = []
        self.gaps = []
        self.seen = set()

    def read(self, path, category):
        path = Path(path)
        key = (str(path), category)
        if key in self.seen:
            return None
        self.seen.add(key)
        row = {'path': str(path), 'category': category}
        self.files.append(row)
        try:
            if SECRET_PATH.search(str(path)):
                raise ValueError('SENSITIVE_PATH_NOT_READ')
            if len(self.files) > MAX_FILES:
                raise ValueError('FILE_COUNT_LIMIT')
            # Do not follow file links or parent symlinks. Inspect referents only
            # through an explicit, separately selected canonical path.
            if path.absolute() != path.resolve(strict=False):
                raise ValueError('SYMLINK_PATH_NOT_READ')
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
                info = os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('NOT_REGULAR')
                if info.st_size > MAX_FILE or self.used + info.st_size > MAX_TOTAL:
                    raise ValueError('BYTE_LIMIT')
                data = f.read(MAX_FILE + 1)
                self.used += len(data)
                after = os.fstat(f.fileno())
                if len(data) > MAX_FILE or self.used > MAX_TOTAL:
                    raise ValueError('BYTE_LIMIT')
                if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('CHANGED_DURING_READ')
            row.update(status='READ', size=len(data), sha256=sha(data),
                       mode=oct(stat.S_IMODE(info.st_mode)), uid=info.st_uid,
                       gid=info.st_gid, mtime_ns=info.st_mtime_ns)
            row.update(scan_text(data))
            return data
        except (OSError, ValueError) as exc:
            row['status'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            if row['status'] != 'FileNotFoundError':
                self.gaps.append({'path': str(path), 'reason': row['status']})
            return None

    def directory(self, path, suffixes=None):
        path = Path(path)
        try:
            if len(self.files) >= MAX_FILES or self.used >= MAX_TOTAL:
                raise ValueError('COLLECTION_LIMIT')
            if path.absolute() != path.resolve(strict=False):
                raise ValueError('SYMLINK_DIRECTORY_NOT_SCANNED')
            with os.scandir(path) as entries:
                names = []
                for entry in entries:
                    if len(names) >= MAX_FILES:
                        raise ValueError('DIRECTORY_ENTRY_LIMIT')
                    names.append(entry.name)
            return [path / n for n in sorted(names) if suffixes is None or n.endswith(suffixes)]
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            self.gaps.append({'path': str(path), 'reason': type(exc).__name__})
            return []


def query(argv, cwd):
    # Fixed tools only. No shell, inherited Git/Python/Ansible/loader variables,
    # discovered executable, package installation, service or network operation.
    env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'LANG': 'C',
           'HOME': str(cwd), 'GIT_OPTIONAL_LOCKS': '0',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
    try:
        result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        data = result.stdout
        return {'argv': argv, 'rc': result.returncode, 'status': 'RETURNED',
                'stdout_bytes': len(data), 'stderr_bytes': len(result.stderr)}, data
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': argv, 'rc': None, 'status': type(exc).__name__}, b''


def repo_sections(data):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(data.decode('utf-8'))
        return [{'id': s if re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', s) else '[redacted-id]',
                 'enabled_literal': parser.get(s, 'enabled', fallback='UNSET')
                    if parser.get(s, 'enabled', fallback='UNSET') in ('0', '1', 'UNSET') else 'OTHER',
                 'location_fields_present': [k for k in ('baseurl', 'mirrorlist', 'metalink') if parser.has_option(s, k)]}
                for s in parser.sections()]
    except (ValueError, configparser.Error, UnicodeError):
        return [{'status': 'PARSE_ERROR'}]


def validate(args):
    if os.geteuid() == 0:
        raise ValueError('STOP: use the existing non-root operating account; no sudo')
    if socket.gethostname().split('.')[0] != args.expected_host:
        raise ValueError('STOP: host mismatch')
    if pwd.getpwuid(os.geteuid()).pw_name != args.expected_user:
        raise ValueError('STOP: account mismatch')
    repo = Path(args.repo)
    if not repo.is_absolute() or repo != repo.resolve() or not repo.is_dir():
        raise ValueError('STOP: repo must be an existing canonical absolute directory')
    parent = Path(args.output_parent)
    if not parent.is_absolute() or parent != parent.resolve() or not parent.is_dir():
        raise ValueError('STOP: output parent must be an existing canonical absolute directory')
    info = parent.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError('STOP: output parent must be owned by the account and not group/other writable')
    if parent == repo or repo in parent.parents:
        raise ValueError('STOP: evidence must be outside the source checkout')
    return repo, parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True)
    p.add_argument('--output-parent', required=True)
    p.add_argument('--expected-host', required=True)
    p.add_argument('--expected-user', required=True)
    p.add_argument('--file', action='append', default=[], help='Additional explicit non-secret wrapper/unit/workflow path; never executed')
    args = p.parse_args()
    try:
        repo, parent = validate(args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 64
    os.umask(0o077)
    out = Path(tempfile.mkdtemp(prefix='ansible-callpaths-', dir=parent))
    inv = Inventory()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    report = {'schema_version': 1, 'collector_version': VERSION,
              'collector_sha256': sha(Path(__file__).read_bytes()), 'started_at': started,
              'host': socket.gethostname(), 'user': pwd.getpwuid(os.geteuid()).pw_name,
              'uid': os.geteuid(), 'python': sys.version, 'python_executable': sys.executable,
              'scope': 'PASSIVE_LOCAL_COLLECTION_ONLY', 'runtime': 'NOT_RUN',
              'production_apply': False, 'engine_transition': False,
              'environment_presence': {k: bool(os.environ.get(k)) for k in ENV_NAMES},
              'repo': str(repo), 'commands': [], 'path_candidates': [], 'repositories': [],
              'manual_followup': [
                  'actual interactive aliases/functions and PATH precedence versus this process',
                  'root/other users crontab; unreadable units/drop-ins; generated/transient timers',
                  'indirect shell calls, EnvironmentFile values and effective service state',
                  'Runner workflow/image/venv exact source and runtime command per repository',
                  'installed RPM originating repository and vendor backport support',
                  'effective Ansible config/collection list and target Python under actual invocation',
              ]}
    try:
        cmd, raw = query(['/usr/bin/git', '-C', str(repo), 'rev-parse', '--verify', 'HEAD'], out)
        report['commands'].append(cmd)
        head = raw.decode('ascii', errors='replace').strip()
        report['checkout_head'] = head if cmd['rc'] == 0 and re.fullmatch('[0-9a-f]{40,64}', head) else 'UNCONFIRMED'
        cmd, raw = query(['/usr/bin/rpm', '-q', '--qf', '%{NAME}\t%{EPOCHNUM}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{VENDOR}\n', 'ansible-core', 'python3'], out)
        report['commands'].append(cmd)
        report['installed_rpm_rows'] = []
        for line in raw.decode('utf-8', errors='replace').splitlines():
            cols = line.split('\t')
            if len(cols) == 6 and cols[0] in ('ansible-core', 'python3'):
                report['installed_rpm_rows'].append(dict(zip(('name', 'epoch', 'version', 'release', 'arch', 'vendor'), cols)))
        cmd, raw = query(['/usr/bin/crontab', '-l'], out)
        report['commands'].append(cmd)
        report['current_user_crontab'] = scan_text(raw) if cmd['rc'] == 0 and len(raw) <= MAX_FILE else {'status': 'UNCONFIRMED', 'reason': 'nonzero/missing/timeout/oversize is not proof of no scheduled jobs'}
        for directory in os.environ.get('PATH', '').split(os.pathsep):
            if not directory or not Path(directory).is_absolute():
                inv.gaps.append({'path': '[relative PATH entry]', 'reason': 'NOT_INSPECTED'})
                continue
            for name in ('ansible', 'ansible-playbook', 'ansible-galaxy', 'python3', 'python3.12'):
                target = Path(directory) / name
                if target.exists() or target.is_symlink():
                    report['path_candidates'].append({'path': str(target), 'realpath': str(target.resolve()),
                        'executable_bit_for_account': os.access(target, os.X_OK), 'symlink': target.is_symlink(),
                        'executed': False})
                    if name.startswith('ansible'):
                        data = inv.read(target.resolve(), 'cli_file_not_executed')
                        if data is not None and data.startswith(b'#!'):
                            report['path_candidates'][-1]['shebang_references'] = sorted(set(REF.findall(data.splitlines()[0].decode('utf-8', errors='replace'))))
        for path in [repo / 'ansible.cfg', Path('/etc/ansible/ansible.cfg'), Path.home() / '.ansible.cfg',
                     Path('/etc/crontab'), Path('/etc/anacrontab'), Path.home() / '.bashrc',
                     Path.home() / '.bash_profile', Path.home() / '.profile']:
            inv.read(path, 'config_or_shell_or_schedule')
        for name in WRAPPERS:
            inv.read(repo / 'scripts' / name, 'repository_entrypoint')
        for directory in ('/etc/cron.d', '/etc/cron.hourly', '/etc/cron.daily', '/etc/cron.weekly', '/etc/cron.monthly'):
            for path in inv.directory(directory):
                inv.read(path, 'system_schedule')
        for directory in (Path('/etc/systemd/system'), Path('/run/systemd/system'),
                          Path('/usr/lib/systemd/system'), Path.home() / '.config/systemd/user'):
            for path in inv.directory(directory, ('.service', '.timer')):
                inv.read(path, 'unit_file_not_effective_state')
            for dropdir in inv.directory(directory, ('.service.d', '.timer.d')):
                for path in inv.directory(dropdir, ('.conf',)):
                    inv.read(path, 'unit_dropin')
        for path in inv.directory('/etc/yum.repos.d', ('.repo',)):
            data = inv.read(path, 'repo_definition_not_install_origin')
            if data is not None:
                report['repositories'].append({'path': str(path), 'sections': repo_sections(data)})
        for name in args.file:
            path = Path(name)
            if not path.is_absolute():
                inv.gaps.append({'path': '[relative --file]', 'reason': 'NOT_INSPECTED'})
            else:
                inv.read(path, 'operator_selected_entrypoint')
        report.update(status='COLLECTED_REVIEW_REQUIRED', completed=True)
        rc = 0
    except Exception as exc:
        report.update(status='INCOMPLETE_COLLECTION', completed=False, error_type=type(exc).__name__)
        rc = 2
    report.update(files=inv.files, coverage_gaps=inv.gaps, bytes_read=inv.used,
                  finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
    target = out / 'REPORT.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'SHA256SUMS').write_text(sha(target.read_bytes()) + '  REPORT.json\n', encoding='ascii')
    print(json.dumps({'status': report['status'], 'output': str(out), 'rc': rc}))
    return rc


if __name__ == '__main__':
    sys.exit(main())
