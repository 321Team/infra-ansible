"""Test-only controller action: no subprocess, network, service or clock access."""
import glob
import json
from pathlib import Path

from ansible.plugins.action import ActionBase


def fixture_print_config(path):
    """Model fixture include expansion only; NOT a real chronyd grammar test.

    Only localhost test files are read. Actual parser coverage is recorded
    separately by the chronyd 4.6.1 effective-configuration fixtures.
    """
    lines = []
    for raw in Path(path).read_text().splitlines():
        line = ' '.join(raw.split())
        if not line or line[0] in '!#;%':
            continue
        fields = line.split()
        directive = fields[0].lower()
        if directive == 'confdir':
            assert len(fields) == 2, 'Unmodelled fixture confdir layout'
            for included in sorted(Path(fields[1]).glob('*.conf')):
                lines.extend(fixture_print_config(included))
        elif directive == 'include':
            assert len(fields) == 2, 'Unmodelled fixture include layout'
            matches = sorted(glob.glob(fields[1]))
            assert matches, 'chronyd include requires at least one match'
            for included in matches:
                lines.extend(fixture_print_config(included))
        else:
            lines.append(line)
    return lines


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        super().run(tmp, task_vars)
        root = Path(task_vars['fixture_root'])
        scenario = task_vars['fixture_scenario']
        state_file = root / 'events.json'
        state = json.loads(state_file.read_text()) if state_file.exists() else {
            'events': [], 'restarts': 0, 'synced': False}
        args = self._task.args
        state['events'].append(args)
        rc, stdout = 0, ''
        if args['kind'] == 'systemd':
            assert args['options'] == {'name': 'chronyd', 'state': 'restarted'}
            state['restarts'] += 1
            state['synced'] = False
            if (scenario.get('restart_fail') and state['restarts'] == 1 or
                    scenario.get('restore_fail') and state['restarts'] == 2):
                rc, stdout = 1, 'FIXTURE_SERVICE_FAILURE'
        else:
            argv = args['options']['argv']
            if argv[:3] == ['chronyd', '-p', '-f']:
                assert len(argv) == 4, argv
                path = root / 'chrony.conf' if argv[3] == '/etc/chrony.conf' else Path(argv[3])
                assert path.resolve().is_relative_to(root.resolve()), path
                stdout = '\n'.join(fixture_print_config(path)) + '\n'
            elif argv == ['rpm', '-q', 'chrony']:
                stdout = 'chrony-fixture'
            elif argv[:2] == ['systemctl', 'show']:
                stdout = 'loaded\nactive'
            elif argv == ['systemctl', 'is-active', 'chronyd.service']:
                stdout = 'active'
            elif argv[:2] == ['chronyc', 'waitsync']:
                # Model documented waitsync outcome, NOT real elapsed time.
                assert argv == ['chronyc', 'waitsync', '30', '0.1', '0', '10'], argv
                assert self._task.timeout == 300
                state['polls'] = 30 if scenario.get('wait_fail') else 3
                state['synced'] = not scenario.get('wait_fail', False)
                rc = 0 if state['synced'] else 1
                stdout = 'MODEL_POLLS=' + str(state['polls'])
            elif argv == ['chronyc', 'tracking']:
                system = scenario.get('system_time', '0.000001')
                last = scenario.get('last_offset', '0.000001')
                leap = scenario.get('leap', 'Normal')
                if state['restarts'] and not state['synced']:
                    leap = 'Not synchronised'
                stdout = ('Reference ID : 0A015D66 (10.1.93.102)\nStratum : 3\n'
                          f'System time : {system} seconds slow of NTP time\n'
                          f'Last offset : {last} seconds\nLeap status : {leap}\n')
                if scenario.get('missing_system'):
                    stdout = '\n'.join(x for x in stdout.splitlines()
                                       if not x.startswith('System time'))
                if scenario.get('duplicate_system'):
                    stdout += f'System time : {system} seconds slow of NTP time\n'
            elif argv in (['chronyc', '-n', 'sources', '-a'], ['chronyc', '-c', 'sources']):
                address = scenario.get('address', '10.1.93.102')
                if scenario.get('drift') and not state['synced']:
                    address = '192.0.2.123'
                stdout = ('MS Name/IP address Stratum Poll Reach LastRx Last sample\n'
                          '================================================================\n'
                          f'^* {address} 3 6 377 23 -1234ns[ -1234ns] +/- 1ms\n')
                if task_vars.get('cr_ntp_migrate_main') and task_vars.get('cr_ntp_is_source'):
                    # Local fixture addresses are never queried over the network.
                    upstreams = task_vars['cr_ntp_source_upstreams']
                    selected = scenario.get('address', upstreams[0])
                    first_state = '?' if scenario.get('source_no_selected') else '*'
                    other_state = '*' if scenario.get('source_two_selected') else '+'
                    other_upstreams = upstreams[1:-1] if scenario.get('source_missing') else upstreams[1:]
                    stdout = ('MS Name/IP address Stratum Poll Reach LastRx Last sample\n'
                              '================================================================\n'
                              f'^{first_state} {selected} 2 6 377 23 -1234ns[ -1234ns] +/- 1ms\n' +
                              ''.join(f'^{other_state} {ip} 2 6 377 23 -1234ns[ -1234ns] +/- 1ms\n'
                                      for ip in other_upstreams))
                if scenario.get('extra_source'):
                    stdout += '^? 192.0.2.124 3 6 0 0 0ns[ 0ns] +/- 1ms\n'
                if scenario.get('unresolved_source'):
                    stdout += '^? ID#1234567890 0 0 0 - +0ns[ +0ns] +/- 0ns\n'
            elif argv == ['chronyc', 'clients']:
                stdout = 'FIXTURE_CLIENTS'
            else:
                raise AssertionError('Unmodelled command: ' + repr(argv))
        state_file.write_text(json.dumps(state, indent=2) + '\n')
        return dict(changed=args['kind'] == 'systemd' and rc == 0,
                    failed=rc != 0, rc=rc, stdout=stdout,
                    stdout_lines=stdout.splitlines(), stderr='')
