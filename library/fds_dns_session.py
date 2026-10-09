#!/usr/bin/python
"""Immutable worker02 DNS session snapshot; no networking or service operations.

The hash must be retained outside this module between prepare and later actions.
This is not a lock against another root/operator changing NetworkManager.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROOT = '/var/lib/fds-change/CR-P1-ANS-01-01/worker02-sessions'
FIELDS = ('interface', 'connection', 'ipv4_dns', 'ipv4_dns_search', 'ipv4_ignore_auto_dns')


def validate_inputs(action, session, source, current, desired, expected):
    if action not in ('prepare', 'apply', 'reapply', 'rollback'):
        raise ValueError('Invalid session action')
    if not isinstance(session, str) or not re.fullmatch(r'w02-[0-9]{8}T[0-9]{6}-[a-f0-9]{8}', session):
        raise ValueError('Invalid session ID')
    if not re.fullmatch(r'[a-f0-9]{40}', source):
        raise ValueError('Require the reviewed full source SHA')
    if action != 'prepare' and not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('Require the independently retained backup SHA256')
    for key in FIELDS:
        if not isinstance(current.get(key), str) or '\x00' in current[key]:
            raise ValueError('Invalid current resolver field: ' + key)
    if not current['interface'] or not current['connection'] or current['connection'] == '--':
        raise ValueError('Missing active interface/connection')
    if set(desired) != {'dns', 'search', 'ignore_auto'} or desired['ignore_auto'] is not True:
        raise ValueError('Invalid desired resolver fields')
    for key in ('dns', 'search'):
        values = desired[key]
        if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x for x in values):
            raise ValueError('Invalid desired resolver list')
    if len(desired['dns']) != 2 or len(set(desired['dns'])) != 2:
        raise ValueError('Require two distinct DNS servers')


def normalized(values):
    flag = values['ipv4_ignore_auto_dns'].lower()
    if flag not in ('yes', 'true', '1', 'no', 'false', '0'):
        raise ValueError('Unrecognized ignore-auto-dns value')
    return {'dns': values['ipv4_dns'].replace(',', ' ').split(),
            'search': values['ipv4_dns_search'].replace(',', ' ').split(),
            'ignore_auto': flag in ('yes', 'true', '1')}


def directory(path, uid, create=False, private=False):
    """No symlinks or writable ancestors; never repair existing permissions."""
    path = Path(path)
    for part in reversed([path] + list(path.parents)):
        if not part.exists() and not part.is_symlink() and create:
            try:
                part.mkdir(mode=0o700)
            except FileExistsError:
                pass
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, uid):
            raise ValueError('Unsafe directory type/owner')
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o022 and not (part != path and mode & stat.S_ISVTX):
            raise ValueError('Unsafe writable directory')
        if set(os.listxattr(part, follow_symlinks=False)) - {'security.selinux'}:
            raise ValueError('Unexpected directory ACL or xattr')
        if part == path and private and (info.st_uid != uid or info.st_gid != os.getegid() or mode != 0o700):
            raise ValueError('Session directory must have expected owner/group and mode 0700')


def run(action, session, source, current, desired, expected='', check=False,
        root=ROOT, uid=0, now=None):
    validate_inputs(action, session, source, current, desired, expected)
    normalized(current)
    now = datetime.datetime.now(datetime.timezone.utc) if now is None else now
    binding = {'schema': 'fds.worker02.dns-session.v1', 'session_id': session,
               'change_id': 'CR-P1-ANS-01-01', 'inventory_hostname': 'k8s-worker02',
               'endpoint': '10.1.93.107', 'account': 'svc_ansible', 'source_sha': source,
               'desired': desired}
    parent = Path(root) / session
    path = parent / 'original-resolver.json'
    if action == 'prepare':
        if os.path.lexists(parent):
            raise ValueError('Session already exists; do not overwrite or recapture')
        data = {**binding, 'captured_at': now.isoformat(), 'original': current}
        payload = (json.dumps(data, sort_keys=True, indent=2) + '\n').encode()
        if len(payload) > 65536:
            raise ValueError('Snapshot exceeds the bounded reader size')
        if not check:
            directory(root, uid, create=True, private=True)
            # Exclusive directory creation serializes same-ID capture. An interrupted
            # prepare deliberately leaves an unusable ID, never a replacement snapshot.
            parent.mkdir(mode=0o700)
            directory(parent, uid, private=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            dfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        return {'changed': not check, 'snapshot_written': not check, 'path': str(path),
                'sha256': hashlib.sha256(payload).hexdigest() if not check else None,
                'original': current}
    directory(root, uid, private=True)
    directory(parent, uid, private=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != uid
                or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Unsafe snapshot type/link/ownership/mode')
        if set(os.listxattr(stream.fileno())) - {'security.selinux'}:
            raise ValueError('Unexpected snapshot ACL or xattr')
        payload = stream.read(65537)
    if len(payload) > 65536 or hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError('Snapshot size or pinned SHA256 mismatch')
    data = json.loads(payload)
    if any(data.get(key) != value for key, value in binding.items()):
        raise ValueError('Snapshot session/source/target/desired binding mismatch')
    original = data['original']
    validate_inputs(action, session, source, original, desired, expected)
    if any(current[key] != original[key] for key in ('interface', 'connection')):
        raise ValueError('Active interface or connection drift')
    observed = normalized(current)
    before = normalized(original)
    if action == 'apply':
        age = (now - datetime.datetime.fromisoformat(data['captured_at'])).total_seconds()
        if not 0 <= age <= 900 or current != original:
            raise ValueError('First apply requires an unchanged snapshot no older than 15 minutes')
    elif action == 'reapply' and observed != desired:
        raise ValueError('Reapply requires the previously applied desired state')
    elif action == 'rollback' and observed not in (before, desired):
        raise ValueError('Rollback stopped: state is neither session original nor desired')
    return {'changed': False, 'snapshot_written': False, 'path': str(path),
            'sha256': expected, 'original': original, 'restore_needed': current != original}


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        'action': {'type': 'str', 'required': True},
        'session_id': {'type': 'str', 'required': True},
        'source_sha': {'type': 'str', 'required': True},
        'current': {'type': 'dict', 'required': True},
        'desired': {'type': 'dict', 'required': True},
        'expected_sha256': {'type': 'str', 'default': ''}}, supports_check_mode=True)
    try:
        if os.geteuid() != 0 or os.getegid() != 0:
            raise ValueError('Require root for the protected session snapshot')
        p = module.params
        module.exit_json(**run(p['action'], p['session_id'], p['source_sha'], p['current'],
                               p['desired'], p['expected_sha256'], module.check_mode))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        module.fail_json(msg='NOT RUN: DNS session binding: ' + str(exc))


if __name__ == '__main__':
    main()
