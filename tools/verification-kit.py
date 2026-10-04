#!/usr/bin/env python3
"""Build and verify a commit-pinned offline kit; execute local fixtures only."""
import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import urllib.request

sys.dont_write_bytecode = True
TOOL = 'tools/verification-kit.py'
LOCK = 'tools/verification-wheels.lock.json'
GUIDE = 'docs/runbooks/Verification-Kit.md'
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 5000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def decode(data):
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))


def encoded(data):
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')


def safe_name(name):
    require(type(name) is str and re.fullmatch(r'[A-Za-z0-9_.\-/]+', name), 'Non-portable file name')
    parts = name.split('/')
    require(all(p and p not in ('.', '..') and not p.endswith('.') for p in parts), 'Unsafe path')
    reserved = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
    require(all(p.split('.')[0].lower() not in reserved for p in parts), 'Reserved path')
    return name


def no_links(path):
    path = Path(path).absolute()
    for p in (path, *path.parents):
        require(not p.is_symlink() and not getattr(p, 'is_junction', lambda: False)(), 'Linked path refused')
    return path


def fresh_dir(path):
    path = no_links(path)
    require(not path.exists(), 'Use a NEW directory; existing results are never reused or deleted')
    path.mkdir(parents=True, exist_ok=False)
    return path


def environment():
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('GIT_', 'PIP_', 'PYTHON', 'ANSIBLE_', 'FDS_', 'PR3_', 'SSH_'))
           and k.upper() not in ('VIRTUAL_ENV', 'CONDA_PREFIX')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0',
               PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1',
               PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    return env


def git(repo, *args, data=None):
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'core.fsmonitor=false',
                           '-C', str(repo), *map(str, args)], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, env=environment(), timeout=120).stdout


def clean_source(repo, commit):
    require(re.fullmatch('[a-f0-9]{40}', commit), 'Use a full commit SHA')
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == commit, 'Checkout is not the requested commit')
    require(Path(git(repo, 'rev-parse', '--show-toplevel').decode().strip()).resolve() == Path(repo).resolve(),
            'Source must be a repository root')
    require(not git(repo, 'status', '--porcelain', '--untracked-files=all').strip(), 'Source checkout is dirty')


def source_entries(repo, commit):
    files, object_ids = [], {commit}
    object_ids.add(git(repo, 'rev-parse', commit + '^{tree}').decode().strip())
    for row in git(repo, 'ls-tree', '-r', '-t', '-z', commit).split(b'\0'):
        if not row:
            continue
        meta, name = row.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        name = safe_name(name.decode('utf-8'))
        object_ids.add(oid)
        if kind == 'tree':
            continue
        require(kind == 'blob' and mode in ('100644', '100755'), 'Links and submodules are not distributable')
        files.append({'path': name, 'git_blob': oid, 'mode': mode})
    require(0 < len(files) < MAX_FILES, 'Invalid source file count')
    return files, object_ids


