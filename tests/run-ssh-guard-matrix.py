#!/usr/bin/env python3
"""Two pinned Linux interpreters; baseline + per-guard mutation proofs."""
import argparse
import json
from pathlib import Path
import subprocess

import yaml
from ssh_guard_fixtures import NAMES

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python216', type=Path, required=True)
    parser.add_argument('--python221', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'playbooks/harden_svc_ansible_key.yml'
    variants = [('baseline', source, None)]
    for index, name in enumerate(NAMES):
        for mutation in ('and', 'broken-list', 'undefined'):
            data = yaml.safe_load(source.read_text(encoding='utf-8'))
            task = next(t for t in data[0]['tasks'] if t['name'] == name)
            expression = task['failed_when']
            if ' or ' not in expression:
                raise ValueError('Source changed: mutation requires explicit OR')
            if mutation == 'and':
                task['failed_when'] = expression.replace(' or ', ' and ')
            elif mutation == 'broken-list':
                left, right = expression.split(' or ', 1)
                task['failed_when'] = [left, 'or', right]
            else:
                task['failed_when'] = 'undefined_ssh_guard_probe.value == 1'
            path = output / f'{mutation}-{index}.yml'
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
            variants.append((f'{mutation}-{index}', path, 'FAIL' if mutation == 'and' else 'ERROR'))
    runs = []
    baselines = []
    for version, python in [('2.16.19', args.python216), ('2.21.3', args.python221)]:
        python = python.absolute()
        for name, variant, expected in variants:
            report = output / f'{version}-{name}.json'
            command = [str(python), str(ROOT / 'tests/test-ssh-key-guards.py'),
                       '--source', str(variant), '--output', str(report),
                       '--export-dir', str(output / f'{version}-{name}'),
                       '--expect-engine', version,
                       '--ansible-playbook', str(python.parent / 'ansible-playbook')]
            try:
                process = subprocess.run(command, capture_output=True, text=True, timeout=660)
                (output / f'{version}-{name}.log').write_text(process.stdout + process.stderr, encoding='utf-8')
                summary = json.loads(report.read_text(encoding='utf-8'))
                counts = summary['outcomes']
                # A missing engine must never count as a successful mutation kill.
                valid = summary['engine'] == version and summary.get('cli_rc') is not None
                if expected is None:
                    valid &= process.returncode == 0 and counts == {'PASS': 14, 'FAIL': 0, 'ERROR': 0}
                    baselines.append([(r['case'], r['guard'], r['expected_failure'], r.get('observed_failure'),
                                       r.get('rc'), r.get('count'), r['outcome']) for r in summary['results']])
                else:
                    valid &= process.returncode != 0 and summary['cli_rc'] != 0 and counts[expected] > 0
                    if expected == 'FAIL':
                        valid &= counts['ERROR'] == 0
                    # The untouched guard must still pass all seven cases.
                    unaffected = NAMES[1 - int(name.rsplit('-', 1)[1])]
                    valid &= sum(r['guard'] == unaffected and r['outcome'] == 'PASS'
                                 for r in summary['results']) == 7
                runs.append({'engine': version, 'variant': name, 'passed': bool(valid), 'outcomes': counts})
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                runs.append({'engine': version, 'variant': name, 'passed': False, 'error': str(exc)})
    same = len(baselines) == 2 and baselines[0] == baselines[1]
    passed = same and len(runs) == 14 and all(r['passed'] for r in runs)
    report = {'status': 'PASS' if passed else 'FAIL', 'same_baseline_results': same, 'runs': runs}
    (output / 'MATRIX.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
