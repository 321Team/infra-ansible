#!/usr/bin/env python3
"""Restricted verifier for one retained NTP run; no configuration/journal writes."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

PRIOR_RUN_ID = 'ntp-onepass-f9392ba915da49a19e0fe502e7616cfb'
BASE_SHA256 = 'ccdfd29e6d4821e4205963990b7c29af879240b1aae76c40119966fc67eebf50'
BASELINE_SOURCE_SHA256 = '11ea3cf62d3709d902120aca58264f6160725f5045568d4040d4119e54c7b7a9'
ACTIONS = {'preflight', 'verify', 'sample', 'finalize'}
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
    current = now or datetime.datetime.now(datetime.timezone.utc)
    if require_active and not a <= current < b:
        raise ValueError('Outside the explicitly supplied followup work window')
    return a, b


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
        elif row.startswith('-A ') and table != 'filter':
            raise ValueError('Nonfilter rules differ from the reviewed empty field baseline')
        rows.append(re.sub(r'\[[0-9]+:[0-9]+\]', '[COUNTERS]', row))
    if table is not None or not any(row == '*filter' for row in rows):
        raise ValueError('Incomplete iptables-save table stream')
    return '\n'.join(rows) + '\n'


def normalize_nft(text):
    # Do not trim whitespace, reorder rules, ignore handles or discard expressions.
    # Native inet firewalld is absent from iptables-save and must also be bound.
    return re.sub(r'\bcounter packets [0-9]+ bytes [0-9]+\b', 'counter packets COUNTER bytes COUNTER', text)


def validate_request(req):
    keys = {'schema_version', 'action', 'host', 'prior_run_id', 'followup_run_id',
            'window_start', 'window_end', 'expected_preservation'}
    if not isinstance(req, dict) or set(req) != keys or type(req['schema_version']) is not int or req['schema_version'] != 1:
        raise ValueError('Exact followup request schema required')
    if req['action'] not in ACTIONS or req['host'] not in HOSTS or req['prior_run_id'] != PRIOR_RUN_ID:
        raise ValueError('Request exceeds the fixed action/host/prior-run scope')
    if not isinstance(req['followup_run_id'], str) or not re.fullmatch(r'ntp-post-egress-[a-f0-9]{32}', req['followup_run_id']):
        raise ValueError('Fresh followup evidence identity required')
    expected = req['expected_preservation']
    if (req['action'] == 'preflight' and expected is not None) or (req['action'] != 'preflight' and not isinstance(expected, dict)):
        raise ValueError('Only preflight may establish the preservation receipt')
    validate_window(req['window_start'], req['window_end'])
    return req


def load_base(source):
    if not isinstance(source, str) or digest(source.encode()) != BASE_SHA256:
        raise ValueError('Approved PR32 remote source hash differs')
    scope = {'__name__': 'fds_ntp_followup_approved_engine'}
    exec(compile(source, 'ntp-onepass-remote.py', 'exec'), scope)
    if scope['FILES'] != PRESERVED_FILES:
        raise ValueError('Preserved file contract differs from the approved engine')
    return type('ApprovedEngine', (), scope)


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
    def __init__(self, req, base_engine, journal, runner=None, sender=None):
        self.req, self.m, self.journal = req, base_engine, journal
        self.runner = runner or self.m.command
        self.sender = sender
        self.records = []
        self.record_bytes = 0
        self.before = None
        self.after = None
        original = {'schema_version': 1, 'action': 'verify', 'run_id': PRIOR_RUN_ID, 'host': req['host']}
        self.engine = self.m.Engine(original, journal, runner=self.read_command, sender=self.send)

    def guard(self):
        validate_window(self.req['window_start'], self.req['window_end'])

    def allowed_commands(self):
        allowed = [['/usr/sbin/ip', '-j', '-4', 'addr', 'show', 'dev', 'ens160'],
                   [self.m.FIREWALL, '--state'], [self.m.FIREWALL, '--get-zone-of-interface=ens160'],
                   ['/usr/sbin/iptables-save'], ['/usr/sbin/ip6tables-save'],
                   ['/usr/sbin/nft', 'list', 'ruleset'],
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
        self.guard()
        if argv not in self.allowed_commands():
            raise ValueError('Command outside the exact read-only followup allowlist')
        value = self.runner(argv, timeout=timeout)
        size = len(json.dumps(value).encode())
        if self.record_bytes + size > 4 * 1024 * 1024:
            self.records.append({'argv': argv, 'evidence_limit_exceeded': True, 'observed_record_bytes': size})
            raise ValueError('Bounded followup command evidence exceeds 4 MiB')
        self.record_bytes += size
        self.records.append(value)
        return value

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
        kernel = {}
        for label, argv, normalize in (
                ('iptables', ['/usr/sbin/iptables-save'], normalize_iptables),
                ('ip6tables', ['/usr/sbin/ip6tables-save'], normalize_iptables),
                ('nft', ['/usr/sbin/nft', 'list', 'ruleset'], normalize_nft)):
            value = self.engine.run(argv)
            kernel[label] = digest(normalize(value['stdout']).encode())
            if kernel[label] != BASELINE[self.req['host']]['kernel'][label]:
                raise ValueError(label + ': rules differ from reviewed field baseline; retain raw output and review')
        return {'files': files, 'kernel': kernel, 'journal_sha256': digest(self.journal.read())}

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
        try:
            if self.req['action'] == 'verify':
                self.engine.verify()
                details = self.engine.details
            elif self.req['action'] == 'sample':
                self.engine.sample()
                details = self.engine.details
        finally:
            after = self.preservation()
            self.after = after
            if after != before:
                raise ValueError('Configuration/kernel/journal changed during followup; preserve state, no rollback')
        self.guard()
        return {'observation': details, 'preservation_before': before, 'preservation_after': after,
                'configuration_unchanged': True, 'journal_unchanged': True}


def main(req, base_source):
    result = {'schema_version': 1, 'status': 'STOP', 'changed': False}
    journal, verifier = None, None
    try:
        validate_request(req)
        result.update(req)
        m = load_base(base_source)
        # Identity precedes opening even the existing journal lock.
        probe_req = {'schema_version': 1, 'action': 'verify', 'run_id': PRIOR_RUN_ID, 'host': req['host']}
        m.Engine(probe_req, None).identity()
        journal = ReadOnlyJournal(req, m)
        verifier = Verifier(req, m, journal)
        result['details'] = verifier.execute()
        result['status'] = 'OK'
    except Exception as exc:
        result['error'] = '%s: %s' % (type(exc).__name__, exc)
    finally:
        if verifier is not None:
            result['commands'] = verifier.records
            result.setdefault('details', {'observation': verifier.engine.details,
                'preservation_before': verifier.before, 'preservation_after': verifier.after})
        if journal is not None:
            try:
                result['journal_sha256_after'] = digest(journal.read())
                if result['journal_sha256_after'] != BASELINE[req['host']]['journal_sha256']:
                    raise ValueError('Original journal changed before release')
            except Exception as exc:
                result.update(status='STOP', preservation_uncertain=True,
                              preservation_error='%s: %s' % (type(exc).__name__, exc))
            finally:
                journal.close()
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'OK' else 2
