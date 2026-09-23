#!/usr/bin/env python3
"""Restricted verifier for one retained NTP run; no configuration/journal writes."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import time

PRIOR_RUN_ID = 'ntp-onepass-f9392ba915da49a19e0fe502e7616cfb'
BASE_SHA256 = '28e59bfd517661439f2a2c794824b0d19de3218e5101e143656ff5a865e3f1b2'
KERNEL_SHA256 = '7cb9d316245dc60f0f0690326e7a6db670e84742c627aad5fd16802a25f04d3f'
BASELINE_SOURCE_SHA256 = '11ea3cf62d3709d902120aca58264f6160725f5045568d4040d4119e54c7b7a9'
ACTIONS = {'preflight', 'verify', 'sample', 'finalize'}
KERNEL_COMMANDS = (('/usr/sbin/iptables-save',), ('/usr/sbin/ip6tables-save',),
                   ('/usr/sbin/nft', 'list', 'ruleset'), ('/usr/sbin/ipset', 'save'))
PRESERVED_FILES = ('/etc/chrony.conf', '/etc/chrony.d/50-cr-p1-ntp-01-01.conf',
                   '/etc/sysconfig/chronyd', '/etc/firewalld/firewalld.conf',
                   '/etc/firewalld/zones/public.xml', '/etc/firewalld/direct.xml',
                   '/var/lib/fds-change/CR-P1-NTP-01-01/original-ntp-pair.json',
                   '/var/lib/fds-change/CR-P1-NTP-01-01/original-ntp-dropin.json')
HOSTS = {'k8s-control01': '10.1.93.102', 'k8s-control02': '10.1.93.103',
         'k8s-control03': '10.1.93.104', 'k8s-worker01': '10.1.93.105',
         'k8s-worker02': '10.1.93.107', 'k8s-worker03': '10.1.93.108'}
BASELINE = {'k8s-control01': {'files': {'/etc/chrony.conf': {'exists': True,
                                                  'gid': 0,
                                                  'mode': '0o644',
                                                  'sha256': '949287680df0590a15a68cdf9236f7c7176bd4355eedbbe858f9c66e18e3075e',
                                                  'uid': 0},
                             '/etc/chrony.d/50-cr-p1-ntp-01-01.conf': {'exists': True,
                                                                       'gid': 0,
                                                                       'mode': '0o644',
                                                                       'sha256': '5ebb2911e7b1e2a726f0a24dfacb1269c110897af80fd474771c5de1071b716b',
                                                                       'uid': 0},
                             '/etc/firewalld/direct.xml': {'exists': True,
                                                           'gid': 0,
                                                           'mode': '0o644',
                                                           'sha256': '70a322b243735569f7653d2bf18514c5a877be44f86ca60e61b385f0aa1378d3',
                                                           'uid': 0}},
                   'journal_canonical_sha256': '11fe04e8a2bc2131dba6df83b2d05d182cd4f0b7f39099e38d4be991e77586b5',
                   'journal_sha256': 'a1fe441c24d00c609d04760543322d67c89c279938e71f810f2773c95711be71',
                   'kernel': {'ip6tables': 'f036008460ff5a303fe9fa57595945694cb14dd0d215beea1aee8dc0e18b6615',
                              'iptables': '7463cbf63e245274dc51b72cdf9b607c842fe539f3d4ab07368c4ced3cedf121',
                              'nft': '5f732bac463bed742671d75d04422f02dbc02714ad671d40981a6fe1aa598b54'}},
 'k8s-control02': {'files': {'/etc/chrony.conf': {'exists': True,
                                                  'gid': 0,
                                                  'mode': '0o644',
                                                  'sha256': '949287680df0590a15a68cdf9236f7c7176bd4355eedbbe858f9c66e18e3075e',
                                                  'uid': 0},
                             '/etc/chrony.d/50-cr-p1-ntp-01-01.conf': {'exists': True,
                                                                       'gid': 0,
                                                                       'mode': '0o644',
                                                                       'sha256': '3d516d3aad2498b4fe274a2e9162d3f36f078b78e031c1eac7df92eba816057d',
                                                                       'uid': 0},
                             '/etc/firewalld/direct.xml': {'exists': True,
                                                           'gid': 0,
                                                           'mode': '0o644',
                                                           'sha256': '097d04f50675cfea65d660484117f5c58768a304c434923b6259462e04f3eccd',
                                                           'uid': 0}},
                   'journal_canonical_sha256': 'c340d18edf9eccfb8ea4c90ebecf2bd13566706e55f1164f1d83d629e3acf5fd',
                   'journal_sha256': '58dbbee952a040f814160a16a7f3324985fda3891bf17421d2de55062981bb2a',
                   'kernel': {'ip6tables': 'f036008460ff5a303fe9fa57595945694cb14dd0d215beea1aee8dc0e18b6615',
                              'iptables': '712f2ba08f1b76e819e8274e2de7f8f35cfd432a3e72dc0f416d3cf7aaeb2eaf',
                              'nft': 'd818aa322b79b44ad47d4317a2b8c781a076afb69cfd24411fb6b4cd72e7edc2'}},
 'k8s-control03': {'files': {'/etc/chrony.conf': {'exists': True,
                                                  'gid': 0,
                                                  'mode': '0o644',
                                                  'sha256': '949287680df0590a15a68cdf9236f7c7176bd4355eedbbe858f9c66e18e3075e',
                                                  'uid': 0},
                             '/etc/chrony.d/50-cr-p1-ntp-01-01.conf': {'exists': True,
                                                                       'gid': 0,
                                                                       'mode': '0o644',
                                                                       'sha256': '3d516d3aad2498b4fe274a2e9162d3f36f078b78e031c1eac7df92eba816057d',
                                                                       'uid': 0},
                             '/etc/firewalld/direct.xml': {'exists': True,
                                                           'gid': 0,
                                                           'mode': '0o644',
                                                           'sha256': '097d04f50675cfea65d660484117f5c58768a304c434923b6259462e04f3eccd',
                                                           'uid': 0}},
                   'journal_canonical_sha256': 'e25e5dc72611e2df1b8c488a14fff8defed37a9fece3963c3751e56ffaf6aa7b',
                   'journal_sha256': '6a982290575f10b638b4d5bf4b017d39df8c5835c3a5e106febd3f2b5cb4c90e',
                   'kernel': {'ip6tables': 'f036008460ff5a303fe9fa57595945694cb14dd0d215beea1aee8dc0e18b6615',
                              'iptables': '712f2ba08f1b76e819e8274e2de7f8f35cfd432a3e72dc0f416d3cf7aaeb2eaf',
                              'nft': 'd818aa322b79b44ad47d4317a2b8c781a076afb69cfd24411fb6b4cd72e7edc2'}},
 'k8s-worker01': {'files': {'/etc/chrony.conf': {'exists': True,
                                                 'gid': 0,
                                                 'mode': '0o644',
                                                 'sha256': '949287680df0590a15a68cdf9236f7c7176bd4355eedbbe858f9c66e18e3075e',
                                                 'uid': 0},
                            '/etc/chrony.d/50-cr-p1-ntp-01-01.conf': {'exists': True,
                                                                      'gid': 0,
                                                                      'mode': '0o644',
                                                                      'sha256': '3d516d3aad2498b4fe274a2e9162d3f36f078b78e031c1eac7df92eba816057d',
                                                                      'uid': 0},
                            '/etc/firewalld/direct.xml': {'exists': True,
                                                          'gid': 0,
                                                          'mode': '0o644',
                                                          'sha256': '097d04f50675cfea65d660484117f5c58768a304c434923b6259462e04f3eccd',
                                                          'uid': 0}},
                  'journal_canonical_sha256': '8389b27d913b837a80642760e40dd81ead1a2452ccc91c89252fd866d218f7fe',
                  'journal_sha256': 'ee7d72b327bdee46f06bfc6ba94104f2231e8db7e200dab76757cfb79c433b12',
                  'kernel': {'ip6tables': 'f036008460ff5a303fe9fa57595945694cb14dd0d215beea1aee8dc0e18b6615',
                             'iptables': '712f2ba08f1b76e819e8274e2de7f8f35cfd432a3e72dc0f416d3cf7aaeb2eaf',
                             'nft': '2cf07cd728d51dbaa9502e39c5facc564fbdd321d0babc00a927567569634ace'}},
 'k8s-worker02': {'files': {'/etc/chrony.conf': {'exists': True,
                                                 'gid': 0,
                                                 'mode': '0o644',
                                                 'sha256': '949287680df0590a15a68cdf9236f7c7176bd4355eedbbe858f9c66e18e3075e',
                                                 'uid': 0},
                            '/etc/chrony.d/50-cr-p1-ntp-01-01.conf': {'exists': True,
                                                                      'gid': 0,
                                                                      'mode': '0o644',
                                                                      'sha256': '3d516d3aad2498b4fe274a2e9162d3f36f078b78e031c1eac7df92eba816057d',
                                                                      'uid': 0},
                            '/etc/firewalld/direct.xml': {'exists': True,
                                                          'gid': 0,
                                                          'mode': '0o644',
                                                          'sha256': '097d04f50675cfea65d660484117f5c58768a304c434923b6259462e04f3eccd',
                                                          'uid': 0}},
                  'journal_canonical_sha256': '88849569ea96796cab0be0ac1db5bcfa82afb5ac096ca2b289bba8b0a7559b0d',
                  'journal_sha256': '1626d1850897905c83c534175831ee5c429d8937b7c8a46a2fa47443ac261dd5',
                  'kernel': {'ip6tables': 'f036008460ff5a303fe9fa57595945694cb14dd0d215beea1aee8dc0e18b6615',
                             'iptables': '712f2ba08f1b76e819e8274e2de7f8f35cfd432a3e72dc0f416d3cf7aaeb2eaf',
                             'nft': 'da3d0d139cd77fa4d375f01a107331f59e6d20368be0ec37bb95e073a293fd92'}},
 'k8s-worker03': {'files': {'/etc/chrony.conf': {'exists': True,
                                                 'gid': 0,
                                                 'mode': '0o644',
                                                 'sha256': '949287680df0590a15a68cdf9236f7c7176bd4355eedbbe858f9c66e18e3075e',
                                                 'uid': 0},
                            '/etc/chrony.d/50-cr-p1-ntp-01-01.conf': {'exists': True,
                                                                      'gid': 0,
                                                                      'mode': '0o644',
                                                                      'sha256': '3d516d3aad2498b4fe274a2e9162d3f36f078b78e031c1eac7df92eba816057d',
                                                                      'uid': 0},
                            '/etc/firewalld/direct.xml': {'exists': True,
                                                          'gid': 0,
                                                          'mode': '0o644',
                                                          'sha256': '097d04f50675cfea65d660484117f5c58768a304c434923b6259462e04f3eccd',
                                                          'uid': 0}},
                  'journal_canonical_sha256': 'c7f609c57db1a620feda7144a92b361561711ac390d75eff2277c39cb172c800',
                  'journal_sha256': 'e0aab490a7e95ee8a67285a7c1416265a62c938b848c8a30e321cafe7e1845cd',
                  'kernel': {'ip6tables': 'f036008460ff5a303fe9fa57595945694cb14dd0d215beea1aee8dc0e18b6615',
                             'iptables': '712f2ba08f1b76e819e8274e2de7f8f35cfd432a3e72dc0f416d3cf7aaeb2eaf',
                             'nft': 'da3d0d139cd77fa4d375f01a107331f59e6d20368be0ec37bb95e073a293fd92'}}}  # Retained evidence; never learned at runtime.


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_window(start, end, now=None, require_active=True):
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError('Explicit timezone-aware start/end strings required')
    a, b = datetime.datetime.fromisoformat(start), datetime.datetime.fromisoformat(end)
    if a.tzinfo is None or b.tzinfo is None or a >= b:
        raise ValueError('Invalid timezone-aware work window')
    if a <= datetime.datetime(2026, 9, 21, 2, 35, tzinfo=datetime.timezone.utc):
        raise ValueError('A new window after the expired original window is required')
    if require_active:
        current = now or datetime.datetime.now(datetime.timezone.utc)
        if not a <= current < b:
            raise ValueError('Outside the explicitly supplied followup work window')
    return a, b


def clock_snapshot():
    """Linux boot clock includes suspend and cannot be stepped by NTP."""
    return {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'boottime_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME)}


def validate_clock_binding(binding):
    keys = {'boot_id', 'sampled_boottime_ns', 'deadline_boottime_ns', 'controller_received_at'}
    if not isinstance(binding, dict) or set(binding) != keys:
        raise ValueError('Exact controller-authoritative clock binding required')
    if (not isinstance(binding['boot_id'], str) or not re.fullmatch(
            r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', binding['boot_id']) or
            any(type(binding[key]) is not int or binding[key] <= 0
                for key in ('sampled_boottime_ns', 'deadline_boottime_ns')) or
            binding['deadline_boottime_ns'] <= binding['sampled_boottime_ns'] or
            not isinstance(binding['controller_received_at'], str)):
        raise ValueError('Invalid controller-authoritative clock binding')
    received = datetime.datetime.fromisoformat(binding['controller_received_at'])
    if received.tzinfo is None:
        raise ValueError('Controller receipt time must be timezone-aware')
    current = clock_snapshot()
    if (current['boot_id'] != binding['boot_id'] or
            not binding['sampled_boottime_ns'] <= current['boottime_ns'] < binding['deadline_boottime_ns']):
        raise ValueError('Remote boot changed or fixed controller work-window deadline expired')
    return (binding['deadline_boottime_ns'] - current['boottime_ns']) / 1_000_000_000


def normalize_iptables(text):
    """Keep every structural byte except save timestamps and numeric counters."""
    rows, table = [], None
    for row in text.splitlines():
        if row.startswith('#'):
            continue
        if row.startswith('*'):
            if table is not None:
                raise ValueError('Nested iptables table')
            table = row[1:]
        elif row == 'COMMIT':
            if table is None:
                raise ValueError('Unexpected iptables COMMIT')
            table = None
        rows.append(re.sub(r'\[[0-9]+:[0-9]+\]', '[COUNTERS]', row))
    if table is not None or not any(row == '*filter' for row in rows):
        raise ValueError('Incomplete iptables-save table stream')
    return '\n'.join(rows) + '\n'


def normalize_nft(text):
    # Do not trim whitespace, reorder rules, ignore handles or discard expressions.
    # Native inet firewalld is absent from iptables-save and must also be bound.
    return re.sub(r'\bcounter packets [0-9]+ bytes [0-9]+\b', 'counter packets COUNTER bytes COUNTER', text)


def kernel_receipt(host, command_results, kernel_contract):
    """Validate a fresh complete observation before deriving preservation hashes."""
    if not isinstance(command_results, list) or len(command_results) != len(KERNEL_COMMANDS):
        raise ValueError('Four complete kernel command receipts are required')
    texts = []
    for argv, value in zip(KERNEL_COMMANDS, command_results):
        if (not isinstance(value, dict) or value.get('argv') != list(argv) or
                type(value.get('rc')) is not int or value['rc'] != 0 or
                not isinstance(value.get('stdout'), str) or not isinstance(value.get('stderr'), str) or
                any(value.get(key) for key in ('timeout', 'timed_out', 'interrupted', 'output_limit',
                                               'stdout_truncated', 'stderr_truncated', 'truncated'))):
            raise ValueError('Kernel observation is missing, incomplete or failed: ' + ' '.join(argv))
        texts.append(value['stdout'])
    contract = kernel_contract.validate_kernel(host, *texts)
    labels = ('iptables', 'ip6tables', 'nft', 'ipset')
    if (not isinstance(contract, dict) or set(contract) != {label + '_contract' for label in labels} or
            any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                for value in contract.values())):
        raise ValueError('Reviewed kernel contract returned an invalid receipt')
    normalized = (normalize_iptables(texts[0]), normalize_iptables(texts[1]),
                  normalize_nft(texts[2]), kernel_contract.normalize_ipset(texts[3]))
    if any(not isinstance(text, str) for text in normalized):
        raise ValueError('Kernel preservation normalization must return text')
    return {'kernel': {label: digest(text.encode()) for label, text in zip(labels, normalized)},
            'kernel_contract': dict(contract)}


def validate_request(req):
    keys = {'schema_version', 'action', 'host', 'prior_run_id', 'followup_run_id',
            'window_start', 'window_end', 'expected_preservation', 'clock_binding'}
    if not isinstance(req, dict) or set(req) != keys or type(req['schema_version']) is not int or req['schema_version'] != 1:
        raise ValueError('Exact followup request schema required')
    if req['action'] not in ACTIONS or req['host'] not in HOSTS or req['prior_run_id'] != PRIOR_RUN_ID:
        raise ValueError('Request exceeds the fixed action/host/prior-run scope')
    if not isinstance(req['followup_run_id'], str) or not re.fullmatch(r'ntp-post-egress-[a-f0-9]{32}', req['followup_run_id']):
        raise ValueError('Fresh followup evidence identity required')
    expected = req['expected_preservation']
    if (req['action'] == 'preflight' and expected is not None) or (req['action'] != 'preflight' and not isinstance(expected, dict)):
        raise ValueError('Only preflight may establish the preservation receipt')
    start, end = validate_window(req['window_start'], req['window_end'], require_active=False)
    validate_clock_binding(req['clock_binding'])
    received = datetime.datetime.fromisoformat(req['clock_binding']['controller_received_at'])
    if (not start <= received < end or
            req['clock_binding']['deadline_boottime_ns'] - req['clock_binding']['sampled_boottime_ns'] >
            int((end - received).total_seconds() * 1_000_000_000) - 10_000_000_000):
        raise ValueError('Clock binding exceeds controller receipt work-window budget')
    return req


def load_base(source):
    if not isinstance(source, str) or digest(source.encode()) != BASE_SHA256:
        raise ValueError('Approved PR32 remote source hash differs')
    scope = {'__name__': 'fds_ntp_followup_approved_engine'}
    exec(compile(source, 'ntp-onepass-remote.py', 'exec'), scope)
    if scope['FILES'] != PRESERVED_FILES:
        raise ValueError('Preserved file contract differs from the approved engine')
    return type('ApprovedEngine', (), scope)


def load_kernel(source):
    if not isinstance(source, str) or digest(source.encode()) != KERNEL_SHA256:
        raise ValueError('Reviewed kernel contract source hash differs')
    scope = {'__name__': 'fds_ntp_followup_kernel_contract'}
    exec(compile(source, 'ntp-kernel-contract.py', 'exec'), scope)
    if not callable(scope.get('validate_kernel')) or not callable(scope.get('normalize_ipset')):
        raise ValueError('Reviewed kernel contract API is incomplete')
    return type('ReviewedKernelContract', (), scope)


class ReadOnlyJournal:
    """Read an existing protected journal under its existing host-wide lock."""
    def __init__(self, req, base_engine, base=None):
        self.m = base_engine
        self.base = Path(base or self.m.BASE)
        self.lock_fd = None
        for directory in reversed([self.base] + list(self.base.parents)):
            self.m.protected(directory, directory=True, private=directory == self.base)
        lock_path = self.base / '.lock'
        info = self.m.protected(lock_path, private=True)
        fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError('Existing host lock changed while opening')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_fd = fd
            self.directory = self.base / PRIOR_RUN_ID
            self.m.protected(self.directory, directory=True, private=True)
            self.path = self.directory / 'state.json'
            self.raw = self.read()
            self.data = json.loads(self.raw, object_pairs_hook=self.m.unique)
            if (self.data.get('schema_version') != 1 or self.data.get('host') != req['host'] or
                    self.data.get('run_id') != PRIOR_RUN_ID or
                    not isinstance(self.data.get('snapshot'), dict) or self.data['snapshot'].get('status') != 'COMPLETE'):
                raise ValueError('Original journal identity/completed snapshot mismatch')
            operations = self.data.get('operations')
            if not isinstance(operations, list) or not operations or any(
                    not isinstance(op, dict) or op.get('state') not in ('ADDED', 'PREEXISTING') for op in operations):
                raise ValueError('Original journal has incomplete, removed or uncertain intent')
            expected = BASELINE[req['host']]
            if (digest(self.raw) != expected['journal_sha256'] or
                    digest(json.dumps(self.data, sort_keys=True, separators=(',', ':')).encode()) != expected['journal_canonical_sha256']):
                raise ValueError('Original journal bytes/ownership receipt differ from retained evidence')
        except BaseException:
            os.close(fd)
            self.lock_fd = None
            raise

    def read(self):
        info = self.m.protected(self.path, private=True)
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino) or info.st_size > self.m.MAX_STATE:
                raise ValueError('Original journal changed while opening or exceeds bound')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(self.m.MAX_STATE + 1)
        finally:
            os.close(fd)
        if len(raw) > self.m.MAX_STATE:
            raise ValueError('Original journal exceeds bound')
        return raw

    def save(self):
        raise ValueError('Followup cannot write the original journal')

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None


class Verifier:
    def __init__(self, req, base_engine, journal, runner=None, sender=None, kernel_contract=None):
        self.req, self.m, self.journal = req, base_engine, journal
        if kernel_contract is None:
            raise ValueError('A reviewed kernel contract is required; historical raw hashes cannot authorize a probe')
        self.kernel_contract = kernel_contract
        self.runner = runner or self.m.command
        self.sender = sender
        self.records = []
        self.record_bytes = 0
        self.before = None
        self.after = None
        self.operation_error = None
        self.preservation_error = None
        self.clock_remaining = None
        original = {'schema_version': 1, 'action': 'verify', 'run_id': PRIOR_RUN_ID, 'host': req['host']}
        owner = self
        class FollowupEngine(self.m.Engine):
            # Both topology() and verify() dispatch here; the approved mutation
            # engine remains unchanged and is never used to relax a packet gate.
            def kernel_topology(engine, registered):
                owner.kernel_topology(registered)
        self.engine = FollowupEngine(original, journal, runner=self.read_command, sender=self.send)

    def guard(self):
        remaining = validate_clock_binding(self.req['clock_binding'])
        if self.clock_remaining is not None and remaining > self.clock_remaining:
            raise ValueError('Remote boot clock moved backwards during the observation')
        self.clock_remaining = remaining
        return remaining

    def allowed_commands(self):
        allowed = [['/usr/sbin/ip', '-j', '-4', 'addr', 'show', 'dev', 'ens160'],
                   [self.m.FIREWALL, '--state'], [self.m.FIREWALL, '--get-zone-of-interface=ens160'],
                   ['/usr/sbin/iptables-save'], ['/usr/sbin/ip6tables-save'],
                   ['/usr/sbin/nft', 'list', 'ruleset'],
                   ['/usr/sbin/ipset', 'save'],
                   ['/usr/bin/chronyc', '-n', 'tracking'], ['/usr/bin/chronyc', '-n', 'sources', '-a'],
                   ['/usr/sbin/iptables', '-w', '5', '-n', '-v', '-x', '-L', self.m.CHAIN, '--line-numbers']]
        for permanent in (False, True):
            prefix = [self.m.FIREWALL] + (['--permanent'] if permanent else []) + ['--direct']
            allowed.extend(prefix + [flag] for flag in ('--get-all-rules', '--get-all-chains', '--get-all-passthroughs'))
        objects = self.m.egress_objects(self.req['host'])
        if self.req['host'] == self.m.SOURCE:
            objects += self.m.ingress_objects()
        allowed.extend(self.m.fw_args(obj, 'query') for obj in objects)
        return allowed

    def read_command(self, argv, timeout=20):
        remaining = self.guard()
        if remaining <= 1:
            raise ValueError('Read cannot fit the remaining fixed remote deadline')
        if argv not in self.allowed_commands():
            raise ValueError('Command outside the exact read-only followup allowlist')
        value = self.runner(argv, timeout=min(timeout, remaining - 1))
        size = len(json.dumps(value).encode())
        if self.record_bytes + size > 4 * 1024 * 1024:
            self.records.append({'argv': argv, 'evidence_limit_exceeded': True, 'observed_record_bytes': size})
            raise ValueError('Bounded followup command evidence exceeds 4 MiB')
        self.record_bytes += size
        self.records.append(value)
        return value

    def observe_kernel(self):
        commands = [self.engine.run(list(argv)) for argv in KERNEL_COMMANDS]
        return kernel_receipt(self.req['host'], commands, self.kernel_contract)

    def kernel_topology(self, registered):
        """Bind exact owned registry objects to the reviewed current kernel path."""
        rows = [shlex.split(line) for line in registered.splitlines()]
        if any(len(row) < 4 for row in rows):
            raise ValueError('Malformed direct rule listing')
        actual = [tuple(row) for row in rows if row[1] == 'filter' and row[2] in (self.m.CHAIN, 'OUTPUT')]
        expected = [tuple([obj['family'], 'filter', obj['chain'], obj['priority']] + obj['args'])
                    for obj in self.m.egress_objects(self.req['host'])
                    if obj['kind'] == 'direct' and not obj['permanent']]
        if sorted(actual) != sorted(expected) or len(set(actual)) != len(actual):
            raise ValueError('Runtime registered dedicated rules/hooks differ from exact reviewed objects')
        # The pinned contract also checks actual chain body/order, hook layout,
        # cross-table references and packet-relevant Calico/Kubernetes paths.
        current = self.observe_kernel()
        if self.before is not None and any(current[key] != self.before[key]
                                           for key in ('kernel', 'kernel_contract')):
            raise ValueError('Kernel/ipset changed since the preservation observation')

    def preservation(self):
        files = {}
        for name in self.m.FILES:
            value = self.engine.read_file(name)
            files[name] = {k: v for k, v in value.items() if k != 'base64'}
        if digest(self.journal.read()) != BASELINE[self.req['host']]['journal_sha256']:
            raise ValueError('Original journal changed during followup')
        for name, expected in BASELINE[self.req['host']]['files'].items():
            actual = files[name]
            if any(actual.get(key) != val for key, val in expected.items()):
                raise ValueError('Retained configuration baseline differs: ' + name)
        kernel = self.observe_kernel()
        return {'files': files, **kernel, 'journal_sha256': digest(self.journal.read())}

    def send(self):
        self.guard()
        if self.req['action'] != 'verify' or self.preservation() != self.req['expected_preservation']:
            raise ValueError('Packet requires matching reviewed preflight preservation receipt')
        self.guard()
        return self.sender() if self.sender is not None else self.engine.send_test_flow()

    def execute(self):
        self.guard()
        self.engine.identity()
        before = self.preservation()
        self.before = before
        expected = self.req['expected_preservation']
        if expected is not None and before != expected:
            raise ValueError('Configuration/kernel/journal drift since all-host preflight')
        self.engine.pending_guard()
        self.engine.topology()
        objects = self.m.egress_objects(self.req['host']) + (self.m.ingress_objects() if self.req['host'] == self.m.SOURCE else [])
        if not all(self.engine.exists(obj) for obj in objects):
            raise ValueError('Expected runtime/permanent firewall object missing')
        details = {}
        failure = None
        try:
            if self.req['action'] == 'verify':
                self.engine.verify()
                details = self.engine.details
            elif self.req['action'] == 'sample':
                self.engine.sample()
                details = self.engine.details
        except Exception as exc:
            self.operation_error = {'type': type(exc).__name__, 'message': str(exc)}
            failure = exc
        try:
            after = self.preservation()
            self.after = after
            if after != before:
                raise ValueError('Configuration/kernel/journal changed during followup; preserve state, no rollback')
        except Exception as exc:
            self.preservation_error = {'type': type(exc).__name__, 'message': str(exc)}
            if failure is None:
                failure = exc
        if failure is not None:
            raise failure
        self.guard()
        return {'observation': details, 'preservation_before': before, 'preservation_after': after,
                'configuration_unchanged': True, 'journal_unchanged': True}


def main(req, base_source, kernel_source=None):
    result = {'schema_version': 1, 'status': 'STOP', 'changed': False}
    journal, verifier = None, None
    try:
        validate_request(req)
        result.update(req)
        m = load_base(base_source)
        kernel = load_kernel(kernel_source)
        # Identity precedes opening even the existing journal lock.
        probe_req = {'schema_version': 1, 'action': 'verify', 'run_id': PRIOR_RUN_ID, 'host': req['host']}
        m.Engine(probe_req, None).identity()
        journal = ReadOnlyJournal(req, m)
        verifier = Verifier(req, m, journal, kernel_contract=kernel)
        result['details'] = verifier.execute()
        result['status'] = 'OK'
    except Exception as exc:
        result['error'] = '%s: %s' % (type(exc).__name__, exc)
    finally:
        if verifier is not None:
            result['commands'] = verifier.records
            if verifier.operation_error is not None:
                result['operation_error'] = verifier.operation_error
            if verifier.preservation_error is not None:
                result['preservation_error'] = verifier.preservation_error
                result['preservation_uncertain'] = True
            result.setdefault('details', {'observation': verifier.engine.details,
                'preservation_before': verifier.before, 'preservation_after': verifier.after})
        if journal is not None:
            try:
                result['journal_sha256_after'] = digest(journal.read())
                if result['journal_sha256_after'] != BASELINE[req['host']]['journal_sha256']:
                    raise ValueError('Original journal changed before release')
            except Exception as exc:
                result.update(status='STOP', preservation_uncertain=True,
                              journal_preservation_error={'type': type(exc).__name__, 'message': str(exc)})
            finally:
                journal.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'OK' else 2
