"""Task-driven mocks, not systemd/Ansible runtime acceptance tests."""
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(undefined=StrictUndefined)

def tasks(name):
    return yaml.safe_load((ROOT / 'playbooks' / name).read_text())[-1]['tasks']

def recovery(name):
    seq = tasks(name)
    if name.endswith('apply.yml'):
        return next(t['rescue'] for t in seq if 'rescue' in t)
    return next(t['block'] for t in seq if t['name'] == 'Restore generic INPUT 443 before removing guard')

class RecoveryGates(unittest.TestCase):
    def run_mock(self, filename, failure=None):
        seq = recovery(filename)
        start = next(i for i,t in enumerate(seq) if 'disable Docker guard dependency' in t['name'] or 'Disable Docker guard dependency' in t['name'])
        context = {'hbr_ac04_guard_service':'guard.service'}
        effects = []
        for task in seq[start:]:
            name = task['name'].lower()
            if 'systemd_service' in ''.join(task.keys()):
                opts = task['ansible.builtin.systemd_service']
                stage = 'disable' if 'enabled' in opts else 'reload' if 'daemon_reload' in opts else 'stop'
                rc = 1 if failure == stage else 0
                if stage == 'stop':
                    effects.append('stop')
                    break  # Safety prefix only; no live service action.
            elif 'ansible.builtin.command' in task:
                argv = task['ansible.builtin.command']['argv']
                if '--property=Requires' in argv:
                    stage = 'query'
                    rc = 1 if failure == 'query' else 0
                    out = 'guard.service other.service' if failure == 'remaining' else 'other.service'
                elif 'is-active' in argv:
                    rc = 0; out = 'active'
                else:
                    raise AssertionError(name)
                context[task['register']] = {'rc':rc,'stdout':out}
            elif 'ansible.builtin.assert' in task:
                if not all(ENV.compile_expression(expr)(**context) for expr in task['ansible.builtin.assert']['that']):
                    break
                continue
            else:
                raise AssertionError(name)
            if rc != 0 and task.get('failed_when') is not False:
                break
        return effects

    def test_recovery_failure_prefix(self):
        for f in ('p1-hbr-01-ac04-apply.yml','p1-hbr-01-ac04-rollback.yml'):
            for failure in ('disable','reload','query','remaining'):
                with self.subTest(play=f,failure=failure):
                    self.assertEqual(self.run_mock(f,failure), [])
            with self.subTest(play=f,failure=None):
                self.assertEqual(self.run_mock(f), ['stop'])

    def test_dependency_checks_precede_destructive_operations(self):
        for f in ('p1-hbr-01-ac04-apply.yml','p1-hbr-01-ac04-rollback.yml'):
            seq = recovery(f)
            gate = next(i for i,t in enumerate(seq) if 'require confirmed dependency detach' in t['name'])
            for i,t in enumerate(seq):
                if t.get('ansible.builtin.systemd_service',{}).get('state') == 'stopped' or 'destroy' in t.get('ansible.builtin.command',{}).get('argv',[]):
                    self.assertGreater(i,gate)

class PrestateSeal(unittest.TestCase):
    def test_real_hash_command_normal_missing_and_tampered(self):
        seq = tasks('p1-hbr-01-ac04-verify.yml')
        i = next(i for i,t in enumerate(seq) if t['name']=='Verify sealed prestate hashes before consuming state')
        command = seq[i]['ansible.builtin.command']
        read = next(i for i,t in enumerate(seq) if 'ansible.builtin.slurp' in t)
        self.assertLess(i,read)
        self.assertNotIn('failed_when',seq[i])
        self.assertEqual(command['chdir'],'{{ hbr_ac04_state_dir }}')
        for failure in (None,'missing','state','other'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                p=Path(td)
                originals={'original-state.json':b'{"schema":3}\n','original-public.xml':b'<zone/>\n','nft-ruleset-before.txt':b'table inet before {}\n'}
                for n,b in originals.items(): (p/n).write_bytes(b)
                (p/'PRESTATE_SHA256SUMS').write_text(''.join(hashlib.sha256(b).hexdigest()+'  '+n+'\n' for n,b in originals.items()))
                if failure=='missing': (p/'PRESTATE_SHA256SUMS').unlink()
                if failure=='state': (p/'original-state.json').write_bytes(b'{"schema":4}\n')
                if failure=='other': (p/'nft-ruleset-before.txt').write_bytes(b'changed\n')
                r=subprocess.run(command['argv'],cwd=td,capture_output=True)
                self.assertEqual(r.returncode==0,failure is None)

class ApplyDataflow(unittest.TestCase):
    """Apply must register every prestate value it consumes before using it."""
    EXTRA_VARS = {'hbr_ac04_change_approved', 'hbr_ac04_ui_fallback_confirmed',
                  'hbr_ac04_change_window_confirmed'}

    def test_prestate_sources_registered_before_preserve(self):
        seq = tasks('p1-hbr-01-ac04-apply.yml')
        names = [t['name'] for t in seq]
        for var, writer in (('hbr_ac04_filter_save', 'Preserve filter table source'),
                            ('hbr_ac04_nat_save', 'Preserve NAT table source'),
                            ('hbr_ac04_nft_ruleset_before', 'Preserve nft ruleset source')):
            registered = [i for i, t in enumerate(seq) if t.get('register') == var]
            self.assertEqual(len(registered), 1, var + ' must be registered exactly once in apply')
            self.assertLess(registered[0], names.index(writer), var + ' must precede ' + writer)
            self.assertNotIn('failed_when', seq[registered[0]], var + ' capture must fail closed')

    def test_every_apply_variable_is_defined(self):
        import re
        text = (ROOT / 'playbooks' / 'p1-hbr-01-ac04-apply.yml').read_text()
        includes = re.findall(r'include_tasks:\s*(\S+)', text)
        sources = [text] + [(ROOT / 'playbooks' / inc).read_text() for inc in includes]
        defined = set(yaml.safe_load((ROOT / 'inventory' / 'group_vars' / 'hbr.yml').read_text()))
        defined |= self.EXTRA_VARS
        for src in sources:
            defined |= set(re.findall(r'register:\s*(\w+)', src))
            defined |= set(re.findall(r'^\s+(hbr_ac04_\w+):', src, re.M))
        used = set(re.findall(r'\b(hbr_ac04_\w+)', text))
        self.assertEqual(sorted(v for v in used if v not in defined), [])

if __name__=='__main__': unittest.main()
