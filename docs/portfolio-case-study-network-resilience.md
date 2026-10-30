# Case study: Routing resilience, measurement and incident evidence

**Milena Strahova — independent engineering portfolio**  
Network reliability · BGP policy · Python automation · C++/UDP evidence

## Engineering problem

A network path can appear healthy while application traffic times out. Similarly, a BGP best path may be selected without proving that packets are delivered reliably. The task is to design a reproducible isolated network, deliberately cause a bounded failure, gather measurements and explain what observations do **not** establish.

## System architecture

```text
                PRIMARY TRANSIT (AS65020)
               /                      \
EDGE (AS65010)                         CORE (AS65040)
               \                      /
                 BACKUP TRANSIT (AS65030)
       |                                      |
  UDP probe client                    UDP echo server
       \_____________  ________________/
                    \/
             NetPath Bench (C++17)
                    |
             CSV / JSON metrics
                    |
    Network Operations Toolkit (Python)
      FRR BGP snapshots / incident review
                    |
        independent source/evidence audit
```

The routing fabric is a Docker/FRRouting emulation; it is **not** a commercial exchange interconnect. Local Preference selects the primary path; a deliberate primary failure exercises backup preference and recovery checks. FRR control-plane state is examined separately from Linux forwarding and application results.

## Observed results already recorded in the projects

The NetPath Bench repository documents a **source-verified nine-run** UDP study across four simulated ASes: **10,580 application requests**; controls **7,067 / 7,067** matching replies, and three deliberate primary-transit disruption trials **3,510 / 3,513** matching replies. The three nonmatching replies were recorded as timeouts at sequences 294, 295 and 297 in the controlled experiments. The source-verified report is [`docs/bgp-nine-run-source-audit-2026-10-30.md`](bgp-nine-run-source-audit-2026-10-30.md).

Do not interpret these application timeouts as proof of physical wire packet loss or a measured BGP convergence interval. No sub-microsecond end-to-end speed or hardware timestamping is claimed.

## Additional Linux and packet evidence

The new [socket-buffer and packet-trace study](socket-buffer-and-packet-trace-study.md) adds a **repeatable measurement method** and an independent CSV integrity audit. It measures process-local buffer variants in bounded Linux loopback trials, and can summarize an independently captured classic PCAP (TCP/UDP, timestamps, flow direction, sequence observations). It does not promise improved latency.

The **original six-run operator data** for the socket-buffer study has now been independently audited: **1,800 / 1,800** UDP loopback echoes matched within the 200 ms application timeout; **zero timeouts**. Per-run source CSV hashes and percentiles were recalculated. The larger-buffer profile gave a lower pooled p50 but mixed per-run p99 results, so no tail-latency optimization is claimed. See the [source-verified field report](socket-buffer-source-audit-2026-10-30.md) and [machine-readable audit](../evidence/socket-buffer-source-audit-2026-10-30.json).

### Independently audited packet capture

The user-run Docker loopback PCAP capture is now source-verified: **480/480 measured application replies**, **520/520 captured request/reply pairs** including warmup, and source manifest integrity on **8/8** files. Each original UDP frame was reconciled by NPS1 session, client/server port, sequence number and direction; no capture gaps or duplicate NPS1 frames were found. Application RTT and capture-timestamp deltas were reported separately.

Review the [detailed PCAP source audit](pcap-loopback-source-verification-2026-10-30.md) and [structured evidence](../evidence/pcap-loopback-source-audit-2026-10-30.json).

## What is demonstrably implemented

1. Routing policy reasoning and failover in an isolated four-AS topology.
2. C++ network applications that emit per-attempt statistics and documented RTT percentiles.
3. Python tooling for BGP monitoring, evidence checks and incident reconstruction.
4. Validation that separates observations, hypotheses and unavailable measurements.
5. CI and test suites that catch malformed inputs and misleading summaries.

## Engineering decisions / trade-offs

- **BGP policy vs measured latency:** Local Preference is an administrative routing preference, not a speed measurement. Routing selection and observed application performance must be investigated separately.
- **Recoverability vs fault injection:** Only isolated, explicitly opted-in container tests are used; restoration is attempted in cleanup paths.
- **Tail latency vs completeness:** Success-only p99 can look lower during failures because timed-out requests are excluded. Both must be reported.
- **Synthetic market-data-like sequencing vs actual feed reliability:** Sequence gaps in a PCAP may be generated upstream, missed in capture, or dropped; they cannot uniquely identify the failure point.
- **Kernel/NIC optimization:** Process-local socket-buffer experiments are an introduction to measurement methodology. Claims about physical NIC/IRQ tuning require hardware access and a properly controlled testbed.

## How a reviewer can verify

- Routing: [BGP Routing Laboratory](https://github.com/milenastrahova/bgp-routing-laboratory) → `configs/`, `docs/validation.md`, `docs/field-report-2026-10-27.md`.
- Network tools: [Network Operations Toolkit](https://github.com/milenastrahova/network-operations-toolkit) → `netops/`, `docs/release-acceptance.md`.
- C++ measurement: [NetPath Bench](https://github.com/milenastrahova/netpath-bench) → `src/`, `docs/bgp-nine-run-source-audit-2026-10-30.md`, `scripts/`.
- New lab: run `python3 -m unittest discover -s tests -p 'test_network_performance_extension.py' -v` and the bounded socket study with its separate hash audit.

**Scope:** Professional-style engineering exercise with verifiable outputs; not a claim of operation of production HFT networks, leased lines or exchange colocation hardware.
