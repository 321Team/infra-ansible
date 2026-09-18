#!/usr/bin/env python3
"""Render review data from the same vars file used by the NTP role.

No network lookup, firewall operation, or service operation is performed.
An address passing syntax checks is not an approved/publicly usable NTP server.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHANGE_ID = 'CR-P1-NTP-01-01'
SOURCE_HOST = 'k8s-control01'
SOURCE_IP = '10.1.93.102'
CLIENT_IPS = ('10.1.93.103', '10.1.93.104', '10.1.93.105',
              '10.1.93.107', '10.1.93.108')
MAX_INPUT_BYTES = 1024 * 1024
# Load the exact file Ansible bundles as ansible.module_utils.fds_ntp_policy;
# a missing or broken policy file must fail rather than select a fallback.
_policy_spec = importlib.util.spec_from_file_location(
    'fds_ntp_shared_policy', ROOT / 'module_utils/fds_ntp_policy.py')
POLICY = importlib.util.module_from_spec(_policy_spec)
_policy_spec.loader.exec_module(POLICY)


class ContractError(ValueError):
    """Input does not define the narrowly scoped review contract."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject ambiguous inventory values rather than accepting the last one."""


def unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ContractError('duplicate YAML key: %s' % key)
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as exc:
            raise ContractError('YAML mapping keys must be scalar values') from exc
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                               unique_mapping)


def public_upstreams(value):
    try:
        return POLICY.validate_public_upstreams(value)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc


def load_vars(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ContractError('vars file exceeds the 1 MiB review-input limit')
    variables = yaml.load(raw.decode('utf-8'), Loader=UniqueKeyLoader)
    if not isinstance(variables, dict):
        raise ContractError('vars file must be one YAML mapping')
    return variables, hashlib.sha256(raw).hexdigest()


def build_contract(variables, input_sha256):
    if variables.get('cr_ntp_change_id') != CHANGE_ID:
        raise ContractError('unexpected NTP change ID')
    if (variables.get('cr_ntp_source_host') != SOURCE_HOST
            or variables.get('cr_ntp_source_ip') != SOURCE_IP):
        raise ContractError('this contract permits only k8s-control01 / 10.1.93.102')
    clients = variables.get('cr_ntp_client_ips')
    if (not isinstance(clients, list) or len(clients) != len(CLIENT_IPS)
            or not all(isinstance(value, str) for value in clients)
            or set(clients) != set(CLIENT_IPS)):
        raise ContractError('client list must match the five reviewed cluster nodes')
    upstreams = public_upstreams(variables.get('cr_ntp_source_upstreams'))
    return {
        'schema_version': 1,
        'change_id': CHANGE_ID,
        'status': 'CANDIDATE_NOT_APPLIED',
        'addresses_owner_policy_status': 'PENDING',
        'enforcement_status': 'NOT_PERFORMED',
        'input': {'vars_sha256': input_sha256,
                  'upstreams_variable': 'cr_ntp_source_upstreams',
                  'effective_ansible_vars_verified': False},
        'public_ntp_egress': {
            'source_host': SOURCE_HOST,
            'source_before_snat': SOURCE_IP + '/32',
            'destination_cidrs': [address + '/32' for address in upstreams],
            'address_count': len(upstreams),
            'operator_count': len({POLICY.UPSTREAM_CATALOG[address]['operator']
                                   for address in upstreams}),
            'operators': {address: POLICY.UPSTREAM_CATALOG[address]['operator']
                          for address in upstreams},
            'catalog_membership_is_service_approval': False,
            'ip_family': 'IPv4',
            'protocol': 'udp',
            'destination_port': 123,
            'source_port': {'selection': 'OS_SELECTED_EPHEMERAL',
                            'fixed_port': None,
                            'observed_port_range': 'PENDING'},
            'return_traffic': 'STATEFUL_REPLIES_ONLY',
            'unsolicited_inbound_permitted': False,
        },
        'five_client_policy': {
            'source_cidrs': [address + '/32' for address in CLIENT_IPS],
            'ntp_destination': SOURCE_IP + '/32',
            'ntp_destination_port': 123,
            'direct_public_ntp_permitted_by_design': False,
            'effective_enforcement_verified': False,
        },
        'implementation_review': {
            'firewall_backend': 'UNCONFIRMED',
            'required_rule_count': 'UNDETERMINED',
            'source_after_snat': 'UNCONFIRMED',
            'effective_host_network_calico_policy': 'UNCONFIRMED',
            'public_server_ownership_use_policy_and_time_policy': 'PENDING',
            'ntp_response_reachability': 'NOT_TESTED',
            'applies_firewall_configuration': False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vars-file', type=Path,
                        default=ROOT / 'inventory/group_vars/all.yml')
    parser.add_argument('--format', choices=('json', 'yaml'), default='json')
    parser.add_argument('--output', type=Path,
                        help='new local review file; an existing path is never overwritten')
    args = parser.parse_args(argv)
    try:
        variables, digest = load_vars(args.vars_file)
        result = build_contract(variables, digest)
        rendered = (json.dumps(result, indent=2) + '\n' if args.format == 'json'
                    else yaml.safe_dump(result, sort_keys=False))
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(rendered)
        else:
            sys.stdout.write(rendered)
    except (ContractError, OSError, UnicodeError, yaml.YAMLError) as exc:
        print('STOP: %s; no firewall action performed' % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