def source_content_allowed(name, data):
    parts = [p.lower() for p in name.split('/')]
    forbidden = {'.git', '.ssh', '.env', 'known_hosts', 'authorized_keys', 'id_rsa', 'id_ed25519', '.netrc', '__pycache__'}
    require(not forbidden.intersection(parts) and not name.lower().endswith(('.pem', '.key', '.p12', '.pfx', '.pyc')),
            'Credential path refused: ' + name)
    require(not re.search(rb'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----', data), 'Private key content refused')
    require(not re.search(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b', data),
            'Credential content refused')


def lock_data(raw):
    lock = decode(raw)
    require(lock.get('schema_version') == 1 and type(lock.get('schema_version')) is int, 'Unknown wheel lock schema')
    require(lock['target'] == {'system': 'Linux', 'machine': 'x86_64', 'python': '3.12', 'glibc_min': '2.28'},
            'Unsupported wheel target')
    require(set(lock['engines']) == {'2.16.19', '2.21.3'} and lock['installer'] == {'pip': '25.2'}, 'Unexpected engines/installer')
    wanted = {(n, v) for pins in lock['engines'].values() for n, v in pins.items()} | {('pip', '25.2')}
    require(all(re.fullmatch('[A-Za-z0-9_-]+', n) and re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', v)
                for n, v in wanted), 'Invalid requirement name/version')
    found, names = set(), set()
    for wheel in lock['wheels']:
        key = (wheel['name'], wheel['version'])
        filename = safe_name(wheel['filename'])
        require('/' not in filename and filename.endswith('.whl') and filename.casefold() not in names, 'Invalid wheel name')
        require(filename.lower().startswith(wheel['name'].replace('-', '_').lower() + '-' + wheel['version'] + '-'),
                'Wheel does not match package identity')
        require(key in wanted and key not in found, 'Unexpected/duplicate wheel')
        require(re.fullmatch('[0-9a-f]{64}', wheel['sha256']) and type(wheel['size']) is int and 0 < wheel['size'] < MAX_BYTES,
                'Invalid wheel hash/size')
        require(wheel['url'].startswith('https://files.pythonhosted.org/packages/') and wheel['url'].endswith('/' + filename),
                'Unexpected artifact origin')
        found.add(key)
        names.add(filename.casefold())
    require(found == wanted, 'Missing pinned wheel')
    return lock


def verify_wheels(lock, directory):
    directory = no_links(directory)
    require(directory.is_dir(), 'Missing wheel directory')
    require({p.name for p in directory.iterdir()} == {w['filename'] for w in lock['wheels']}, 'Missing/extra wheel files')
    for w in lock['wheels']:
        p = no_links(directory / w['filename'])
        require(p.is_file() and p.stat().st_size == w['size'] and sha(p.read_bytes()) == w['sha256'], 'Wheel hash mismatch: ' + w['filename'])


def collect(repo, commit, destination):
    clean_source(repo, commit)
    require(not no_links(destination).is_relative_to(no_links(repo)), 'Collect outside the source checkout')
    lock = lock_data(git(repo, 'show', commit + ':' + LOCK))
    out = fresh_dir(destination)
    for w in lock['wheels']:
        with urllib.request.urlopen(w['url'], timeout=60) as response:
            require(response.geturl().startswith('https://files.pythonhosted.org/'), 'Unexpected artifact redirect')
            raw = response.read(w['size'] + 1)
        require(len(raw) == w['size'] and sha(raw) == w['sha256'], 'Downloaded wheel hash mismatch')
        (out / w['filename']).write_bytes(raw)
    verify_wheels(lock, out)
    clean_source(repo, commit)
    return {'status': 'WHEELS_VERIFIED', 'wheels': len(lock['wheels']), 'source_commit': commit}


def lock_text(lock, pins):
    hashes = {(w['name'], w['version']): w['sha256'] for w in lock['wheels']}
    return ''.join(f'{n}=={v} --hash=sha256:{hashes[n, v]}\n' for n, v in sorted(pins.items())).encode()


def make_archive(files):
    raw = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.USTAR_FORMAT) as tar:
            for name, (data, mode) in sorted(files.items()):
                item = tarfile.TarInfo(safe_name(name))
                item.size, item.mode = len(data), mode
                item.mtime, item.uid, item.gid = 0, 0, 0
                tar.addfile(item, io.BytesIO(data))
    return raw.getvalue()


