#!/usr/bin/env python3
"""Fixed-topology firewall companion. JSON stdin/stdout; no shell and no reload.

This is NEW code requiring its own reviewed revision. It never applies chrony.
The controller alone orders egress after a successfully completed approved rollout.
Runtime policy creation is unavailable without reload; the deprecated firewalld
DIRECT interface is used only for drop-only OUTPUT filtering, not ACCEPT rules.
"""
import base64
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time

HOSTS = {'k8s-control01': '10.1.93.102', 'k8s-control02': '10.1.93.103',
         'k8s-control03': '10.1.93.104', 'k8s-worker01': '10.1.93.105',
         'k8s-worker02': '10.1.93.107', 'k8s-worker03': '10.1.93.108'}
SOURCE = 'k8s-control01'
UPSTREAMS = ['162.159.200.1', '162.159.200.123']
CHAIN = 'FDS_NTP_0101'
BASE = Path('/var/lib/fds-ntp-onepass')
ACTIONS = {'snapshot', 'ingress', 'egress', 'verify', 'rollback_ingress',
           'rollback_egress', 'sample'}
MAX_REQUEST = 65536
MAX_OUTPUT = 8 * 1024 * 1024
MAX_STATE = 24 * 1024 * 1024
FIREWALL = '/usr/bin/firewall-cmd'
FILES = ('/etc/chrony.conf', '/etc/chrony.d/50-cr-p1-ntp-01-01.conf',
         '/etc/sysconfig/chronyd', '/etc/firewalld/firewalld.conf',
         '/etc/firewalld/zones/public.xml', '/etc/firewalld/direct.xml',
         '/var/lib/fds-change/CR-P1-NTP-01-01/original-ntp-pair.json',
         '/var/lib/fds-change/CR-P1-NTP-01-01/original-ntp-dropin.json')


class Stop(ValueError):
    pass


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Stop('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def request(raw):
    if len(raw) > MAX_REQUEST:
        raise Stop('Request exceeds 64 KiB')
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {'schema_version', 'action', 'run_id', 'host'}:
        raise Stop('Request keys differ from the exact schema')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise Stop('Unsupported schema')
    if not isinstance(value['action'], str) or value['action'] not in ACTIONS:
        raise Stop('Unknown action')
    if not isinstance(value['host'], str) or value['host'] not in HOSTS:
        raise Stop('Host is outside the fixed six-host scope')
    if not isinstance(value['run_id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{19,63}', value['run_id']):
        raise Stop('Run identifier must be 20-64 safe characters')
    return value


def command(argv, timeout=20):
    """Bound disk-backed outputs and wait; never inherit untrusted command options."""
    env = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'LANG': 'C'}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env)
            try:
                code = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                code = 124
        except OSError as exc:
            return {'argv': argv, 'rc': 127, 'stdout': '', 'stderr': str(exc)}
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(MAX_OUTPUT + 1), err.read(MAX_OUTPUT + 1)
    if len(stdout) > MAX_OUTPUT or len(stderr) > MAX_OUTPUT:
        raise Stop('Command output exceeds bound: ' + argv[0])
    return {'argv': argv, 'rc': code, 'stdout': stdout.decode('utf-8', 'replace'),
            'stderr': stderr.decode('utf-8', 'replace')}


def protected(path, directory=False, private=False):
    s = path.lstat()
    good_type = stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)
    if not good_type or s.st_uid != 0 or (s.st_mode & 0o022) or (private and s.st_mode & 0o077):
        raise Stop('Unsafe root-owned path: ' + str(path))
    if not directory and s.st_nlink != 1:
        raise Stop('Multiply linked journal/file refused: ' + str(path))
    return s


