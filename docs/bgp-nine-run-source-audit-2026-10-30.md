# Source-verified nine-run BGP UDP routing experiment

**Study date:** 29 October 2026 UTC / 30 October in Riga.  
**Evidence:** three original ZIP archives uploaded by the Windows workstation operator, inspected in full by an independent offline Python audit on 30 October. **All 9 original experiment triplets (JSON + CSV + event journal), per-run nested ZIP bundles and series manifests matched.** The original source ZIPs are not published here; their SHA-256 fingerprints are retained below.

## Summary

| Condition | Independent 24-second runs | UDP echo attempts | Successful replies | Application timeouts | Median of per-run p99 RTT |
| --- | ---: | ---: | ---: | ---: | ---: |
| No fault injected | **6** | **7,067** | **7,067** | **0** | **0.633097 ms** |
| Primary transit deliberately stopped | **3** | **3,513** | **3,510** | **3** | **0.583104 ms** |
| **Total** | **9** | **10,580** | **10,577** | **3** | — |

In the deliberately disrupted condition, **3/3,513 = 0.0854%** of application echo requests timed out (one in each fault run). All three timed-out requests occurred inside the **approximate stop-to-restore orchestration window**. Each run's controller checked BGP health before injecting a fault and after recovery; an additional final live `labctl.py check` succeeded on the operator's Windows Docker lab.

These are measured application responses over a virtual BGP-routed Docker network; they **do not prove wire packet loss, zero data-plane interruption, or HFT production latency**.

## All original runs

Configuration for both conditions: 64-byte payload, UDP, 24-second observation, **20 ms configured issue interval**, **200 ms application timeout**, Edge `10.10.10.1` to Core `10.40.40.1` via an isolated four-AS FRRouting lab. Fault runs additionally used `--fault-at 6 --fault-seconds 5`; all controls were completed before the fault series.