def build(repo, commit, wheels, destination):
    repo, destination = no_links(repo), no_links(destination)
    clean_source(repo, commit)
    require(not destination.is_relative_to(repo), 'Build outside the source checkout')
    require(Path(__file__).read_bytes() == git(repo, 'show', commit + ':' + TOOL), 'Builder differs from requested commit')
    lock = lock_data(git(repo, 'show', commit + ':' + LOCK))
    verify_wheels(lock, wheels)
    entries, ids = source_entries(repo, commit)
    files = {}
    for entry in entries:
        raw = git(repo, 'cat-file', 'blob', entry['git_blob'])
        source_content_allowed(entry['path'], raw)
        require(blob_sha(raw) == entry['git_blob'], 'Source blob mismatch')
        entry.update(sha256=sha(raw), size=len(raw))
        files['source/' + entry['path']] = (raw, int(entry['mode'][-3:], 8))
    for engine, pins in lock['engines'].items():
        text = files['source/tests/requirements-verification-' + engine + '.txt'][0].decode()
        observed = dict(line.split('==') for line in text.splitlines() if line and not line.startswith('#'))
        require(observed == pins, 'Runtime pins and wheel lock differ')
        files['requirements-' + engine + '.lock'] = (lock_text(lock, pins), 0o644)
    files['installer.lock'] = (lock_text(lock, lock['installer']), 0o644)
    for w in lock['wheels']:
        files['wheels/' + w['filename']] = ((Path(wheels) / w['filename']).read_bytes(), 0o644)
    pack = git(repo, 'pack-objects', '--stdout', '--threads=1', '--no-reuse-delta', '--no-reuse-object',
               data=('\n'.join(sorted(ids)) + '\n').encode())
    files['SOURCE.pack'] = (pack, 0o644)
    files['SOURCE_MANIFEST.json'] = (encoded({'schema_version': 1, 'commit': commit,
        'tree': git(repo, 'rev-parse', commit + '^{tree}').decode().strip(), 'files': entries,
        'source_file_count': len(entries), 'history': 'only selected commit, trees and blobs; parents excluded'}), 0o644)
    files['kit.py'] = (files['source/' + TOOL][0], 0o644)
    files['README.md'] = (files['source/' + GUIDE][0], 0o644)
    files['KIT.json'] = (encoded({'schema_version': 1, 'source_commit': commit, 'target': lock['target'],
        'wheel_lock_sha256': sha(files['source/' + LOCK][0]), 'default_scope': 'local fixtures only',
        'operational_apply': False, 'operational_engine_transition': False}), 0o644)
    files['SHA256SUMS'] = (''.join(f'{sha(data)}  {name}\n' for name, (data, _) in sorted(files.items())).encode(), 0o644)
    raw = make_archive(files)
    out = fresh_dir(destination)
    archive = out / ('verification-kit-' + commit + '.tar.gz')
    archive.write_bytes(raw)
    archive.with_name(archive.name + '.sha256').write_text(f'{sha(raw)}  {archive.name}\n', encoding='ascii')
    # The verifier is distributed separately so verification precedes executing anything extracted.
    (out / 'verify-kit.py').write_bytes(files['kit.py'][0])
    (out / 'verify-kit.py.sha256').write_text(f"{sha(files['kit.py'][0])}  verify-kit.py\n", encoding='ascii')
    clean_source(repo, commit)
    verified = verify_archive(archive, sha(raw))
    return {'status': 'KIT_BUILT', 'archive': str(archive), 'sha256': sha(raw), 'source_commit': commit,
            'source_files': len(entries), 'payload_files': len(verified)}


