#!/usr/bin/env python3
"""Bounded NTP kernel contract candidate for the retained 2026-09-21 capture.

This is not a general netfilter interpreter.  It pins the observed critical
chains, hook inventory, native firewalld table and ipset membership.  Only exact
kube-proxy Service dispatch forms which cannot match UDP destination 123 are
excluded from the historical projection.  All raw evidence and within-run
whole-ruleset comparisons remain the caller's responsibility.

The nft text renderer omits some xtables extension arguments.  Its projection
therefore complements, and never substitutes for, iptables-save and ipset save.
This contract does not certify ESTABLISHED flows, ingress packet tests, IPv6
reachability, reboot persistence, arbitrary privileged packet marks, or HEP/GNP.
"""
import hashlib
import ipaddress
import json
import re
import shlex


CAPTURE_ARCHIVE_SHA256 = '7945a9bc4c18f0bc05d22dc329773b9820134e57cdaa764cfcd8cc21f218fcb6'
CAPTURED_AT = '2026-09-21T16:14:31+09:00'
HOSTS = ('k8s-control01', 'k8s-control02', 'k8s-control03',
         'k8s-worker01', 'k8s-worker02', 'k8s-worker03')
CHAIN = 'FDS_NTP_0101'
NAME = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
SERVICE = re.compile(r'KUBE-SVC-[A-Z0-9]{16}\Z')
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 40000
IPTABLES_TARGETS = {'ACCEPT', 'DROP', 'RETURN', 'REJECT', 'MARK', 'CONNMARK',
                   'NOTRACK', 'CT', 'DNAT', 'SNAT', 'MASQUERADE', 'NETMAP',
                   'REDIRECT', 'TPROXY', 'DSCP', 'TCPMSS', 'LOG', 'NFLOG',
                   'NFQUEUE', 'CHECKSUM', 'HL', 'TTL', 'AUDIT', 'SECMARK',
                   'CONNSECMARK', 'TRACE', 'RATEEST', 'SET', 'SYNPROXY'}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(_json(value).encode('ascii')).hexdigest()


def _lines(text):
    if not isinstance(text, str) or '\x00' in text or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Invalid or oversized kernel evidence')
    rows = text.splitlines()
    if len(rows) > MAX_ROWS:
        raise ValueError('Kernel evidence row limit exceeded')
    return rows


def _tokens(line):
    try:
        return tuple(shlex.split(line, comments=False, posix=True))
    except ValueError as exc:
        raise ValueError('Malformed kernel tokens') from exc


def _name(value):
    if not NAME.fullmatch(value):
        raise ValueError('Unsupported kernel object name')
    return value


def _jump(row, flags=('-j', '-g')):
    positions = [i for i, word in enumerate(row) if word in flags]
    if len(positions) > 1 or (positions and positions[0] + 1 >= len(row)):
        raise ValueError('Ambiguous chain transfer')
    return row[positions[0] + 1] if positions else None


def _service_iptables(row, family):
    """Return a provably disjoint dispatch or None; no generic match erasure."""
    if len(row) != 16 or row[:3] != ('-A', 'KUBE-SERVICES', '-d'):
        return None
    if (row[4] != '-p' or row[5] not in ('tcp', 'udp') or
            row[6:9] != ('-m', 'comment', '--comment') or
            row[10:13] != ('-m', row[5], '--dport') or row[14] != '-j' or
            not SERVICE.fullmatch(row[15])):
        return None
    try:
        address = ipaddress.ip_network(row[3], strict=True)
        port = int(row[13])
    except ValueError:
        return None
    if (address.version != family or address.prefixlen != address.max_prefixlen or
            str(port) != row[13] or not 1 <= port <= 65535 or
            (row[5] == 'udp' and port == 123)):
        return None
    return (str(address.network_address), row[5], port, row[15])


