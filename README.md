# NetPath Bench

**C++17 TCP/UDP measurement and network-resilience experiments with reproducible evidence.**  
C++17 · CMake · Python · Docker · FRRouting

This project investigates **application-level echo latency, tail behavior, and missing replies** across healthy and deliberately disrupted routes. Its analysis distinguishes measured observations from assumptions about packet loss or BGP convergence.

## What works

| Component | Implementation |
| --- | --- |
| TCP/UDP echo client and server | Native C++17 sockets (Windows Winsock2 and Linux POSIX), versioned framing and sequence/session checks |
| Timing and summaries | Monotonic-clock RTT, p50/p95/p99/p99.9, per-attempt CSV and JSON |
| Controlled path experiment | Client and server joined to different FRRouting network namespaces; explicit primary-transit fault and restoration attempt |
| Evidence audit | Rechecks original CSV/JSON bundles, per-probe counts and hashes; rejects inconsistent results |
| Linux counter diagnostics | Read-only `/proc/net/dev`, `softnet_stat`, and TCP retransmission snapshot comparisons |
| Synthetic UDP feed continuity | A small original educational feed framing, sequence gaps, late recovery, duplicates and optional multicast subscription |
| Cross-platform tests | [Successful Windows/Linux C++/Python and Alpine Docker CI](https://github.com/milenastrahova/netpath-bench/actions/runs/40932791021) |

## Verified results from the actual FRRouting lab

Four original data-checked UDP experiment runs on **28 October 2026**, 64-byte payload, 24 seconds each, 20 ms interval, 200 ms timeout:

| Observation | Healthy control (2 runs) | Primary transit fault (2 runs) |
| --- | ---: | ---: |
| Application echo requests | 2,353 | 2,334 |
| Matching echo replies | **2,353** | **2,332** |
| Echoes without matching replies before deadline | **0** | **2** |
| Median of per-run successful-RTT p99 | 0.801 ms | 0.680 ms |

**Interpretation matters:** the fault experiments had two application timeouts, but that does **not prove physical packet loss or precise outage duration**. The numerically lower p99 among successful fault-run replies does **not** establish better performance; timed-out replies are excluded, host load differs, and there are only two independent runs per condition.

[Verified conditions and limitations](docs/verified-conditions-2026-10-28.md) · [Measurement methodology](docs/benchmark-methodology.md) · [Independent evidence audit](scripts/audit_conditions.py)

## Operator validation — Windows Docker (29 October 2026)

An independent workstation run confirmed Docker build, C++ `SELFTEST PASS`, **500/500 UDP echoes** and **500/500 TCP echoes**, with zero application timeouts in each short trial. Measured p99 RTT was **0.320 ms (UDP)** and **0.306 ms (TCP)** inside the isolated NetPath Bench Docker network. **The original 1,000 CSV samples have now been independently audited** against the two JSON reports; the raw ZIP is retained privately. The original archive and member SHA-256 hashes are in the [verification report](docs/windows-docker-benchmark-2026-10-29.md). To reproduce with the same original ZIP: `python scripts/verify_standalone_evidence.py NetPath_Evidence.zip`. The script does not touch any network. [Read the complete reproducibility report](docs/windows-docker-benchmark-2026-10-29.md).

## Successful four-AS routed UDP pilot — 30 October 2026

An operator-supplied Windows/Docker run recorded **737/737 UDP application echoes with zero timeouts in a 15-second pilot** across Edge and Core via the separate four-AS FRRouting lab. This is screenshot-confirmed execution; the raw JSON/CSV/events still require independent review. [Pilot verification record](docs/windows-bgp-routed-pilot-2026-10-30.md).

## Next study: repeated BGP-routed baseline and failover

The [operator protocol](docs/reproducible-bgp-study.md) explains a reproducible 3-control / 3-controlled-fault study connecting **NetPath Bench** and **BGP Routing Laboratory**. It preserves source reports and checks primary recovery after every fault. The **first new three-run no-fault control series has now completed** (30 October 2026): 3,535/3,535 application UDP echoes with no unsuccessful replies, with healthy BGP checks before and after each trial. This result is corroborated by operator PowerShell output; original trial bundles and p99 values have not been independently reviewed for this series. Three corresponding fault-injection trials remain **pending**. Failover is opt-in and limited to the isolated Docker lab.

## Reproduce a standalone benchmark

On **Windows 11 + Docker Desktop with Linux containers**, from this repository:

```powershell
docker compose build
docker compose up -d server
docker compose run --rm bench selftest

docker compose run --rm bench udp --host server --count 500 --bytes 64 --timeout-ms 250 --interval-us 1000 --json /reports/udp.json --csv /reports/udp.csv
docker compose run --rm bench tcp --host server --count 500 --bytes 64 --timeout-ms 250 --interval-us 1000 --json /reports/tcp.json --csv /reports/tcp.csv

docker compose down
```

Collected reports are under local ignored `reports/`. For experiments *through* the four-AS routing lab, read the [BGP routed experiment runbook](docs/bgp-routed-experiment.md) first: it includes checks, explicit fault-injection consent and recovery.

On Linux, verify the C++ and Python tests without Docker:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
ctest --test-dir build --output-on-failure
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Additional network-engineering studies

**Linux network counters:** [source](scripts/linux_net_diagnostics.py) · [runbook](docs/linux-network-performance.md). Samples interface drops/errors and namespace-level softnet/TCP counters without adjusting host settings. This is instrumentation, not demonstrated low-latency optimization.

**Synthetic market-data-like UDP stream:** [source](scripts/market_data_feed_lab.py) · [tests](tests/test_market_data_feed_lab.py) · [explainer](docs/market-data-feed-lab.md).

```powershell
py -3 scripts/market_data_feed_lab.py demo --count 80
```

The synthetic feed uses real local UDP sockets with an invented protocol. **It is not a live exchange feed, a completed FIX/FAST implementation, or a production multicast system.**

## Review the engineering decisions

| Focus | Where to look |
| --- | --- |
| C++ sockets, framing and clocks | [`src/netpath_bench.cpp`](src/netpath_bench.cpp) |
| TCP/UDP integration tests | [`tests/integration.py`](tests/integration.py) |
| BGP-controlled experiments | [`scripts/bgp_routed_trial.py`](scripts/bgp_routed_trial.py) |
| Independent sample verification | [`scripts/audit_conditions.py`](scripts/audit_conditions.py) |
| Performance methodology | [`docs/metrics-and-limitations.md`](docs/metrics-and-limitations.md) |
| Engineering tradeoffs and design review | [`docs/design-review.md`](docs/design-review.md) |
| Interview-ready evidence explanation | [`docs/portfolio-evidence.md`](docs/portfolio-evidence.md) |
| Full automated testing | [GitHub Actions](https://github.com/milenastrahova/netpath-bench/actions) |

## Limits

The measurements are **sequential user-space RTT inside Docker/WSL2**, not PTP-synchronized one-way wire latency, kernel-bypass or NIC hardware timestamps. No trading-exchange infrastructure is used. This independent lab provides reproducible code and bounded evidence—not a production HFT performance claim.

*Independent engineering portfolio project.*
