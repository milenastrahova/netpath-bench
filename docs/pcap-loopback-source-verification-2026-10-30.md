# Evidence report — Linux UDP echo / PCAP source verification

**Milena Strahova**  
**Project:** NetPath Bench · independent network engineering case study  
**Evidence date:** 30 October 2026 · **Audit:** PASS  

## Executive finding

A user-operated Windows 11 / Docker Desktop / WSL2 laboratory generated four controlled UDP loopback measurement runs (two standard-buffer, two larger-buffer). An independent review of the original uploaded archive verified **480/480 matching application replies, zero application timeouts, 1,040 captured UDP frames and 520 complete request/reply pairs** (480 measured and 40 warmup). Each observed NPS1 request and reply could be reconciled by session ID, client/server ports, direction, and sequence number; no duplicated or unexpected NPS1 observations were found.

**Engineering conclusion:** The evidence confirms a repeatable packet-capture, CSV integrity and application-to-capture correlation workflow. It does **not** demonstrate superior HFT performance, faster physical-network routing, or a causal socket-buffer latency improvement.

## Laboratory architecture

```text
Windows 11 host / Docker Desktop / WSL2
  └── isolated Linux Docker namespace (--network none)
       ├── UDP echo client ↔ UDP echo server (127.0.0.1)
       ├── tcpdump -i lo  (UDP port 19371)
       │     └── classic Ethernet/IPv4 PCAP
       ├── source CSV + JSON, microsecond application RTT
       └── independent review
              ├── CSV ↔ summary (hashes, counts, percentiles)
              ├── PCAP binary decode and source SHA-256
              └── request ↔ reply by session/port/sequence
```

All generated packets remained inside the container-local loopback environment. There was no captured traffic from a physical NIC or a trading exchange.

## Exact experimental conditions

- Python 3.12.16 on WSL2 Linux 6.18.54.1-microsoft-standard-WSL2-x86_64-with.
- Application protocol: self-generated `NPS1` UDP echo, 64-byte payload, monotonically measured RTT.
- Two repeats using alternating A/B order; four runs of 120 counted requests each, plus 10 warmup requests per run.
- Interval request: 1 ms; response timeout: 200 ms; echo server UDP port: 19371.
- Socket-buffer profiles: 65,536 requested / 131,072 effective bytes, versus 524,288 requested / 1,048,576 effective bytes.
- Source capture: classic Ethernet/IPv4 PCAP with microsecond capture timestamps, limited to Docker loopback.

## Source-recomputed application RTT

| Repeat | Profile | Replies | p50 (µs) | p95 (µs) | p99 (µs) | Maximum (µs) |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Standard | 120/120 | 68.514 | 103.874 | 128.921 | 716.427 |
| 1 | Larger buffer | 120/120 | 66.061 | 92.090 | 151.060 | 218.835 |
| 2 | Standard | 120/120 | 66.714 | 120.294 | 198.175 | 205.696 |
| 2 | Larger buffer | 120/120 | 67.942 | 117.504 | 129.042 | 140.230 |

All four runs had **zero application timeouts**. Percentiles were recomputed directly from each CSV sample, not copied from `summary.json`.

### Interpretation of buffering result

- Run 1: larger-buffer p99 was **151.060 µs versus 128.921 µs** for standard buffer (higher/worse).
- Run 2: larger-buffer p99 was **129.042 µs versus 198.175 µs** for standard buffer (lower/better).
- Across pooled successful samples (240 per condition), p50 was 67.457 µs standard and 67.168 µs larger-buffer; pooled p99 was 195.748 µs and 137.265 µs respectively. These pooled statistics **do not establish** a buffer optimization, especially with only two independent runs per condition and unsaturated loopback echo traffic.
- The standard-buffer first run contained a 716.427 µs high tail sample while its p99 was 128.921 µs. Reporting the maximum alongside percentiles avoids hiding outliers.