def _iptables(text, family):
    tables, current = {}, None
    for raw in _lines(text):
        if not raw or raw.startswith('#'):
            continue
        if raw.startswith('*'):
            name = _name(raw[1:])
            if current is not None or name in tables:
                raise ValueError('Duplicate or nested iptables table')
            current = tables[name] = {'declarations': {}, 'rules': {}}
        elif raw == 'COMMIT':
            if current is None:
                raise ValueError('Unexpected iptables COMMIT')
            current = None
        elif current is None:
            raise ValueError('Content outside an iptables table')
        elif raw.startswith(':'):
            row = _tokens(raw[1:])
            if (len(row) != 3 or row[1] not in ('-', 'ACCEPT', 'DROP') or
                    not re.fullmatch(r'\[[0-9]+:[0-9]+\]', row[2])):
                raise ValueError('Unsupported iptables declaration')
            name = _name(row[0])
            if name in current['declarations']:
                raise ValueError('Duplicate iptables chain')
            current['declarations'][name] = row[1]
            current['rules'][name] = []
        elif raw.startswith('-A '):
            row = _tokens(raw)
            if len(row) < 3 or row[1] not in current['rules']:
                raise ValueError('Rule refers to undeclared iptables chain')
            current['rules'][row[1]].append(row)
        else:
            raise ValueError('Unsupported iptables-save syntax')
    if current is not None or 'filter' not in tables:
        raise ValueError('Incomplete iptables-save evidence')
    references = []
    for table_name, table in tables.items():
        if CHAIN in table['declarations'] and table_name != 'filter':
            raise ValueError('NTP chain declared outside filter')
        for chain, rows in table['rules'].items():
            for row in rows:
                target = _jump(row)
                if target == CHAIN:
                    references.append((table_name, chain, row))
                if target and target not in table['declarations'] and target not in IPTABLES_TARGETS:
                    raise ValueError('Unresolved iptables transfer')
    if len(references) != 1 or references[0][:2] != ('filter', 'OUTPUT'):
        raise ValueError('NTP hook is missing, duplicated or foreign')
    projection, services, critical = {}, [], {}
    for table_name, table in tables.items():
        bases = {k: v for k, v in table['declarations'].items() if v != '-'}
        roots = ['OUTPUT'] if table_name == 'filter' else list(bases)
        selected, visiting = {}, set()

        def walk(chain):
            if chain in visiting:
                raise ValueError('Cycle in critical iptables path')
            if chain in selected:
                return
            if chain not in table['rules']:
                raise ValueError('Missing critical iptables chain')
            visiting.add(chain)
            retained = []
            for row in table['rules'][chain]:
                disjoint = _service_iptables(row, family) if table_name == 'nat' and chain == 'KUBE-SERVICES' else None
                if disjoint is not None:
                    if table['declarations'].get(disjoint[3]) != '-':
                        raise ValueError('Service dispatch must target a regular chain')
                    services.append(disjoint)
                    continue
                retained.append(row)
                target = _jump(row)
                if target in table['declarations']:
                    walk(target)
            visiting.remove(chain)
            selected[chain] = {'policy': table['declarations'][chain], 'rules': retained}

        for chain in roots:
            walk(chain)
        projection[table_name] = {'bases': bases, 'critical': selected}
        critical[table_name] = selected
    if len(set(services)) != len(services):
        raise ValueError('Duplicate Service dispatch')
    return projection, sorted(services), critical


def _nft_tokens(line):
    row = _tokens(line)
    result, index = [], 0
    while index < len(row):
        if row[index:index + 2] == ('counter', 'packets'):
            if (index + 4 >= len(row) or row[index + 3] != 'bytes' or
                    not row[index + 2].isdigit() or not row[index + 4].isdigit()):
                raise ValueError('Malformed nft counter')
            result.extend(('counter', 'packets', 'COUNTER', 'bytes', 'COUNTER'))
            index += 5
        else:
            result.append(row[index])
            index += 1
    return tuple(result)


def _service_nft(row, family):
    # nft renders the exact kube-proxy dispatch generated above in this form.
    core = tuple(x for i, x in enumerate(row) if not any(
        row[j:j + 5] == ('counter', 'packets', 'COUNTER', 'bytes', 'COUNTER')
        and j <= i < j + 5 for j in range(max(0, i - 4), i + 1)))
    if (len(core) != 11 or core[:2] != ('meta', 'l4proto') or core[2] not in ('tcp', 'udp') or
            core[3:5] != (('ip' if family == 4 else 'ip6'), 'daddr') or
            core[6:8] != (core[2], 'dport') or core[9] != 'jump' or
            not SERVICE.fullmatch(core[10])):
        return None
    try:
        address = ipaddress.ip_address(core[5])
        port = int(core[8])
    except ValueError:
        return None
    if (address.version != family or str(port) != core[8] or not 1 <= port <= 65535 or
            (core[2] == 'udp' and port == 123)):
        return None
    return (str(address), core[2], port, core[10])