| Run | Condition | Probes | Timeouts | Mean RTT (ms) | p95 (ms) | p99 (ms) | Maximum (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ctrl261030004525-01` | control | 1,179 | 0 | 0.236843 | 0.482193 | 0.670010 | 1.192101 |
| `ctrl261030004525-02` | control | 1,178 | 0 | 0.242743 | 0.451906 | 0.635133 | 1.139199 |
| `ctrl261030004525-03` | control | 1,178 | 0 | 0.242232 | 0.454775 | 0.625558 | 1.085831 |
| `ctrl261030005946-01` | control | 1,176 | 0 | 0.271759 | 0.506778 | 0.631060 | 1.015416 |
| `ctrl261030005946-02` | control | 1,179 | 0 | 0.235050 | 0.481608 | 0.755299 | 1.332409 |
| `ctrl261030005946-03` | control | 1,177 | 0 | 0.261932 | 0.496390 | 0.630021 | 0.843482 |
| `fault261030005336-01` | failover | 1,169 | 1 | 0.234790 | 0.458634 | 0.693676 | 1.186988 |
| `fault261030005336-02` | failover | 1,172 | 1 | 0.190649 | 0.390562 | 0.507498 | 0.811107 |
| `fault261030005336-03` | failover | 1,172 | 1 | 0.194872 | 0.388344 | 0.583104 | 0.799813 |

**No selective exclusion:** all nine runs and all timed-out observations are included. RTT percentiles are computed over **successful** application echoes only, not an artificial RTT assigned to timed-out requests. Nearest-rank percentiles were recomputed from every original per-sequence CSV and matched each JSON summary. The six control p99s ranged from **0.625558–0.755299 ms** and the three fault-run p99s from **0.507498–0.693676 ms**.

### Exactly when were echoes missing?

| Run | Missing sequence | Time offset from probe start | Phase indicated by approximate UTC event correlation |
| --- | ---: | ---: | --- |
| Fault 1 | **294** | **5,997.103319 ms** | Stop requested → restore command completed |
| Fault 2 | **295** | **5,990.758836 ms** | Stop requested → restore command completed |
| Fault 3 | **297** | **6,032.540561 ms** | Stop requested → restore command completed |

There were no other non-`ok` records in the provided CSV files. All three misses are labeled `timeout` in the original data. **Important nuance:** the probe's timestamp is the beginning of the request, not the exact instant when the configured 200-ms timeout completed. Correlation uses Windows/Docker wall-clock event timestamps and an application start time plus monotonic offsets; these clocks are **not hardware synchronized**. Differences of roughly 0–3 ms were observed between reported UTC elapsed time and the monotonic observation duration in some runs. Therefore the rows above are *approximate orchestration-phase associations*, **not precise BGP convergence timing**.

## Independent source audit

The original three ZIPs were read in full. The audit checked:

1. ZIP structure and integrity (no duplicate or traversal names), and completeness of three trials per series.
2. **9 nested original per-run ZIPs**, their series-manifest SHA-256 values, and equality of their JSON/CSV/events contents to corresponding top-level files.
3. **All 10,580 CSV sequence indices**, monotonically increasing per-run offsets, valid statuses and RTT values.
4. Exact JSON/CSV agreement on attempts, successful replies, timeouts and unexpected replies.
5. Recomputed **min/mean/p50/p95/p99/p99.9/max RTT**, nearest-rank method, and consecutive absolute RTT differences against original JSON within displayed rounding tolerance.
6. Event-journal identity, `CAPTURED` status, sequence of orchestration events, and plausible UTC duration (bearing in mind separate timing sources).

**Original source-archive SHA-256:**

- `control-ctrl261030004525.zip`: `a9f09a30f4910fe8bd0788e027b054d32dde0f333cf077b57c2064e130d07590`
- `control-ctrl261030005946.zip`: `6754eef753fef16440d6d7dd5d1309e76b1f6bb7b71757f3700887a30f6a9dc5`
- `series-fault261030005336.zip`: `c0ab5f309db70545eef5d0235adc5c73a5a30da0e186990f0c304d91fdef6f92`

**Original per-run CSV SHA-256:** see [machine-readable summary](../evidence/bgp-nine-run-audit-2026-10-30.json) for all nine exact checksums and measured per-run values.

The per-run series manifests were independently consistent with the source data. This is an **internal-data-consistency and source-provenance** audit; file hashes by themselves cannot authenticate the physical laboratory or establish external authorship.

## Interpretation: why lower p99 in fault runs is not 'faster'

- Some failed responses are **excluded** from the RTT percentile, so even a lower success-only p99 can coexist with worse service continuity.
- The controls were performed before the fault runs: CPU load, caching, host scheduling and background activity can differ. Trials were not randomized/interleaved.
- With only three fault runs there is no meaningful basis to claim a speed advantage or a production reliability SLA.
- An application-level missing reply is not conclusive proof of a physical packet lost on the wire.
- Docker command timestamps and sampling cannot establish a packet-level failover/convergence duration.

**Defensible CV statement:** “Built and validated a four-AS FRRouting Docker network and a C++17/Python UDP measurement workflow; independently audited nine 24-second trials covering 10,580 application echo attempts, including three controlled BGP primary-path outages, route restoration and source-level evidence validation.”

**Not defensible:** claims of hardware-NIC microsecond latency, production exchange connectivity, 99.9% availability guarantees, or a specific measured BGP convergence interval.

## Reproduce and check

Follow [the Windows operator runbook](../docs/reproducible-bgp-study.md). The executable [offline condition-audit script](../scripts/audit_conditions.py) accepts one control-source ZIP and one failover-source ZIP at a time. It must receive an individual series archive, not a composite of all three supplied archives. Retain original CSV/JSON files and their hashes. For full nine-run replication, process each original series, then compare their independently verified summaries without pooling unlike conditions.

**Evidence transparency:** the raw source archives remain with the operator and were not committed to a public Git repository. Their exact SHA-256 fingerprints let an interviewer verify unchanged originals if access is later granted.