## Packet-level correlation of original PCAP

| Evidence check | Independently verified result |
|---|---|
| PCAP capture size | 126,904 bytes |
| Decoded Ethernet/IPv4 UDP frames | 1,040 |
| TCP frames and unsupported frames in this dataset | 0 / 0 |
| UDP client → server request frames | 520 |
| UDP server → client reply frames | 520 |
| Full request/reply pairs including warmup | 520 / 520 |
| Measured application exchanges | 480 / 480 |
| Warmup exchanges | 40 / 40 |
| Missing request/reply capture observations | 0 |
| Duplicate or unrecognized NPS1 frames | 0 |
| Source files matched their SHA-256 manifest | 8 / 8 |

The original PCAP was parsed separately from the included `packet-analysis.json`; each Ethernet/IPv4 UDP frame carried a 64-byte `NPS1` datagram and matched one recorded stream/session, directional port pair, and sequence value. Captured reply timestamps were after their associated request timestamps.

### Capture timestamps versus application RTT

| Repeat | Profile | PCAP request→reply timestamp delta p50 (µs) | p99 (µs) |
|---:|---|---:|---:|
| 1 | Standard | 31.000 | 67.000 |
| 1 | Larger buffer | 31.500 | 92.540 |
| 2 | Standard | 31.500 | 99.000 |
| 2 | Larger buffer | 32.000 | 75.620 |

These deltas are calculated from the two observed PCAP timestamps for the same local UDP sequence. They are **not the application RTT**, **not calibrated wire latency**, and **not one-way physical NIC timestamps**. Capturing packets adds measurement overhead and can change timing.

## Source integrity and independent audit

- Original source ZIP SHA-256: `d326d2a4242fa408fcaa7c2f55a1cb721d5c2799a154d65041357b47c68ac742`
- Original PCAP SHA-256: `2199b38a2108dbd69037dc9454a202e26fb85a4ea7ce19d9fea111475390967c`
- The independently generated structured summary is [`evidence/pcap-loopback-source-audit-2026-10-30.json`](../evidence/pcap-loopback-source-audit-2026-10-30.json).
- SHA-256 validation covered all 8 source members listed in the ZIP manifest (four source CSVs, trial summary, PCAP, packet analysis and correlation JSON).
- All source CSV counts, p50, p95, p99, and maximum values were independently recomputed; each was checked against the original JSON.
- The raw PCAP remains in private user evidence because even nonproduction captures should be reviewed before publication. It is not committed to the repository.

## Reproducibility

From the repository root on Windows with Docker Desktop:

```powershell
git switch main
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-Pcap-Evidence.ps1
```

The command builds a local Docker image and executes a bounded loopback capture (`--network none`). Evidence appears under `reports/pcap-study-<UTC>-<random>.zip`. The launcher never changes the Windows networking configuration. The supplied snapshot uses 120 counted packets × four runs; new trials may yield different timing results.

## Limitations, responsible claims and follow-up

1. Lab traffic is serial, user-space, process-local loopback in Docker/WSL2. This is not HFT throughput, PTP/NIC timestamping, kernel bypass, colocation, exchange market data, or physical wire loss measurement.
2. Neither a complete PCAP nor zero application timeouts proves behavior under network congestion. There is no external route or physical switch in this capture.
3. A buffer-performance hypothesis requires more independent paired experiments and a workload that actually challenges receive queues. These four short runs are a correctness study, not tuning evidence.
4. A useful next controlled experiment would be multi-stream or burst-rate UDP traffic across distinct namespaces with intentionally constrained receiver capacity, plus Linux kernel counters and PCAP sequence checks.

### Reviewer one-line summary

> Reconciled 1,040 real Docker-loopback UDP PCAP frames with 480/480 source-audited application echo attempts across four trials; verified 520 request/reply pairs, zero capture gaps, and SHA-256 integrity of eight original evidence files, while explicitly separating capture timestamps from user-space RTT.