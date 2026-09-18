#!/usr/bin/env python3
"""Compare real chrony 4.8 client rates against a loopback-only NTP fixture.

The response fixture is adapted from ntp-rollout/work/tests/ntp_source/test_probe.py.
No managed host, public NTP endpoint, system service or clock is changed.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import threading
import time

HERE = Path(__file__).resolve().parent
BINARY = Path('/workspace/scratch/de9613d2608d/ntp-migration/chrony-validation/chrony-4.8/chronyd')
FIXTURE = Path('/workspace/scratch/de9613d2608d/ntp-rollout/work/tests/ntp_source/test_probe.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value):
    whole = int(value)
    return struct.pack('!II', (whole + 2208988800) & 0xffffffff,
                       int((value - whole) * 2**32))


def compare(name, options, offset=0.0):
    packets = []
    errors = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(('127.0.0.1', 0))
        server.settimeout(0.1)
        destination_port = server.getsockname()[1]
        stop = threading.Event()
        begin = time.monotonic()

        def serve():
            try:
                while not stop.is_set():
                    try:
                        request, peer = server.recvfrom(4096)
                    except socket.timeout:
                        continue
                    received_mono = time.monotonic()
                    assert peer[0] == '127.0.0.1', peer
                    assert len(request) >= 48, len(request)
                    packets.append(dict(elapsed_seconds=received_mono - begin,
                                        source_address=peer[0], source_port=peer[1],
                                        request_bytes=len(request)))
                    received = time.time() + offset
                    response = bytearray(48)
                    response[:4] = bytes((36, 2, 6, 236))
                    response[4:12] = struct.pack('!II', 65, 65)
                    response[12:16] = bytes((127, 0, 0, 2))
                    response[16:24] = timestamp(received - 1)
                    response[24:32] = request[40:48]
                    response[32:40] = timestamp(received)
                    response[40:48] = timestamp(time.time() + offset)
                    server.sendto(response, peer)
            except Exception as exc:
                errors.append(repr(exc))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        argv = [str(BINARY), '-4', '-Q', '-t', '35',
                'server 127.0.0.1 ' + options + ' port ' + str(destination_port),
                'pidfile /', 'port 0', 'cmdport 0', 'bindcmdaddress /']
        env = dict(os.environ, LC_ALL='C')
        for key in ('LISTEN_FDS', 'LISTEN_PID', 'LISTEN_FDNAMES', 'NOTIFY_SOCKET'):
            env.pop(key, None)
        outer_timeout = False
        try:
            child = subprocess.run(argv, capture_output=True, text=True, env=env,
                                   timeout=40, check=False)
            stdout, stderr, rc = child.stdout, child.stderr, child.returncode
        except subprocess.TimeoutExpired as exc:
            outer_timeout = True
            def text(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
            stdout, stderr, rc = text(exc.stdout), text(exc.stderr), 124
        finally:
            elapsed = time.monotonic() - begin
            stop.set()
            thread.join(timeout=1)
        samples = re.findall(r'System clock wrong by ([+-]?[0-9]+(?:\.[0-9]+)?) seconds \(ignored\)', stdout + stderr)
        measured = float(samples[0]) if len(samples) == 1 else None
        accepted = rc == 0 and measured is not None and math.isfinite(measured)
        intervals = [second['elapsed_seconds'] - first['elapsed_seconds']
                     for first, second in zip(packets, packets[1:])]
        expected_rate = (bool(intervals) and max(intervals) < 4.0) if name == 'existing_iburst' else (bool(intervals) and min(intervals) >= 4.0)
        passed = (not errors and accepted and abs(measured - offset) < 0.01 and
                  expected_rate and 'Disabled control of system clock' in stderr and
                  not outer_timeout and all(packet['source_port'] != 123 for packet in packets))
        return dict(name=name, passed=passed, argv=argv, returncode=rc,
                    stdout=stdout, stderr=stderr, elapsed_seconds=elapsed,
                    outer_timeout=outer_timeout, fixture_offset_seconds=offset,
                    offset_seconds=measured, sample_accepted=accepted,
                    offset_gate_100ms_pass=accepted and abs(measured) <= 0.1,
                    destination_address='127.0.0.1', destination_port=destination_port,
                    packet_count=len(packets), packets=packets,
                    request_intervals_seconds=intervals,
                    intervals_at_least_4_seconds=bool(intervals) and min(intervals) >= 4.0,
                    fixture_errors=errors)


def main():
    specs = [('existing_iburst', 'iburst', 0.0),
             ('proposed_poll8s', 'minpoll 3 maxpoll 3', 0.0),
             ('proposed_poll8s_250ms', 'minpoll 3 maxpoll 3', 0.25)]
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda spec: compare(*spec), specs))
    report = dict(recorded_at=datetime.now(timezone.utc).isoformat(),
                  scope='Actual chrony 4.8 against synthetic NTP on 127.0.0.1 only',
                  binary_path=str(BINARY), binary_sha256=sha(BINARY),
                  adapted_fixture_path=str(FIXTURE), adapted_fixture_sha256=sha(FIXTURE),
                  script_sha256=sha(Path(__file__)), results=results,
                  passed=sum(result['passed'] for result in results), total=len(results),
                  limitations=['No public NTP endpoint or production host contacted.',
                               'Only per-process packet intervals are measured.',
                               'Does not cover daemon/probe overlap, restart boundaries, repeated invocations or NAT-shared clients.',
                               'No repository code was modified; production policy support is not complete.',
                               'The synthetic server is unauthenticated and does not prove public-service reachability or leap policy.'])
    (HERE / 'RESULTS.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    lines = ['# Chrony 4.8 loopback request-rate comparison', '',
             'Actual binary, synthetic IPv4 loopback NTP only. No public endpoint was contacted.', '',
             '| Case | Packets | Intervals (s) | Offset (s) | RC | 100 ms gate |',
             '|---|---:|---|---:|---:|---|']
    for item in results:
        lines.append('| %s | %d | %s | %s | %d | %s |' % (
            item['name'], item['packet_count'], ', '.join('%.6f' % x for x in item['request_intervals_seconds']),
            item['offset_seconds'], item['returncode'], item['offset_gate_100ms_pass']))
    lines.extend(['', 'Result: %d/%d experiment expectations passed.' % (report['passed'], report['total']), '',
                  'The iburst case is expected to violate the NIST 4-second limit; its PASS means that the incompatibility was reproduced.', '',
                  'Removing iburst and selecting minpoll 3/maxpoll 3 avoids that conflict within these individual diagnostic processes. The 250 ms case remains rejected by the application offset threshold although chronyd successfully receives samples.', '',
                  '## Limits', '', *('- ' + value for value in report['limitations']), '',
                  'A production change still needs matching configuration generation, exact effective-config validation, diagnostics, and tests. Enforce aggregate spacing across daemon queries, restarts, repeated probes, and any shared egress address before claiming provider-policy compliance.', '',
                  'Binary SHA256: ' + report['binary_sha256'],
                  'Script SHA256: ' + report['script_sha256'], ''])
    (HERE / 'RESULTS.md').write_text('\n'.join(lines))
    print(json.dumps({key: report[key] for key in ('passed', 'total', 'binary_sha256')}))
    for result in results:
        print(json.dumps({key: result[key] for key in ('name', 'passed', 'returncode', 'packet_count', 'request_intervals_seconds', 'offset_seconds', 'offset_gate_100ms_pass')}))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