def verify_archive(archive, expected):
    require(re.fullmatch('[0-9a-f]{64}', expected), 'Supply the independently recorded archive SHA256')
    archive = no_links(archive)
    require(archive.is_file() and archive.stat().st_size <= MAX_BYTES, 'Invalid archive size')
    raw = archive.read_bytes()
    require(sha(raw) == expected, 'Outer SHA256 mismatch')
    files, names, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
        for item in tar:
            name = safe_name(item.name)
            require(item.isfile() and not item.issparse() and item.mode in (0o644, 0o755), 'Unsupported archive member')
            require(name.casefold() not in names and len(files) < MAX_FILES, 'Duplicate/excessive archive members')
            names.add(name.casefold())
            total += item.size
            require(0 <= item.size <= MAX_BYTES and total <= MAX_BYTES, 'Expanded archive size limit')
            files[name] = (tar.extractfile(item).read(), item.mode)
    require('SHA256SUMS' in files, 'Missing inner manifest')
    listed = {}
    for line in files['SHA256SUMS'][0].decode('ascii').splitlines():
        require(re.fullmatch(r'[0-9a-f]{64}  [A-Za-z0-9_.\-/]+', line), 'Invalid manifest line')
        digest, name = line.split('  ', 1)
        safe_name(name)
        require(name not in listed, 'Duplicate manifest entry')
        listed[name] = digest
    require(set(listed) == set(files) - {'SHA256SUMS'}, 'Unlisted or missing payload file')
    require(all(sha(files[n][0]) == d for n, d in listed.items()), 'Inner SHA256 mismatch')
    manifest = decode(files['SOURCE_MANIFEST.json'][0])
    kit = decode(files['KIT.json'][0])
    require(manifest['schema_version'] == kit['schema_version'] == 1, 'Unknown kit schema')
    require(re.fullmatch('[0-9a-f]{40}', manifest['commit']) and manifest['commit'] == kit['source_commit'], 'Code identity mismatch')
    source = set()
    for entry in manifest['files']:
        name = 'source/' + safe_name(entry['path'])
        require(name not in source and entry['mode'] in ('100644', '100755'), 'Duplicate/invalid source entry')
        source.add(name)
        data, mode = files[name]
        source_content_allowed(entry['path'], data)
        require(sha(data) == entry['sha256'] and len(data) == entry['size'] and blob_sha(data) == entry['git_blob']
                and mode == int(entry['mode'][-3:], 8), 'Source manifest mismatch')
    require(source == {n for n in files if n.startswith('source/')} and len(source) == manifest['source_file_count'], 'Source list mismatch')
    lock = lock_data(files['source/' + LOCK][0])
    require(sha(files['source/' + LOCK][0]) == kit['wheel_lock_sha256'] and lock['target'] == kit['target'], 'Lock identity mismatch')
    for w in lock['wheels']:
        data = files['wheels/' + w['filename']][0]
        require(sha(data) == w['sha256'] and len(data) == w['size'], 'Pinned wheel mismatch')
    require(files['kit.py'][0] == files['source/' + TOOL][0], 'Verifier source mismatch')
    require(files['README.md'][0] == files['source/' + GUIDE][0], 'Guide source mismatch')
    for engine, pins in {**lock['engines'], 'installer': lock['installer']}.items():
        name = 'installer.lock' if engine == 'installer' else 'requirements-' + engine + '.lock'
        require(files[name][0] == lock_text(lock, pins), 'Install lock mismatch')
    expected_files = source | {'SOURCE.pack', 'SOURCE_MANIFEST.json', 'KIT.json', 'kit.py', 'README.md', 'SHA256SUMS', 'installer.lock'}
    expected_files |= {'requirements-' + engine + '.lock' for engine in lock['engines']}
    expected_files |= {'wheels/' + w['filename'] for w in lock['wheels']}
    require(set(files) == expected_files, 'Unexpected kit payload')
    return files


def extract_files(files, destination):
    out = fresh_dir(destination)
    for name, (data, mode) in sorted(files.items()):
        p = out / safe_name(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('xb') as handle:
            handle.write(data)
        p.chmod(mode)
    return out


def materialize(kit, repo):
    manifest = decode((kit / 'SOURCE_MANIFEST.json').read_bytes())
    repo = fresh_dir(repo)
    git(repo, 'init', '--template=')
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'config', 'core.filemode', 'false' if os.name == 'nt' else 'true')
    git(repo, 'unpack-objects', '-r', data=(kit / 'SOURCE.pack').read_bytes())
    (repo / '.git/shallow').write_text(manifest['commit'] + '\n', encoding='ascii')
    (repo / '.git/HEAD').write_text(manifest['commit'] + '\n', encoding='ascii')
    require(git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip() == manifest['tree'], 'Packed commit tree mismatch')
    actual, _ = source_entries(repo, manifest['commit'])
    require([{k: e[k] for k in ('path', 'git_blob', 'mode')} for e in manifest['files']] == actual, 'Packed source differs')
    for entry in manifest['files']:
        data = (kit / 'source' / entry['path']).read_bytes()
        require(git(repo, 'cat-file', 'blob', entry['git_blob']) == data, 'Packed blob differs from text')
        target = repo / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(int(entry['mode'][-3:], 8))
    git(repo, 'read-tree', 'HEAD')
    git(repo, 'fsck', '--strict', '--no-reflogs')
    clean_source(repo, manifest['commit'])
    return repo


