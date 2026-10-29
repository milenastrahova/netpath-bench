# Windows Docker bridge TCP/UDP benchmark — 29 October 2026

**Origin and verification:** The workstation operator supplied both the original PowerShell screenshots and a ZIP containing `udp.json`, `udp.csv`, `tcp.json`, and `tcp.csv` on 29 October 2026. All **1,000** per-request records were parsed offline independently, and the program's reported mean, nearest-rank p50/p95/p99/p99.9, min/max, and adjacent absolute RTT difference statistics were reproduced from CSV. Counts and sequence numbers match. Source files are retained as an uploaded private ZIP, **not committed to this repository**; the immutable byte hashes below allow the operator to rerun and verify the checks. The hashes do not cryptographically prove the measurement environment or authorship.

## Environment and commands

Windows 11, Docker Desktop Linux engine, Alpine-based C++17 image `netpath-bench-lab:1.0`, a server and a benchmark client on the dedicated internal Docker Compose network `bench-net`.

```powershell
docker compose build
docker compose up -d server
docker compose run --rm bench selftest
docker compose run --rm bench udp --host server --count 500 --bytes 64 --timeout-ms 250 --interval-us 1000 --json /reports/udp.json --csv /reports/udp.csv
docker compose run --rm bench tcp --host server --count 500 --bytes 64 --timeout-ms 250 --interval-us 1000 --json /reports/tcp.json --csv /reports/tcp.csv
docker compose down
```

- Docker image built successfully; runtime image's in-build C++ selftest completed.
- `SELFTEST PASS: codec, invalid magic, quantile, null stats, CSV samples`.
- Both live echo clients completed and produced JSON summaries and CSV output paths.
- Final `docker compose down` removed the NetPath Bench server container and its dedicated network; the BGP Routing Laboratory is a separate Compose project and was not used for these two trials.

## Independently verified raw-data consistency

- **Verdict:** PASS for internal CSV/JSON consistency; **500 consecutive sequences** `0–499` for each of TCP and UDP, all `ok` with 0 timeouts, 0 errors and 0 unexpected replies. Monotonic offsets increase in both CSV files.
- **UDP:** adjacent absolute RTT difference mean **0.033764 ms**, p99 **0.188683 ms**; largest RTT **1.008590 ms at sequence 453**, with only one UDP RTT above 0.5 ms.
- **TCP:** adjacent absolute RTT difference mean **0.027293 ms**, p99 **0.198849 ms**; largest RTT **0.411629 ms at sequence 491**.
- **Timestamp precision:** wall-clock UTC timestamps in the summary are displayed to the nearest millisecond, while `observation_duration_ms` has finer precision (UDP **594.271520 ms**, TCP **584.050000 ms**). Sub-millisecond disagreement from rounding is expected, not an inconsistency.
- **Nearest-rank detail:** with 500 values, p99.9 selects the maximum (rank 500). This cannot justify a reliable 99.9th-percentile service-level claim.

### SHA-256 source fingerprints

| Evidence file | SHA-256 |
| --- | --- |
| Original `NetPath_Evidence.zip` | `9914f7a4cd7259f1f43b53644b3ba79320fc7f38d8665b8e0ebacdb951526d81` |
| `udp.csv` | `6ac0de68c6300c0968fbbec2e25a84eb3c0665d94e8063d3d1a9bd51fe9bae0d` |
| `udp.json` | `521a5096ea3ad5d8dba4e984c71ee1382531459abf7185cef7b6f188776cce67` |
| `tcp.csv` | `98b88caf7c0d9022fa5d8c22766e1cd3fcfcbacc7859d1af491edf02719096e8` |
| `tcp.json` | `d214090ce33c85ccfe138056ac0701ae72d98970d05de1fc366c32a4eadaf2aa` |

## Results visible in the output

| Metric | UDP echo | TCP echo |
| --- | ---: | ---: |
| Requests attempted | 500 | 500 |
| Successful matched replies | 500 | 500 |
| Application-level timeouts | 0 | 0 |
| Application-level errors | 0 | 0 |
| Payload bytes | 64 | 64 |
| Interval configured | 1,000 µs | 1,000 µs |
| Timeout configured | 250 ms | 250 ms |
| Mean RTT | 0.099204 ms | 0.083121 ms |
| Minimum RTT | 0.019193 ms | 0.027611 ms |
| p50 RTT | 0.079335 ms | 0.059065 ms |
| p95 RTT | 0.230241 ms | 0.202344 ms |
| p99 RTT | 0.319658 ms | 0.306448 ms |
| p99.9 RTT | 1.008590 ms | 0.411629 ms |
| Maximum RTT | 1.008590 ms | 0.411629 ms |

Both runs reported zero `unexpected_replies`. The UDP run's start timestamp as printed was `2026-10-29T21:15:46.129Z`; the TCP run's start timestamp as printed was `2026-10-29T21:15:55.238Z`.

## What the results do and do not show

- **Shows:** the C++17 tool built in Docker, the server exchanged 500 TCP and 500 UDP application echoes within each respective timeout, and its output included percentile estimates and per-attempt report files.
- **Does not show:** that TCP generally has lower latency than UDP. These are two non-paired short trials, with different execution times; no repeated randomized or interleaved samples were taken.
- **Does not show:** Ethernet wire timing, hardware NIC counters, one-way latency, kernel-bypass performance, sustained throughput, real exchange network conditions, or proof of a physical network with zero packet loss.
- The reported `p99.9` and maximum values are sensitive to sample size. A nearest-rank percentile from 500 observations is not a reliable tail-SLA estimate.
- Results here are from **the NetPath Bench internal Docker bridge** rather than the separate four-AS FRRouting topology. Earlier routed experiments are documented independently.

## Next reproducibility step

1. **Completed:** preserved the original JSON and CSV in `NetPath_Evidence.zip` and verified all 1,000 CSV records against JSON summaries. Keep the private ZIP unchanged as the archived original.
2. Run repeated randomized or alternating UDP/TCP trials with identical payloads, counts and timeout settings; retain every raw sample, run order and environment version.
3. Verify the SHA-256 source fingerprints and rerun the offline report checker before making a minimized, scrubbed evidence bundle publicly available.
4. Keep the distinction between *application response missing by deadline* and actual physical packet loss.
5. To study routed resilience, run the existing [isolated BGP path experiment](bgp-routed-experiment.md), not `docker compose down` or failure injection against an unrelated project.

*Source ZIP was supplied privately and independently checked; raw bytes remain outside the Git repository pending an intentional publication decision. All listed hashes are computed from the received original files. No claim of production performance, authorship authentication or physical packet loss is made.*
