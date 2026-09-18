# Chrony 4.8 loopback request-rate comparison

Actual binary, synthetic IPv4 loopback NTP only. No public endpoint was contacted.

| Case | Packets | Intervals (s) | Offset (s) | RC | 100 ms gate |
|---|---:|---|---:|---:|---|
| existing_iburst | 3 | 2.007274, 2.037364 | 3.3e-05 | 0 | True |
| proposed_poll8s | 3 | 8.133328, 8.013326 | 3.5e-05 | 0 | True |
| proposed_poll8s_250ms | 3 | 8.069227, 8.110653 | 0.250065 | 0 | False |

Result: 3/3 experiment expectations passed.

The iburst case is expected to violate the NIST 4-second limit; its PASS means that the incompatibility was reproduced.

Removing iburst and selecting minpoll 3/maxpoll 3 avoids that conflict within these individual diagnostic processes. The 250 ms case remains rejected by the application offset threshold although chronyd successfully receives samples.

## Limits

- No public NTP endpoint or production host contacted.
- Only per-process packet intervals are measured.
- Does not cover daemon/probe overlap, restart boundaries, repeated invocations or NAT-shared clients.
- No repository code was modified; production policy support is not complete.
- The synthetic server is unauthenticated and does not prove public-service reachability or leap policy.

A production change still needs matching configuration generation, exact effective-config validation, diagnostics, and tests. Enforce aggregate spacing across daemon queries, restarts, repeated probes, and any shared egress address before claiming provider-policy compliance.

Binary SHA256: 4bbea9015df39385b6f025fed43ed5a630906de8846d92114fce2833b0fdb914
Script SHA256: d3a3ac2a8b9ca8fe9b5571250526819203eaaef89e305f272614787156232875
