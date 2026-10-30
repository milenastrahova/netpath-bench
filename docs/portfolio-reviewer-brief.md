# Network Engineering — Portfolio Reviewer Brief

**Milena Strahova** · Riga, Latvia · [GitHub profile](https://github.com/milenastrahova)

## Executive summary

A connected set of reproducible network-engineering projects demonstrates **BGP policy and failover, Python network operations, C++ TCP/UDP measurement, experiment design and source-evidence auditing**. The objective is to make network behavior observable, failure handling repeatable and performance claims verifiable.

**This is a controlled Docker/FRRouting laboratory, not production trading infrastructure.** Project evidence and code can be independently reviewed.

## Three connected projects

| Project | Implementation | Reviewer entry point |
| --- | --- | --- |
| [BGP Routing Laboratory](https://github.com/milenastrahova/bgp-routing-laboratory) | Four eBGP autonomous systems, primary/backup transit, Local Preference route policy, prefix filtering, controlled failover and recovery, static + Docker integration CI | [Routing lab README](https://github.com/milenastrahova/bgp-routing-laboratory#readme) |
| [Network Operations Toolkit](https://github.com/milenastrahova/network-operations-toolkit) | Python FRR audit and monitor, JSON snapshots and diff, incident triage/reconstruction, TCP probe and PCAP/UDP analysis, CI | [Operations toolkit README](https://github.com/milenastrahova/network-operations-toolkit#readme) |
| [NetPath Bench](https://github.com/milenastrahova/netpath-bench) | C++17 TCP/UDP echo applications, microsecond-resolution user-space RTT sampling, percentiles, timeouts, evidence checks and bounded BGP-routed experiments | [NetPath Bench README](https://github.com/milenastrahova/netpath-bench#readme) |

## Source-verified routed UDP experiment

An independently audited nine-run study through the isolated four-AS routing lab contains **10,580 UDP application echo attempts**:

- **7,067 / 7,067** matched responses in control runs.
- **3,510 / 3,513** matched responses across three deliberately disrupted primary-transit runs.
- Three unmatched application replies were recorded as **timeouts**, at sequences 294, 295 and 297.
- Raw CSV/JSON counts, SHA-256 fingerprints, health checks and experiment timing were reconciled in the source audit.

See [nine-run source audit](bgp-nine-run-source-audit-2026-10-30.md) and [NetPath measurement methodology](benchmark-methodology.md).

**Interpretation:** These are application-level requests/replies and user-space RTT inside Docker; they are not physical wire loss, one-way NIC latency, PTP measurements, or precisely measured BGP convergence. A success-only p99 number can look better during failure because timed-out requests are excluded.

## Independently audited Linux UDP socket-buffer study

A separate, operator-run Docker/WSL2 experiment tested two process-local socket-buffer profiles across **six trials / 1,800 UDP echo requests**. All **1,800 replies matched**, with **zero application timeouts**. Original CSV rows, per-run p50/p95/p99 and SHA-256 hashes were independently reconciled to the source metadata. The larger-buffer profile produced a lower pooled p50 but **no consistent improvement in per-run p99**. This demonstrates evidence integrity and careful tail-latency interpretation, not physical NIC tuning.

[Read full six-run source audit](socket-buffer-source-audit-2026-10-30.md) · [Machine-readable report](../evidence/socket-buffer-source-audit-2026-10-30.json)

## Engineering decisions worth reviewing

**Route selection ≠ lowest latency.** Local Preference determines administrative routing policy; verifying traffic requires checking the forwarding table and application behavior separately.

**Fault testing must be bounded.** Controlled outages are only permitted in the isolated laboratory, with health checks and recovery attempts.

**Incident reports must account for missing evidence.** Monitoring tools distinguish a healthy result from missing observations and avoid false timeline correlation.

**Performance claims require auditable data.** Per-attempt samples and run-level reports matter more than a single favorable percentile.

## Where to inspect actual code

- C++17 sockets and timing: [`src/netpath_bench.cpp`](../src/netpath_bench.cpp)
- BGP-routed test runner: [`scripts/bgp_routed_trial.py`](../scripts/bgp_routed_trial.py)
- Nine-run source integrity report: [`docs/bgp-nine-run-source-audit-2026-10-30.md`](bgp-nine-run-source-audit-2026-10-30.md)
- Network operations state logic: [`network-operations-toolkit/netops/`](https://github.com/milenastrahova/network-operations-toolkit/tree/main/netops)
- BGP configurations: [`bgp-routing-laboratory/configs/`](https://github.com/milenastrahova/bgp-routing-laboratory/tree/main/configs)

## Reproducibility and boundaries

The experiments run on Windows 11/Docker Desktop/WSL2 or Linux. The repos include their own runbooks, tests and CI. None claims ownership of exchange infrastructure, colocation circuits, FPGA, kernel bypass or hardware timestamp data. This page is a **technical index of existing work**, not a claim of verified commercial HFT deployment.
