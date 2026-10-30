# Source-verified Linux UDP socket-buffer experiment — 30 October 2026

**Milena Strahova · NetPath Bench · independent network engineering portfolio**  
**Audit result: PASS** — original CSV rows and SHA-256 fingerprints independently reconciled with the experiment's `summary.json`.

## Engineering question

Does requesting a larger per-process UDP receive/send socket buffer improve application-level echo performance, particularly tail latency, in a controlled Linux Docker/WSL2 loopback workload?

**Outcome:** All 1,800 application requests received their matching replies within the deadline, with **zero application timeouts**. The larger-buffer condition had a lower *pooled* p50 but **did not provide a repeatable improvement in per-run p99**. This does **not** establish a socket-buffer optimization or NIC performance gain.

## Environment and protocol

- **Operator environment:** Windows PowerShell with Docker Desktop and a Linux container. Container-reported platform: `Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with`; Python `3.12.16`.
- **Scope:** loopback UDP echo with a 64-byte application datagram, not routed traffic between BGP peers.
- **Test matrix:** 3 repetitions × 2 buffer profiles × 300 measured requests = **1,800 attempts**; per trial, 10 warmup requests are excluded.
- **Ordering:** `baseline → larger`, `larger → baseline`, `baseline → larger` (AB/BA/AB).
- **Timing:** 1 ms nominal interval; 200 ms application timeout. User-space monotonic-clock RTT; three decimal places of microsecond resolution in CSV.
- **Baseline:** requested `SO_RCVBUF` / `SO_SNDBUF` = **65,536 bytes**; reported effective values = **131,072 bytes** at both client and server.
- **Larger profile:** requested **524,288 bytes**; reported effective values = **1,048,576 bytes** at both endpoints. These are process-local socket options, **not Linux sysctl or NIC settings**.
- **Source:** user-supplied `socket-buffer-evidence.zip` containing six original CSV files and `summary.json`. The raw ZIP is retained outside the repository; the reproducible audit metadata and source hashes are linked below.

## Source-verified run results

All times below are **microseconds (µs)**. Tail percentiles are computed on successful replies; each run had zero timeouts.

| Repeat | Profile | Requests / replies | RTT p50 | RTT p95 | RTT p99 | Maximum RTT |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Baseline | 300 / 300 | 123.849 | 250.105 | 360.056 | 468.275 |
| 1 | Larger buffer | 300 / 300 | 96.860 | 215.958 | 404.354 | 595.564 |
| 2 | Larger buffer | 300 / 300 | 111.059 | 254.889 | 410.226 | 624.816 |
| 2 | Baseline | 300 / 300 | 147.245 | 316.135 | 406.160 | 559.384 |
| 3 | Baseline | 300 / 300 | 139.291 | 286.279 | 447.368 | 971.230 |
| 3 | Larger buffer | 300 / 300 | 132.217 | 272.562 | 409.329 | 674.001 |

**Pooled descriptive summary** (900 measured replies per profile; not independent replicate counts):

| Profile | p50 | p95 | p99 | Application timeouts |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 136.696 | 285.454 | 402.301 | 0 / 900 |
| Larger buffer | 112.091 | 254.771 | 410.167 | 0 / 900 |

**Paired p99 change (larger − baseline):** repeat 1 **+44.298 µs**, repeat 2 **+4.066 µs**, repeat 3 **−38.039 µs**. A positive change means higher (worse) observed p99. Two pairs had higher p99 with the larger buffer and one had lower p99; there is no stable p99 improvement across the three pairs. A lower pooled p50 should not be presented as evidence of improved HFT performance.

## Audit and evidence integrity

An independent review parsed the original ZIP and performed the following checks:

1. Confirmed expected **seven files**: `summary.json` plus six run CSV files.
2. Recomputed SHA-256 for each CSV and matched it against the corresponding hash in `summary.json`.
3. Confirmed each CSV has **300 records**, contiguous sample sequences `0..299`, `ok` status and a finite non-negative RTT value for every attempt.
4. Recomputed p50, p95, p99 (linear interpolation on sorted samples), maximum and median absolute successive successful-RTT difference for each run, comparing them with source metrics.
5. Verified the profile requests, effective socket-buffer readbacks, run ordering, replies and timeout totals.
6. Independently calculated pooled descriptive statistics and per-repetition p99 differences. **All checks passed.**

**Original ZIP SHA-256:** `1f8f928081471f7edfd7d7aded8c30952dfd27d3a640cd3b9106291be0ce7e3c`  
**Original `summary.json` SHA-256:** `8f9107946717e774ca2e3a78e6b3fb15d018cd8dcdd733b9a5c87554d6d87cb7`

| Original CSV | SHA-256 |
| --- | --- |
| `01_baseline.csv` | `43190ad663446f33080dddb560754bba23f6a38f2162e67aee2d5303e5d548c4` |
| `01_larger_buffer.csv` | `5b5d7e674ebc9634fcb1dd428118dec7b1547a8b0728bb8bca580e2369787153` |
| `02_larger_buffer.csv` | `83948a8ad7e8575f2917cd70179dc72dda69318c5629acf1a5981f694f3da34a` |
| `02_baseline.csv` | `b3d9089b60ee4c5600376ce76961d339697c78bf1360525a4594e84307f85021` |
| `03_baseline.csv` | `311284c6c8cce3fe0cbc6094e66eaa553519be0c448f3103a61d7a6854b3c829` |
| `03_larger_buffer.csv` | `e2b20ce3cc90c098116853c78804e55092e6befb5380a8ab030974aff17861c1` |

[Machine-readable audit summary](../evidence/socket-buffer-source-audit-2026-10-30.json) · [Experiment implementation](../scripts/socket_buffer_study.py) · [Independent CSV auditor](../scripts/audit_socket_study.py) · [Methodology](socket-buffer-and-packet-trace-study.md)

## Reproduce and verify

From the NetPath Bench root on Windows 11 with Docker Desktop running:

```powershell
docker run --rm -v "${PWD}:/work" -w /work python:3.12-alpine python scripts/socket_buffer_study.py --output-dir reports/buffer-ab-repeat-2 --repetitions 3 --count 300
docker run --rm -v "${PWD}:/work" -w /work python:3.12-alpine python scripts/audit_socket_study.py reports/buffer-ab-repeat-2/summary.json
```

Use a **new output directory** for each run. The existing source bundle can be verified by extracting its seven original members together, running `python scripts/audit_socket_study.py path/to/summary.json`, and comparing its ZIP checksum with the SHA-256 above. The original ZIP is not committed because it is an operator artifact; metadata alone does not independently reproduce measurements without that archive.

## Limitations and engineering judgment

- This is Linux **container/WSL2 loopback application RTT**. It is not packet-level wire latency, a data-center NIC measurement, one-way latency or production trading/exchange performance.
- Serial echo requests at 1 ms spacing are unlikely to fill socket receive queues; this workload does not isolate congestion- or queue-pressure-related gains from buffer sizing.
- Docker/WSL2 scheduling, virtual networking, background host load, time resolution and warmup effects can influence observed differences.
- The three repetitions per profile are small, and every attempt succeeded. This experiment does not test performance under packet loss or queue saturation; no causal improvement is demonstrated.
- Zero **application timeouts** means only that replies were matched before the defined timeout in this experiment; it does not prove zero physical-layer packet loss in other settings.
- Source hash reconciliation confirms **file integrity and internal statistical consistency**, not external attestation that the environment was tamper-free.

**Engineering takeaway:** Treat p50 and p99 separately, verify source records independently, report timeouts alongside successful-reply tail percentiles and avoid claiming an optimization that is not consistently supported by measurements.