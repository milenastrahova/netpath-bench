# Linux socket-buffer experiment and packet-trace evidence

**Independent network engineering exercise** — C++/TCP/UDP portfolio extension for NetPath Bench.  
Python 3.10+ · Linux/WSL2/Docker · no third-party Python packages · no system configuration changes.

## Why this exists

A low-latency engineer must separate a hypothesis ("larger receive buffers reduce drops") from a measurement and from evidence of *causation*. This module adds a bounded repeatable trial using real UDP loopback sockets, a raw CSV integrity audit, and a classic-PCAP offline flow review. It supplements, rather than replaces, the existing C++ network benchmark and BGP experiments.

## Experimental design

* Variable: process-local `SO_RCVBUF` and `SO_SNDBUF` requests (64 KiB vs 512 KiB).
* Control: same UDP echo implementation, payload 64 bytes, socket location, timeout, process and experiment parameters.
* Trials: repeated AB/BA ordering to reduce trivial ordering bias, warmup packets excluded.
* Measures: count of sent requests, matched application replies, timeouts, RTT p50/p95/p99, and a descriptive median of absolute successive successful RTT differences.
* Evidence: every attempt is recorded to CSV; SHA-256 hashes and statistics are rechecked by a separate auditor. Effective buffer sizes read back with `getsockopt()`.
* Read-only environment metadata: `/proc/sys/net/core/{rmem_max,wmem_max,netdev_max_backlog}` where accessible.
* **No `sysctl -w`, `ethtool`, CPU affinity, NIC queue modification, Windows registry edit, or production routing changes.**

Serial loopback UDP echo traffic generally **does not fill receive queues**; changing socket buffers may have no benefit. Windows Docker and WSL2 introduce virtualized timing. No one-way latency or trading performance should be inferred. Per-run p99 values exclude timed-out requests; timeouts are counted separately. `rtt_median_abs_successive_delta_us` is not RFC 3550 jitter.

## Run in an existing Linux / WSL2 environment

From NetPath Bench repository root:

```bash
python3 -m unittest discover -s tests -p 'test_network_performance_extension.py' -v
python3 scripts/socket_buffer_study.py --output-dir reports/buffer-ab-1 --repetitions 4 --count 300 --interval-ms 1 --server-port 19371
python3 scripts/audit_socket_study.py reports/buffer-ab-1/summary.json
```

`reports/buffer-ab-1` must not already exist. Use a new directory for every study. No administrator privileges are needed for the experiment. The fixed loopback port is optional; omit `--server-port` to let the OS allocate one. If your Linux environment does not allow binding UDP sockets, the command will fail explicitly.

## Windows 11 + Docker Desktop, without changing Windows networking

From **PowerShell** in the repository root:

```powershell
docker run --rm -v "${PWD}:/work" -w /work python:3.12-alpine python scripts/socket_buffer_study.py --output-dir reports/buffer-ab-docker-1 --repetitions 3 --count 300
docker run --rm -v "${PWD}:/work" -w /work python:3.12-alpine python scripts/audit_socket_study.py reports/buffer-ab-docker-1/summary.json
```

The container needs access to the Python image (initial download may be required), but the scripts themselves use only the standard library. Docker's user-space loopback and network namespaces are isolated from Windows TCP/IP configuration. The bind-mounted `reports/` folder contains the new evidence and should remain ignored/unpublished until reviewed.

## Capture traffic for offline packet inspection (optional, Linux/WSL2)

In terminal A, **capture only your own local test** (root privileges are required by tcpdump on many Linux systems):

```bash
mkdir -p reports
sudo tcpdump -i lo -s 0 -U -w reports/local-udp.pcap 'udp port 19371'
```

In terminal B, run the experiment above with `--server-port 19371`. Stop tcpdump with `Ctrl+C` once the test finishes, then:

```bash
python3 scripts/packet_trace_review.py --pcap reports/local-udp.pcap --output reports/local-udp-analysis.json
```

For Windows PowerShell you can also copy a **classic Ethernet/IPv4 PCAP** from an authorized Wireshark/tcpdump session, and run the analyzer via Python without Linux. Do not commit PCAP files if they might contain IP addresses, tokens, customer traffic or private information.

### Packet analyst features

- Classic PCAP (microsecond/nanosecond timestamp, either byte order), Ethernet + up to two VLAN tags, IPv4 UDP/TCP.
- Per-direction flow grouping and inter-arrival p50/p95 **within capture timestamps**.
- `NPS1` echo and `MDL1` educational UDP sequence decoding: gaps, duplicates and out-of-order observations.
- TCP payload sequence repetitions are flagged as **candidates for further examination**, not definitive retransmissions.
- Explicitly skips fragmented/unsupported frames, rejects malformed PCAP, hashes the source capture.
- Never attempts to infer physical wire loss from sequence gaps; a capture can omit packets.

**Limitations:** Not PCAPNG, not IPv6, no TCP SACK interpretation, no hardware timestamps, no one-way delay or exact outage interval. A legitimate pcap may need conversion to classic pcap first, e.g. `editcap -F pcap input.pcapng output.pcap` in an authorized environment.

## How to interpret results responsibly

1. Inspect `summary.json` and confirm that `audit_socket_study.py` returns `PASS`.
2. Compare **per-run** p99 and timeout counts, not only pooled samples; account for AB/BA order and CPU load.
3. Inspect actual `getsockopt` values: the kernel may cap or double the requested buffer, so requested values do not imply achieved values.
4. If two profiles differ, repeat on the same machine, then on a different machine before suggesting any benefit. The lab's traffic model may be too gentle to evaluate buffer tuning.
5. Correlate PCAP *sequence observations* and application CSVs by stream, sequence and time where clocks permit. Inter-arrival time is not application RTT.
6. Do not list measured improvements in a CV unless they can be reproduced and are attributable to a real optimization under controlled load.

## Files

| File | Purpose |
| --- | --- |
| `scripts/socket_buffer_study.py` | Trial runner, process-local socket options and hashed CSV bundles |
| `scripts/audit_socket_study.py` | Independent CSV/manifest hash and percentile audit |
| `scripts/packet_trace_review.py` | Bounded offline classic-PCAP evidence parser |
| `tests/test_network_performance_extension.py` | Behavioral, malformed-input and audit-tampering tests |
| `.github/workflows/network-evidence-extension.yml` | Linux CI: tests + short real UDP experiment + evidence artifact |

**Evidence provenance:** Any example outputs from an assistant-run container are demonstration data, not evidence of operation on the author's Windows workstation or physical network. The repository's main BGP/UDP source-verified experiments remain independent evidence.