def _verdict_map(rows, chains):
    """Accept only the observed bounded ifname -> chain verdict map grammar."""
    if not rows or rows[0] != 'type ifname : verdict':
        raise ValueError('Unsupported nft map type')
    elements = {}
    if len(rows) > 1:
        match = re.fullmatch(r'elements = \{ (.+) \}', ' '.join(rows[1:]))
        if not match:
            raise ValueError('Malformed nft verdict map elements')
        for item in match[1].split(','):
            entry = re.fullmatch(r'\s*"([A-Za-z0-9_.:-]{1,15})" : (jump|goto) ([A-Za-z0-9_.:-]{1,128})\s*', item)
            if not entry or entry[1] in elements:
                raise ValueError('Unsupported or duplicate nft map element')
            if entry[3] not in chains or entry[3] == CHAIN:
                raise ValueError('Unresolved or foreign nft map verdict target')
            elements[entry[1]] = (entry[2], entry[3])
    return {'type': 'ifname : verdict', 'elements': elements}


def _nft(text, ip_critical, ip_services):
    tables, table, chain, verdict_map = {}, None, None, None
    for raw in _lines(text):
        line = raw.strip()
        if not line:
            continue
        if table is None:
            match = re.fullmatch(r'table (ip|ip6|inet|arp|bridge|netdev) ([A-Za-z0-9_.:-]+) \{(?: # progname [A-Za-z0-9_.-]+)?', line)
            if not match:
                raise ValueError('Unsupported nft table syntax')
            key = (match[1], _name(match[2]))
            if key in tables:
                raise ValueError('Duplicate nft table')
            table = tables[key] = {'attributes': [], 'chains': {}, 'maps': {}}
        elif verdict_map is not None:
            if line == '}':
                verdict_map = None
            else:
                verdict_map.append(line)
        elif chain is None:
            match = re.fullmatch(r'chain ([A-Za-z0-9_.:-]+) \{', line)
            map_match = re.fullmatch(r'map ([A-Za-z0-9_.:-]+) \{', line)
            if match:
                name = _name(match[1])
                if name in table['chains']:
                    raise ValueError('Duplicate nft chain')
                chain = table['chains'][name] = []
            elif map_match:
                name = _name(map_match[1])
                if key != ('arp', 'calico-arp') or name in table['maps']:
                    raise ValueError('Duplicate or unsupported nft map')
                verdict_map = table['maps'][name] = []
            elif line == '}':
                table = None
            elif line == 'flags owner,persist':
                table['attributes'].append(line)
            else:
                raise ValueError('Unsupported nft table object')
        elif line == '}':
            chain = None
        else:
            # All captured set expressions are single-line rule expressions.
            # Nested declarations/objects are outside this bounded grammar.
            if line.startswith(('chain ', 'table ', 'set ', 'map ', 'flowtable ')):
                raise ValueError('Unsupported nested nft object')
            chain.append(_nft_tokens(line))
    if table is not None or chain is not None or verdict_map is not None or not tables:
        raise ValueError('Incomplete nft evidence')
    projection, services, ntp_refs = {}, {4: [], 6: []}, {4: [], 6: []}
    for (family, name), value in tables.items():
        value['maps'] = {map_name: _verdict_map(rows, value['chains'])
                         for map_name, rows in value['maps'].items()}
        bases = {}
        for chain_name, rows in value['chains'].items():
            for row in rows:
                if row and row[0] == 'type':
                    if chain_name in bases or 'hook' not in row:
                        raise ValueError('Ambiguous nft chain type')
                    bases[chain_name] = row
                target = _jump(row, ('jump', 'goto'))
                if target and target not in value['chains']:
                    raise ValueError('Unresolved nft chain transfer')
                if target == CHAIN:
                    if family not in ('ip', 'ip6'):
                        raise ValueError('Foreign nft NTP chain reference')
                    ntp_refs[4 if family == 'ip' else 6].append((name, chain_name))
                if 'vmap' in row:
                    if (len(row) not in (3, 5) or row[:2] != ('oifname', 'vmap') or
                            not row[2].startswith('@') or row[2][1:] not in value['maps'] or
                            (len(row) == 5 and row[3] != 'comment')):
                        raise ValueError('Unsupported or unresolved nft verdict map reference')
            if chain_name == CHAIN and (family not in ('ip', 'ip6') or name != 'filter'):
                raise ValueError('Nft NTP chain outside filter')
        key = family + ' ' + name
        if family in ('inet', 'arp'):
            projection[key] = value
            continue
        if family not in ('ip', 'ip6'):
            raise ValueError('Unreviewed nft family')
        number = 4 if family == 'ip' else 6
        if name not in ip_critical[number]:
            raise ValueError('Nft table absent from iptables evidence')
        selected = {}
        for chain_name in ip_critical[number][name]:
            if chain_name not in value['chains']:
                # iptables-nft save includes empty ACCEPT builtins which have
                # never been materialised as native nft chains. Pin that exact
                # absence; never excuse a regular chain, DROP policy, or rule.
                peer = ip_critical[number][name][chain_name]
                if peer != {'policy': 'ACCEPT', 'rules': []}:
                    raise ValueError('Nft critical chain absent: ' + family + ' ' + name + ' ' + chain_name)
                selected[chain_name] = {'unmaterialised_empty_accept_builtin': True}
                continue
            rows = []
            for row in value['chains'][chain_name]:
                disjoint = _service_nft(row, number) if name == 'nat' and chain_name == 'KUBE-SERVICES' else None
                if disjoint is not None:
                    if disjoint[3] not in value['chains'] or disjoint[3] in bases:
                        raise ValueError('Invalid nft Service dispatch target')
                    services[number].append(disjoint)
                else:
                    rows.append(row)
            selected[chain_name] = rows
        projection[key] = {'attributes': value['attributes'], 'bases': bases, 'critical': selected}
    for number in (4, 6):
        if ntp_refs[number] != [('filter', 'OUTPUT')]:
            raise ValueError('Nft NTP hook is missing, duplicated or foreign')
        if sorted(services[number]) != ip_services[number]:
            raise ValueError('Nft and iptables Service dispatches disagree')
    return projection