class Journal:
    """One host-wide advisory lock; fsync intent before each firewall mutation."""
    def __init__(self, req, base=BASE):
        self.req = req
        self.base = Path(base)
        for ancestor in reversed(self.base.parents):
            protected(ancestor, directory=True)
        try:
            self.base.mkdir(mode=0o700)
        except FileExistsError:
            pass
        protected(self.base, directory=True, private=True)
        fd = os.open(self.base / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'r+')
        protected(self.base / '.lock', private=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise Stop('Another onepass action holds the host lock') from exc
        self.directory = self.base / req['run_id']
        self.path = self.directory / 'state.json'
        if req['action'] == 'snapshot':
            try:
                self.directory.mkdir(mode=0o700)
            except FileExistsError:
                pass
        protected(self.directory, directory=True, private=True)
        if self.path.exists() or self.path.is_symlink():
            protected(self.path, private=True)
            raw = self.path.read_bytes()
            if len(raw) > MAX_STATE:
                raise Stop('Journal exceeds bounded state')
            self.data = json.loads(raw, object_pairs_hook=unique)
            if (self.data.get('schema_version') != 1 or self.data.get('host') != req['host']
                    or self.data.get('run_id') != req['run_id']):
                raise Stop('Journal identity does not match request')
        elif req['action'] == 'snapshot':
            self.data = {'schema_version': 1, 'host': req['host'], 'run_id': req['run_id'],
                         'created_at': utc(), 'snapshot': None, 'operations': []}
        else:
            raise Stop('Snapshot journal is missing')

    def save(self):
        raw = (json.dumps(self.data, sort_keys=True, indent=2) + '\n').encode()
        if len(raw) > MAX_STATE:
            raise Stop('Journal exceeds bounded state')
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            dfd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def close(self):
        self.lock.close()


def rich_rules():
    return ['rule family="ipv4" source address="%s/32" destination address="10.1.93.102/32" port port="123" protocol="udp" accept' % ip
            for host, ip in HOSTS.items() if host != SOURCE]


def ingress_objects():
    return [{'kind': 'rich', 'permanent': permanent, 'rule': rule}
            for permanent in (False, True) for rule in rich_rules()]


def egress_objects(host):
    allowed = UPSTREAMS if host == SOURCE else [HOSTS[SOURCE]]
    objects = []
    for permanent in (False, True):
        for family in ('ipv4', 'ipv6'):
            objects.append({'kind': 'chain', 'permanent': permanent, 'family': family, 'chain': CHAIN})
            rules = [(['-d', ip + '/32', '-j', 'RETURN'], str(i)) for i, ip in enumerate(allowed)] if family == 'ipv4' else []
            rules.append((['-j', 'DROP'], '99'))
            for args, priority in rules:
                objects.append({'kind': 'direct', 'permanent': permanent, 'family': family,
                                'chain': CHAIN, 'priority': priority, 'args': args})
            # Build full chain before linking; NEW excludes stateful NTP responses.
            objects.append({'kind': 'direct', 'permanent': permanent, 'family': family,
                            'chain': 'OUTPUT', 'priority': '0', 'args': ['-p', 'udp', '--dport', '123',
                                '-m', 'conntrack', '--ctstate', 'NEW', '-j', CHAIN]})
    return objects


def fw_args(obj, verb):
    args = [FIREWALL] + (['--permanent'] if obj['permanent'] else [])
    if obj['kind'] == 'rich':
        return args + ['--zone=public', '--%s-rich-rule=%s' % (verb, obj['rule'])]
    args += ['--direct', '--' + verb + '-' + ('chain' if obj['kind'] == 'chain' else 'rule'),
             obj['family'], 'filter', obj['chain']]
    if obj['kind'] == 'direct':
        args += [obj['priority']] + obj['args']
    return args


def parse_sample(tracking, sources, host):
    def field(pattern):
        values = re.findall(pattern, tracking, re.M)
        if len(values) != 1:
            raise Stop('Missing/duplicate chronyc tracking field')
        return values[0].strip()
    leap = field(r'^Leap status\s*:\s*([^\r\n]+)$')
    last = float(field(r'^Last offset\s*:\s*([+\-0-9.eE]+)\s+seconds\s*$'))
    current = float(field(r'^System time\s*:\s*([+\-0-9.eE]+)\s+seconds\s+(?:fast|slow) of NTP time\s*$'))
    stratum = int(field(r'^Stratum\s*:\s*([0-9]+)\s*$'))
    rows = re.findall(r'^([\^=#][*+?x~-])\s+(\S+)\s+.*$', sources, re.M)
    expected = UPSTREAMS if host == SOURCE else [HOSTS[SOURCE]]
    selected = [address for state, address in rows if state == '^*']
    passed = (leap == 'Normal' and 1 <= stratum <= 15
              and all(math.isfinite(v) and abs(v) <= .1 for v in (last, current))
              and sorted(address for _, address in rows) == sorted(expected)
              and len(selected) == 1 and selected[0] in expected)
    return {'tracking_raw': tracking, 'sources_raw': sources, 'selected_source': selected[0] if len(selected) == 1 else None,
            'last_offset_seconds': last if math.isfinite(last) else None,
            'system_offset_seconds': current if math.isfinite(current) else None, 'leap': leap,
            'stratum': stratum, 'pass': passed, 'observed_at': utc()}


class Engine:
    def __init__(self, req, journal, runner=command, sender=None):
        self.req, self.journal, self.runner = req, journal, runner
        self.sender = sender or self.send_test_flow
        self.changed, self.details = False, {}

    def run(self, argv, okay=(0,), timeout=20):
        value = self.runner(argv, timeout=timeout)
        if value['rc'] not in okay:
            raise Stop('Command failed rc=%s: %s; %s' % (value['rc'], ' '.join(argv), value['stderr'][:2000]))
        return value

    def exists(self, obj):
        return self.run(fw_args(obj, 'query'), okay=(0, 1))['rc'] == 0

    def identity(self):
        if os.geteuid() != 0 or socket.gethostname().split('.')[0] != self.req['host']:
            raise Stop('Root/hostname binding failed')
        rows = json.loads(self.run(['/usr/sbin/ip', '-j', '-4', 'addr', 'show', 'dev', 'ens160'])['stdout'])
        addresses = {a.get('local') for row in rows for a in row.get('addr_info', []) if a.get('family') == 'inet'}
        if HOSTS[self.req['host']] not in addresses or addresses.intersection(HOSTS.values()) != {HOSTS[self.req['host']]}:
            raise Stop('Fixed host address must be present only on expected ens160 binding')
        self.run([FIREWALL, '--state'])
        zone = self.run([FIREWALL, '--get-zone-of-interface=ens160'])['stdout'].strip()
        if zone != 'public':
            raise Stop('ens160 no longer belongs to public zone')

    def read_file(self, name):
        p = Path(name)
        if not p.exists() and not p.is_symlink():
            return {'path': name, 'exists': False}
        s = protected(p)
        with p.open('rb') as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise Stop('Snapshot file is too large: ' + name)
        return {'path': name, 'exists': True, 'uid': s.st_uid, 'gid': s.st_gid,
                'mode': oct(stat.S_IMODE(s.st_mode)), 'sha256': hashlib.sha256(data).hexdigest(),
                'base64': base64.b64encode(data).decode('ascii')}

    def snapshot(self):
        self.topology()
        if self.journal.data['snapshot'] is not None:
            if self.journal.data['snapshot'].get('status') != 'COMPLETE':
                raise Stop('Prior snapshot is incomplete; preserve it and start a new run')
            self.details = {'snapshot_reused': True, 'created_at': self.journal.data['snapshot']['created_at']}
            return
        observations = {}
        snapshot = {'status': 'COLLECTING', 'created_at': utc(), 'files': [], 'observations': observations}
        self.journal.data['snapshot'] = snapshot
        self.journal.save()
        for key, argv in (
            ('firewalld_version', [FIREWALL, '--version']),
            ('runtime_zones', [FIREWALL, '--list-all-zones']),
            ('permanent_zones', [FIREWALL, '--permanent', '--list-all-zones']),
            ('runtime_policies', [FIREWALL, '--list-all-policies']),
            ('permanent_policies', [FIREWALL, '--permanent', '--list-all-policies']),
            ('runtime_direct', [FIREWALL, '--direct', '--get-all-rules']),
            ('permanent_direct', [FIREWALL, '--permanent', '--direct', '--get-all-rules']),
            ('runtime_passthroughs', [FIREWALL, '--direct', '--get-all-passthroughs']),
            ('permanent_passthroughs', [FIREWALL, '--permanent', '--direct', '--get-all-passthroughs']),
            ('nft_ruleset', ['/usr/sbin/nft', '-a', 'list', 'ruleset']),
            ('iptables', ['/usr/sbin/iptables-save']), ('ip6tables', ['/usr/sbin/ip6tables-save']),
            ('chronyd_service', ['/usr/bin/systemctl', 'show', 'chronyd', '--property=ActiveState,SubState,UnitFileState']),
            ('tracking', ['/usr/bin/chronyc', '-n', 'tracking']),
            ('sources', ['/usr/bin/chronyc', '-n', 'sources', '-a'])):
            observations[key] = self.runner(argv, timeout=20)
            self.journal.save()
            if observations[key]['rc'] != 0:
                raise Stop('Snapshot command failed; partial originals preserved: ' + key)
        files = snapshot['files']
        for name in FILES:
            files.append(self.read_file(name))
            self.journal.save()
        snapshot['ingress_before'] = [{'object': obj, 'present': self.exists(obj)} for obj in ingress_objects()] if self.req['host'] == SOURCE else []
        snapshot['status'] = 'COMPLETE'
        self.journal.save()
        self.details = {'snapshot_created': True, 'files_sha256': {f['path']: f.get('sha256') for f in files},
                        'created_at': self.journal.data['snapshot']['created_at']}

    def pending_guard(self):
        if any(op['state'] in ('PREPARED', 'REMOVE_PREPARED', 'UNCERTAIN') for op in self.journal.data['operations']):
            raise Stop('Uncertain prior mutation requires journal reconciliation; no automatic replay/removal')

    def add(self, obj, group):
        operations = self.journal.data['operations']
        prior = next((op for op in operations if op['object'] == obj and op['group'] == group), None)
        present = self.exists(obj)
        if prior:
            if prior['state'] in ('ADDED', 'PREEXISTING') and present:
                return
            raise Stop('Recorded object changed or was rolled back; start a reviewed new run')
        op = {'object': obj, 'group': group, 'state': 'PREEXISTING' if present else 'PREPARED',
              'prepared_at': utc()}
        operations.append(op)
        self.journal.save()
        if present:
            return
        try:
            result = self.runner(fw_args(obj, 'add'), timeout=20)
            op['result'] = result
            # A timeout/error can be post-commit; keep uncertain intent, never infer ownership.
            if result['rc'] != 0 or 'ALREADY_ENABLED' in result['stdout'] + result['stderr']:
                op['state'] = 'UNCERTAIN'
                self.journal.save()
                raise Stop('Firewall add did not complete unambiguously; inspect journal before retry')
            op['state'] = 'ADDED'
            op['completed_at'] = utc()
            self.journal.save()
            self.changed = True
            if not self.exists(obj):
                raise Stop('Firewall did not retain newly added object')
        except BaseException:
            # PREPARED already persisted if transport/process interrupted before result.
            raise

    def ingress(self):
        if self.req['host'] != SOURCE:
            raise Stop('Ingress mutations are restricted to control01')
        self.pending_guard()
        for obj in ingress_objects():
            self.add(obj, 'ingress')
        self.details = {'runtime_and_permanent_rules_present': 10}

    def topology(self):
        """Do not share a custom chain or compete with existing direct OUTPUT rules."""
        import shlex
        expected = egress_objects(self.req['host'])
        for permanent in (False, True):
            prefix = [FIREWALL] + (['--permanent'] if permanent else []) + ['--direct']
            all_rules = self.run(prefix + ['--get-all-rules'])['stdout']
            expected_rows = {tuple([o['family'], 'filter', o['chain'], o['priority']] + o['args'])
                             for o in expected if o['kind'] == 'direct' and o['permanent'] == permanent}
            for line in all_rules.splitlines():
                row = shlex.split(line)
                if len(row) < 4:
                    raise Stop('Malformed direct rule listing')
                if CHAIN in row[4:] and row[2] not in (CHAIN, 'OUTPUT'):
                    raise Stop('Foreign direct hook references the dedicated chain')
                if row[1] == 'filter' and row[2] in (CHAIN, 'OUTPUT') and tuple(row) not in expected_rows:
                    raise Stop('Foreign direct OUTPUT/owned-chain rule conflicts with narrow NTP enforcement')
            if not permanent:
                self.kernel_topology(all_rules)
            passthroughs = self.run(prefix + ['--get-all-passthroughs'])['stdout']
            if re.search(r'\b(?:OUTPUT|OUTPUT_direct|FDS_NTP_0101)\b', passthroughs):
                raise Stop('OUTPUT/owned-chain passthrough requires independent review')
            for family in ('ipv4', 'ipv6'):
                chain = {'kind': 'chain', 'permanent': permanent, 'family': family, 'chain': CHAIN}
                if self.exists(chain):
                    expected_chain = [o for o in expected if o['permanent'] == permanent and o['family'] == family]
                    ledger_owns = any(op['object'] == chain and op['state'] == 'ADDED' for op in self.journal.data['operations'])
                    if not ledger_owns and not all(self.exists(o) for o in expected_chain):
                        raise Stop('Preexisting dedicated chain is incomplete or belongs to another deployment')

    def kernel_topology(self, registered):
        """Match either exact kernel layout; reject unknown paths before the hook."""
        import shlex
        registered_rows = [shlex.split(line) for line in registered.splitlines()]
        def canonical(args):
            # iptables-save spells the automatic UDP extension explicitly.
            clean = []
            index = 0
            while index < len(args):
                if args[index:index + 2] == ['-m', 'udp']:
                    index += 2
                    continue
                clean.append(args[index])
                index += 1
            return tuple(clean)
        for family, binary in (('ipv4', '/usr/sbin/iptables-save'), ('ipv6', '/usr/sbin/ip6tables-save')):
            def refuse(message):
                raise Stop(family + ': ' + message)
            rows = self.run([binary])['stdout'].splitlines()
            table, declarations, actual = None, set(), []
            for line in rows:
                if line.startswith('*'):
                    table = line[1:]
                elif line == 'COMMIT':
                    table = None
                elif line.startswith(':'):
                    name = line[1:].split()[0]
                    if name in (CHAIN, 'OUTPUT_direct') and table != 'filter':
                        refuse('Dedicated chain declared outside filter table')
                    if table == 'filter':
                        if name in declarations:
                            refuse('Duplicate filter chain declaration')
                        declarations.add(name)
                elif line.startswith('-A '):
                    row = shlex.split(line)
                    if any(name in row for name in (CHAIN, 'OUTPUT_direct')) and table != 'filter':
                        refuse('Dedicated chain referenced outside filter table')
                    if table == 'filter':
                        actual.append(canonical(row))
            obj = {'kind': 'chain', 'permanent': False, 'family': family, 'chain': CHAIN}
            if (CHAIN in declarations) != self.exists(obj):
                refuse('Kernel dedicated chain differs from firewalld ownership registry')
            owned = [row for row in registered_rows
                     if row[0] == family and row[1] == 'filter' and row[2] in (CHAIN, 'OUTPUT')]
            if len({tuple(row) for row in owned}) != len(owned):
                refuse('Duplicate registered dedicated rule')
            def expected(chain):
                return [canonical(['-A', chain] + row[4:])
                        for row in sorted((row for row in owned if row[2] == chain), key=lambda row: int(row[3]))]
            body = [row for row in actual if row[1] == CHAIN]
            if body != expected(CHAIN):
                refuse('Actual dedicated rules or rule order differ from registered exact rules')
            hooks = expected('OUTPUT')
            chain_refs = [row for row in actual if CHAIN in row[2:]]
            bridge_refs = [row for row in actual if 'OUTPUT_direct' in row[2:]]
            direct_body = [row for row in actual if row[1] == 'OUTPUT_direct']
            output = [row for row in actual if row[1] == 'OUTPUT']
            bridge = ('-A', 'OUTPUT', '-j', 'OUTPUT_direct')
            entry = None
            if hooks:
                if len(hooks) != 1:
                    refuse('Expected exactly one registered NTP OUTPUT hook')
                hook = hooks[0]
                indirect_hook = ('-A', 'OUTPUT_direct') + hook[2:]
                if chain_refs == [hook] and not bridge_refs and 'OUTPUT_direct' not in declarations and not direct_body:
                    entry = hook
                elif (chain_refs == [indirect_hook] and bridge_refs == [bridge]
                      and 'OUTPUT_direct' in declarations and direct_body == [indirect_hook]):
                    entry = bridge
                else:
                    refuse('NTP hook layout is missing, duplicated, mixed, or foreign')
            else:
                # Preapply and rollback may retain empty owned/OUTPUT_direct chains.
                if chain_refs or direct_body:
                    refuse('Unregistered dedicated hook or OUTPUT_direct rule')
                if bridge_refs:
                    if bridge_refs != [bridge] or 'OUTPUT_direct' not in declarations:
                        refuse('Empty OUTPUT_direct bridge is duplicated, conditional, or foreign')
                    entry = bridge
            prefix = output[:output.index(entry)] if entry is not None else output
            if prefix:
                # The only observed predecessor is this exact drop-only kubelet
                # chain. Unknown ACCEPT/RETURN/goto/subchain paths require review.
                kube_jump = ('-A', 'OUTPUT', '-j', 'KUBE-FIREWALL')
                kube_drop = ('-A', 'KUBE-FIREWALL', '!', '-s', '127.0.0.0/8', '-d', '127.0.0.0/8',
                             '-m', 'comment', '--comment', 'block incoming localnet connections',
                             '-m', 'conntrack', '!', '--ctstate', 'RELATED,ESTABLISHED,DNAT', '-j', 'DROP')
                kube_body = [row for row in actual if row[1] == 'KUBE-FIREWALL']
                if (family != 'ipv4' or prefix != [kube_jump] or 'KUBE-FIREWALL' not in declarations
                        or kube_body != [kube_drop]):
                    refuse('Unreviewed OUTPUT predecessor could bypass NTP enforcement')

    def egress(self):
        self.pending_guard()
        self.topology()
        for obj in egress_objects(self.req['host']):
            self.add(obj, 'egress')
        self.details = {'mechanism': 'firewalld_direct_deprecated', 'chain': CHAIN,
                        'only_new_udp_destination_port': 123, 'forward_changed': False,
                        'allowed_ipv4': UPSTREAMS if self.req['host'] == SOURCE else [HOSTS[SOURCE]],
                        'ipv6_new_ntp': 'DROP'}

    def rollback(self, group):
        self.pending_guard()
        if group == 'egress':
            self.topology()
        count = 0
        for op in reversed(self.journal.data['operations']):
            if op['group'] != group or op['state'] != 'ADDED':
                continue
            obj = op['object']
            if group == 'egress' and obj['kind'] == 'chain':
                self.topology()
            present = self.exists(obj)
            op['state'] = 'REMOVE_PREPARED'
            self.journal.save()
            if present:
                result = self.runner(fw_args(obj, 'remove'), timeout=20)
                op['remove_result'] = result
                if result['rc'] != 0:
                    op['state'] = 'UNCERTAIN'
                    self.journal.save()
                    raise Stop('Firewall removal uncertain; no further automatic rollback')
                self.changed = True
                if self.exists(obj):
                    op['state'] = 'UNCERTAIN'
                    self.journal.save()
                    raise Stop('Removed object still exists')
            op['state'] = 'REMOVED'
            op['removed_at'] = utc()
            self.journal.save()
            count += 1
        self.details = {'owned_objects_removed': count, 'preexisting_objects_preserved': True}

    def drop_counter(self):
        result = self.run(['/usr/sbin/iptables', '-w', '5', '-n', '-v', '-x', '-L', CHAIN, '--line-numbers'])
        rows = [line.split() for line in result['stdout'].splitlines()]
        drops = [int(row[1]) for row in rows if len(row) >= 4 and row[0].isdigit() and row[1].isdigit() and row[3] == 'DROP']
        if len(drops) != 1:
            raise Stop('Cannot identify exactly one owned IPv4 DROP counter')
        return drops[0]

    def send_test_flow(self):
        # Destination is TEST-NET, not an unapproved live NTP service. Only run
        # after exact restrictive rules are present; no external reply is sought.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.bind((HOSTS[self.req['host']], 0))
            source_port = sock.getsockname()[1]
            sent = sock.sendto(b'\x23' + b'\0' * 47, ('192.0.2.123', 123))
        if sent != 48:
            raise Stop('Negative test packet was not submitted completely')
        return {'destination': '192.0.2.123', 'port': 123, 'source_port': source_port, 'bytes': sent}

    def verify(self):
        self.pending_guard()
        self.topology()
        objects = egress_objects(self.req['host']) + (ingress_objects() if self.req['host'] == SOURCE else [])
        if not all(self.exists(obj) for obj in objects):
            raise Stop('Expected runtime/permanent firewall object is missing')
        before = self.drop_counter()
        packet = self.sender()
        after = self.drop_counter()
        self.details = {'configuration_present': True, 'negative_ipv4_probe': dict(packet, counter_before=before,
                        counter_after=after, **{'pass': after > before}), 'ipv6_packet_test': 'NOT_PERFORMED',
                        'positive_ntp_packets': 'CONTROLLER_APPROVED_PROBE_REQUIRED',
                        'reboot_persistence': 'NOT_TESTED', 'existing_conntrack': 'PRESERVED_NOT_FLUSHED'}
        if after <= before:
            raise Stop('Negative test did not increment the owned DROP counter; timeout is not proof')

    def sample(self):
        tracking = self.run(['/usr/bin/chronyc', '-n', 'tracking'])
        sources = self.run(['/usr/bin/chronyc', '-n', 'sources', '-a'])
        self.details = parse_sample(tracking['stdout'], sources['stdout'], self.req['host'])
        if not self.details['pass']:
            raise Stop('Current chrony sample fails exact source/leap/stratum/100ms checks')

    def dispatch(self):
        if self.req['action'] != 'snapshot' and (self.journal.data['snapshot'] is None or self.journal.data['snapshot'].get('status') != 'COMPLETE'):
            raise Stop('Completed snapshot is required')
        action = self.req['action']
        if action.startswith('rollback_'):
            self.rollback(action.removeprefix('rollback_'))
        else:
            getattr(self, action)()
        return self.details


def main(request_data=None):
    result, journal, engine = {'schema_version': 1, 'status': 'STOP', 'changed': False, 'details': {}}, None, None
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1) if request_data is None else json.dumps(request_data).encode('utf-8')
        req = request(raw)
        result.update(req)
        # Refuse before writing journal if root/host/interface binding does not hold.
        probe = Engine(req, None)
        probe.identity()
        journal = Journal(req)
        engine = Engine(req, journal)
        result['journal_path'] = str(journal.path)
        result['details'] = engine.dispatch()
        result['changed'] = engine.changed
        result['status'] = 'OK'
    except Exception as exc:
        result['error'] = '%s: %s' % (type(exc).__name__, str(exc))
        if engine:
            result['changed'], result['details'] = engine.changed, engine.details
    finally:
        if journal:
            state_raw = json.dumps(journal.data, sort_keys=True, separators=(',', ':')).encode()
            result['journal_receipt'] = {'state_sha256': hashlib.sha256(state_raw).hexdigest(),
                'digest_encoding': 'JSON sort_keys=True separators=(comma,colon), UTF-8',
                'operations': journal.data['operations'],
                'snapshot_sha256': hashlib.sha256(json.dumps(journal.data['snapshot'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
            if result.get('action') == 'snapshot':
                result['journal_receipt']['snapshot'] = journal.data['snapshot']
            journal.close()
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'OK' else 2


if __name__ == '__main__':
    raise SystemExit(main())