def target_host():
    libc, version = platform.libc_ver()
    require(sys.platform == 'linux' and platform.machine() == 'x86_64' and sys.version_info[:2] == (3, 12)
            and sys.implementation.name == 'cpython',
            'Runtime requires Linux x86_64 CPython 3.12; packaging/verification also works elsewhere')
    require(libc == 'glibc' and tuple(map(int, version.split('.')[:2])) >= (2, 28), 'glibc 2.28 or newer required')


def logged(command, cwd, env, directory, timeout=1800):
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'COMMAND.json').write_bytes(encoded([str(x) for x in command]))
    with (directory / 'stdout.log').open('xb') as stdout, (directory / 'stderr.log').open('xb') as stderr:
        proc = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                start_new_session=(os.name == 'posix'))
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                import signal
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait()
            rc = 124
    (directory / 'EXIT_CODE').write_text(str(rc) + '\n', encoding='ascii')
    require(rc == 0, 'Command failed; original logs retained at ' + str(directory))


def prepare(archive, expected, destination):
    files = verify_archive(archive, expected)
    target_host()
    out = fresh_dir(destination)
    (out / 'package.tar.gz').write_bytes(Path(archive).read_bytes())
    verify_archive(out / 'package.tar.gz', expected)
    kit = extract_files(files, out / 'kit')
    repo = materialize(kit, out / 'repo')
    lock = lock_data((kit / 'source' / LOCK).read_bytes())
    env = environment()
    for engine in lock['engines']:
        venv = out / ('venv-' + engine)
        logged([sys.executable, '-I', '-m', 'venv', venv], out, env, out / ('install-' + engine + '-venv'))
        python = venv / 'bin/python'
        base = [python, '-I', '-m', 'pip', '--isolated', 'install', '--no-user', '--prefix', venv,
                '--no-index', '--no-cache-dir', '--only-binary=:all:',
                '--require-hashes', '--find-links', kit / 'wheels']
        logged([*base, '--no-deps', '-r', kit / 'installer.lock'], out, env, out / ('install-' + engine + '-pip'))
        logged([*base, '-r', kit / ('requirements-' + engine + '.lock')], out, env, out / ('install-' + engine + '-packages'))
        logged([python, '-I', '-m', 'pip', 'check'], out, env, out / ('install-' + engine + '-check'))
    meta = {'schema_version': 1, 'status': 'PREPARED', 'archive_sha256': expected,
            'source_commit': decode(files['KIT.json'][0])['source_commit'],
            'python': sys.version, 'platform': platform.platform(), 'scope': 'fixture_local_only',
            'created_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    clean_source(repo, meta['source_commit'])
    (out / 'RUNTIME.json').write_bytes(encoded(meta))
    return meta


def run(runtime, expected, destination):
    target_host()
    runtime = no_links(runtime)
    files = verify_archive(runtime / 'package.tar.gz', expected)
    meta = decode((runtime / 'RUNTIME.json').read_bytes())
    require(meta['status'] == 'PREPARED' and meta['archive_sha256'] == expected and
            meta['source_commit'] == decode(files['KIT.json'][0])['source_commit'], 'Runtime attribution mismatch')
    # Recheck extracted bytes and source before executing any supplied Python.
    for name, (data, _) in files.items():
        p = no_links(runtime / 'kit' / name)
        require(p.is_file() and p.read_bytes() == data, 'Extracted kit changed')
    repo = runtime / 'repo'
    clean_source(repo, meta['source_commit'])
    for e in decode(files['SOURCE_MANIFEST.json'][0])['files']:
        p = no_links(repo / e['path'])
        require(sha(p.read_bytes()) == e['sha256'], 'Source text changed')
    out = no_links(destination)
    require(not out.is_relative_to(runtime), 'Results must be outside the runtime')
    out = fresh_dir(out)
    env = environment()
    env['ANSIBLE_CONFIG'] = str(out / 'ansible.cfg')
    (out / 'ansible.cfg').write_text('[defaults]\nhost_key_checking=True\nretry_files_enabled=False\n', encoding='ascii')
    engines = list(decode(files['source/' + LOCK][0])['engines'])
    pythons = [runtime / ('venv-' + e) / 'bin/python' for e in engines]
    result = {**meta, 'status': 'FAIL', 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'steps': [],
              'original_readonly_result': 'NOT_RUN; no operational inventory or SSH execution in this kit run'}
    try:
        commands = [('unit-tests', [pythons[0], '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'])]
        for name, script in [('guards', 'run-ssh-guard-matrix.py'), ('contract', 'run-verification-contract-matrix.py')]:
            commands.append((name, [pythons[0], '-B', repo / 'tests' / script, '--python216', pythons[0],
                                   '--python221', pythons[1], '--output', out / (name + '-results')]))
        for engine, python in zip(engines, pythons):
            commands.append(('b2-conditions-' + engine, [python, '-B',
                repo / 'tests/run-p1-sec-b2-conditions.py', '--output', out / ('b2-conditions-' + engine + '-results')]))
            commands.append(('dns-' + engine, [python.parent / 'ansible-playbook', '-i', 'localhost,', '-c', 'local',
                '-e', 'ansible_python_interpreter=' + str(python), repo / 'tests/test-dns-resolver-normalization.yml']))
        for name, cmd in commands:
            logged(cmd, repo, env, out / name)
            result['steps'].append({'name': name, 'rc': 0})
        for name in ('guards', 'contract'):
            matrix = decode((out / (name + '-results') / 'MATRIX.json').read_bytes())
            require(matrix['status'] == 'PASS' and matrix['same_baseline_results'] is True, 'Matrix did not establish success')
            if name == 'contract':
                require(matrix['code_sha'] == meta['source_commit'], 'Matrix source identity mismatch')
        clean_source(repo, meta['source_commit'])
        result['status'] = 'PASS_FRESH_OFFLINE_FIXTURES'
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        result['error'] = str(exc)
    finally:
        result['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        (out / 'KIT_RUN.json').write_bytes(encoded(result))
        # Install logs are evidence of fresh venv creation and offline dependency resolution.
        for p in runtime.glob('install-*/*'):
            if p.is_file():
                target = out / 'installation' / p.parent.name / p.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(p.read_bytes())
        hashes = {p.relative_to(out).as_posix(): sha(p.read_bytes()) for p in out.rglob('*') if p.is_file()}
        (out / 'SHA256SUMS').write_text(''.join(f'{v}  {k}\n' for k, v in sorted(hashes.items())), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('collect', 'build'):
        p = sub.add_parser(name)
        p.add_argument('--repo', required=True, type=Path)
        p.add_argument('--commit', required=True)
        p.add_argument('--output', required=True, type=Path)
        if name == 'build':
            p.add_argument('--wheels', required=True, type=Path)
    for name in ('verify', 'prepare'):
        p = sub.add_parser(name)
        p.add_argument('--archive', required=True, type=Path)
        p.add_argument('--sha256', required=True)
        p.add_argument('--output', type=Path, required=(name == 'prepare'))
    p = sub.add_parser('run')
    p.add_argument('--runtime', required=True, type=Path)
    p.add_argument('--sha256', required=True)
    p.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'collect':
            result = collect(args.repo, args.commit, args.output)
        elif args.command == 'build':
            result = build(args.repo, args.commit, args.wheels, args.output)
        elif args.command == 'verify':
            files = verify_archive(args.archive, args.sha256)
            if args.output:
                extract_files(files, args.output)
            result = {'status': 'ARCHIVE_AND_TEXT_VERIFIED', 'files': len(files), 'sha256': args.sha256}
        elif args.command == 'prepare':
            result = prepare(args.archive, args.sha256, args.output)
        else:
            result = run(args.runtime, args.sha256, args.output)
        print(json.dumps(result, indent=2))
        return 1 if result['status'] == 'FAIL' else 0
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, tarfile.TarError) as exc:
        print('VERIFICATION_KIT_FAILED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