def normalize_ipset(text):
    """Canonicalise ordering/initval only; preserve every other option/member."""
    sets = {}
    for raw in _lines(text):
        if not raw:
            continue
        row = _tokens(raw)
        if len(row) < 3:
            raise ValueError('Malformed ipset evidence')
        name = _name(row[1])
        if row[0] == 'create':
            if name in sets or row[2] not in ('hash:ip', 'hash:net'):
                raise ValueError('Duplicate or unsupported ipset')
            options, index = [], 3
            seen = set()
            while index < len(row):
                key = row[index]
                if key in seen or index + 1 >= len(row):
                    raise ValueError('Malformed ipset create options')
                seen.add(key)
                if key not in ('family', 'hashsize', 'maxelem', 'bucketsize', 'initval', 'timeout'):
                    raise ValueError('Unsupported ipset create option')
                val = row[index + 1]
                if key == 'initval':
                    if not re.fullmatch(r'0x[0-9a-fA-F]+', val):
                        raise ValueError('Invalid ipset hash initialisation')
                else:
                    options.append((key, val))
                index += 2
            sets[name] = {'type': row[2], 'options': sorted(options), 'members': []}
        elif row[0] == 'add' and name in sets:
            try:
                member = ipaddress.ip_network(row[2], strict=True)
            except ValueError as exc:
                raise ValueError('Invalid ipset member') from exc
            options, index, seen = [], 3, set()
            while index < len(row):
                key = row[index]
                if key in seen:
                    raise ValueError('Duplicate ipset member option')
                seen.add(key)
                if key == 'nomatch':
                    options.append((key,))
                    index += 1
                elif key == 'timeout' and index + 1 < len(row) and row[index + 1].isdigit():
                    options.append((key, row[index + 1]))
                    index += 2
                else:
                    raise ValueError('Unsupported ipset member option')
            value = (str(member), tuple(sorted(options)))
            if value in sets[name]['members']:
                raise ValueError('Duplicate ipset member')
            sets[name]['members'].append(value)
        else:
            raise ValueError('Unsupported ipset save operation')
    for value in sets.values():
        value['members'].sort()
    return _json(sets)


