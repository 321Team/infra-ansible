#!/usr/bin/env python3
"""Run the pinned two-engine kit and syntax gate; preserve failure evidence."""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ci_kit', ROOT / 'tools/verification-kit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)

def syntax_paths(repo):
    paths = sorted(p.relative_to(repo).as_posix() for p in (repo / 'playbooks').glob('*.yml'))
    paths += ['tests/ssh-server-readonly.yml', 'tests/test-dns-resolver-normalization.yml']
    kit.require(bool(paths) and all((repo / p).is_file() for p in paths), 'Missing syntax source')
    return paths

def plan(repo, commit):
    kit.require(re.fullmatch('[0-9a-f]{40}', commit), 'Use the full reviewed source SHA')
    lock = kit.lock_data((repo / kit.LOCK).read_bytes())
    return {'schema_version': 1, 'source_commit': commit, 'engines': list(lock['engines']),
        'syntax_playbooks': syntax_paths(repo), 'scope': 'syntax + localhost fixtures only',
        'runner_registration': 'external approved input; never inferred from host address',
        'production_apply': False, 'operational_engine_transition': False}

def syntax_gate(runtime, output, paths, engines, evidence):
    repo = runtime / 'repo'
    config = output / 'syntax-ansible.cfg'
    config.write_text('[defaults]\nroles_path = ' + str(repo / 'roles') +
                      '\nhost_key_checking = True\nretry_files_enabled = False\n', encoding='utf-8')
    env = kit.environment(); env['ANSIBLE_CONFIG'] = str(config)
    for engine in engines:
        python = runtime / ('venv-' + engine) / 'bin/python'
        for index, relative in enumerate(paths):
            command = [python.parent / 'ansible-playbook', '--syntax-check', '-i', 'localhost,', '-c', 'local',
                       '-e', 'ansible_python_interpreter=' + str(python), repo / relative]
            kit.logged(command, repo, env, output / f'syntax-{engine}-{index:02}', timeout=300)
            evidence.append({'engine': engine, 'playbook': relative, 'rc': 0})

def execute(repo, commit, output, wheels=None):
    repo = kit.no_links(repo).resolve(); output = kit.no_links(output).resolve()
    kit.require(not output.is_relative_to(repo), 'CI output must be outside the checkout')
    output = kit.fresh_dir(output)
    record = {'schema_version': 1, 'source_commit': commit, 'status': 'FAIL', 'syntax': [],
              'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'scope': 'syntax and localhost fixtures; no deployment',
              'github': {k: os.environ.get(k) for k in ('GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
                  'GITHUB_WORKFLOW_SHA', 'GITHUB_SHA', 'GITHUB_EVENT_NAME', 'RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH')},
              'production_apply': False, 'operational_engine_transition': False}
    try:
        definition = plan(repo, commit)
        record['plan'] = definition
        kit.clean_source(repo, commit)
        kit.target_host()
        if wheels is None:
            wheels = output / 'wheels'
            kit.collect(repo, commit, wheels)
        built = kit.build(repo, commit, wheels, output / 'distribution')
        kit.require(built['source_commit'] == commit, 'Built source mismatch')
        record['archive_sha256'] = built['sha256']
        runtime = output / 'runtime'
        prepared = kit.prepare(Path(built['archive']), built['sha256'], runtime)
        kit.require(prepared['source_commit'] == commit and prepared['status'] == 'PREPARED', 'Prepared identity mismatch')
        syntax_gate(runtime, output, definition['syntax_playbooks'], definition['engines'], record['syntax'])
        fixture = kit.run(runtime, built['sha256'], output / 'fixtures')
        record['fixtures'] = fixture
        kit.require(fixture['status'] == 'PASS_FRESH_OFFLINE_FIXTURES' and fixture['source_commit'] == commit,
                    'Fixture failure or wrong source SHA')
        expected = {(e, p) for e in definition['engines'] for p in definition['syntax_playbooks']}
        kit.require(len(record['syntax']) == len(expected) and
                    {(r['engine'], r['playbook']) for r in record['syntax']} == expected,
                    'Incomplete syntax matrix')
        kit.clean_source(repo, commit)
        record['status'] = 'PASS'
    except Exception as exc:
        record['error'] = str(exc)
    finally:
        try:
            record['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            (output / 'CI_RESULT.json').write_bytes(kit.encoded(record))
            # Keep only evidence/configs, not venvs, cached modules, source packs or credentials.
            roots = [output / 'CI_RESULT.json', output / 'syntax-ansible.cfg']
            roots += sorted(output.glob('syntax-*'))
            roots += [output / 'fixtures/KIT_RUN.json', output / 'fixtures/guards-results/MATRIX.json',
                      output / 'fixtures/contract-results/MATRIX.json', runtime / 'RUNTIME.json'] if 'runtime' in locals() else []
            if 'runtime' in locals(): roots += sorted(runtime.glob('install-*'))
            if (output / 'fixtures').exists():
                roots.append(output / 'fixtures')
            artifact = output / 'artifact'; artifact.mkdir()
            copied, excluded = set(), []
            for root in roots:
                paths = [root] if root.is_file() else sorted(root.rglob('*')) if root.is_dir() else []
                for path in paths:
                    if not path.is_file() or path.is_symlink(): continue
                    relative = path.relative_to(output)
                    if str(relative) in copied: continue
                    if any(part.startswith('ansible-local') or part == 'tmp' for part in relative.parts):
                        excluded.append({'path': relative.as_posix(), 'sha256': kit.sha(path.read_bytes()), 'reason': 'module cache'})
                        continue
                    copied.add(str(relative))
                    target = artifact / relative; target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
            (artifact / 'ARTIFACT_SCOPE.json').write_bytes(kit.encoded({'source_commit': commit,
                'included_files': len(copied), 'excluded_cache_files': excluded,
                'note': 'Artifact SHA256SUMS covers included bytes; original fixture manifests may also reference excluded cache files.'}))
            (artifact / 'SHA256SUMS').write_text(''.join(kit.sha(p.read_bytes()) + '  ' + p.relative_to(artifact).as_posix() + '\n'
                for p in sorted(artifact.rglob('*')) if p.is_file()), encoding='utf-8')
        except Exception as export_error:
            # Fail closed on evidence export errors; never report a successful CLI.
            # Storage can remain unavailable, so updates are explicitly best-effort.
            record['status'] = 'FAIL'
            record['artifact_export'] = {'status': 'FAILED',
                'error_type': type(export_error).__name__,
                'errno': getattr(export_error, 'errno', None)}
            print('ARTIFACT_EXPORT_FAILED: ' + type(export_error).__name__, file=sys.stderr)
            for target in (output / 'CI_RESULT.json', output / 'artifact/CI_RESULT.json'):
                try:
                    if target.parent.is_dir():
                        target.write_bytes(kit.encoded(record))
                except Exception:
                    pass
            # Partial artifacts/manifests remain invalid and must not be accepted.
    return record

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--wheels', type=Path)
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(plan(args.repo, args.commit), indent=2)); return 0
    if args.output is None: parser.error('--output is required for execution')
    result = execute(args.repo, args.commit, args.output, args.wheels)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