# Fixed historical observation, never learned or accepted from live input.
# These candidate constants require review with the code; matching them is not
# current policy approval, operational verification, or final AC acceptance.
BASELINE = {'k8s-control01': {'ip6tables_contract': '2fa6930308ad96f037899c3b6987834d66ce54e249ed7b899ba8f5e4c40ef3ac',
                   'ipset_contract': 'e601a4295de3561dcca2b1679b452fadb67effb14dca62709e9e36d9c6ecbc61',
                   'iptables_contract': '56eaa23c9d2aeb6f157af413e23ba00138cfdb7db13d8ea8d258aa43783aeb91',
                   'nft_contract': '742ae70cfecb9ec798d38aa7e8a8a4d8d1889e79683c3c74b8f873c3ac203f8f'},
 'k8s-control02': {'ip6tables_contract': '2fa6930308ad96f037899c3b6987834d66ce54e249ed7b899ba8f5e4c40ef3ac',
                   'ipset_contract': '7eb76fefd2cd23f612b6c43b2428a8d586f4976ec4a900c8a7238fa5ce670160',
                   'iptables_contract': '30aec41df1b85dbb3c283d875659a72fe41da583d0b8a8f4769ddca891392cf3',
                   'nft_contract': 'd5725d9f8cc13884c10337147c870a0081f115dce452d9cb0a0084a74bf5bdc5'},
 'k8s-control03': {'ip6tables_contract': '2fa6930308ad96f037899c3b6987834d66ce54e249ed7b899ba8f5e4c40ef3ac',
                   'ipset_contract': 'b9a4f2881e2d8a92b59ecdca0ba9c2ea6dddd91f31583a59303a84e46b9dc926',
                   'iptables_contract': '30aec41df1b85dbb3c283d875659a72fe41da583d0b8a8f4769ddca891392cf3',
                   'nft_contract': 'e12997dabc7d0b965b9518637bf70efa9dc5bad62141da5b729b6b12a4097f70'},
 'k8s-worker01': {'ip6tables_contract': '2fa6930308ad96f037899c3b6987834d66ce54e249ed7b899ba8f5e4c40ef3ac',
                  'ipset_contract': '92116bbf67af09c758cd68914df71c6703efdc1086fd49426679cef4585583f4',
                  'iptables_contract': '30aec41df1b85dbb3c283d875659a72fe41da583d0b8a8f4769ddca891392cf3',
                  'nft_contract': 'cd67584fa3c69fe2ec8efe2d04d9a04bae78c2b9603c4fb7e1910248c2dc1665'},
 'k8s-worker02': {'ip6tables_contract': '2fa6930308ad96f037899c3b6987834d66ce54e249ed7b899ba8f5e4c40ef3ac',
                  'ipset_contract': 'fd8ab8b0ce44bd4742ececc458de712d94ef31fbab8c71b6ae9d5a7036dd1276',
                  'iptables_contract': '30aec41df1b85dbb3c283d875659a72fe41da583d0b8a8f4769ddca891392cf3',
                  'nft_contract': 'ac1d250478e2a440e8a6be06e009bd13ce3d9db96ca49a07e6e8359978cd592c'},
 'k8s-worker03': {'ip6tables_contract': '2fa6930308ad96f037899c3b6987834d66ce54e249ed7b899ba8f5e4c40ef3ac',
                  'ipset_contract': '92e6856501853dd827fde532938f84071ea53cd57284366d593ab84e7b3f8e25',
                  'iptables_contract': '30aec41df1b85dbb3c283d875659a72fe41da583d0b8a8f4769ddca891392cf3',
                  'nft_contract': '361617a0f6324b53a7f90a941d636170ba732d2a5a82ab8ab970a8ba452623b7'}}


def _contracts(iptables_text, ip6tables_text, nft_text, ipset_text):
    ipv4, services4, critical4 = _iptables(iptables_text, 4)
    ipv6, services6, critical6 = _iptables(ip6tables_text, 6)
    nft = _nft(nft_text, {4: critical4, 6: critical6}, {4: services4, 6: services6})
    return {'iptables_contract': _digest(ipv4), 'ip6tables_contract': _digest(ipv6),
            'nft_contract': _digest(nft),
            'ipset_contract': hashlib.sha256(normalize_ipset(ipset_text).encode('ascii')).hexdigest()}


def validate_kernel(host, iptables_text, ip6tables_text, nft_text, ipset_text):
    if host not in HOSTS or host not in BASELINE:
        raise ValueError('Host has no pinned kernel contract')
    expected_contract = BASELINE[host]
    if (set(expected_contract) != {'iptables_contract', 'ip6tables_contract', 'nft_contract', 'ipset_contract'} or
            any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
                for value in expected_contract.values())):
        raise ValueError('Pinned historical kernel contract is incomplete')
    actual = _contracts(iptables_text, ip6tables_text, nft_text, ipset_text)
    for name, expected in expected_contract.items():
        if actual[name] != expected:
            raise ValueError(name + ': critical NTP path differs from the pinned historical contract')
    return actual
