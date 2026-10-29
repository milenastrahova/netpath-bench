# Windows Docker TCP/UDP loopback benchmark — 29 October 2026

**Origin:** PowerShell screenshots supplied by the workstation operator on 29 October 2026. All numbers below were read from the program's printed JSON. **Raw `reports/udp.json`, `reports/tcp.json` and corresponding CSV files have not been provided for an independent record-level audit.** This is a user-observed local execution report, not a published evidence bundle.

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

1. Preserve both local JSON and CSV outputs rather than taking only terminal screenshots.
2. Run repeated randomized or alternating UDP/TCP trials with identical payloads, counts and timeout settings; retain every raw sample, run order and environment version.
3. Use existing scripts to check the original files' counts and consistency before publishing a minimized, scrubbed evidence bundle.
4. Keep the distinction between *application response missing by deadline* and actual physical packet loss.
5. To study routed resilience, run the existing [isolated BGP path experiment](bgp-routed-experiment.md), not `docker compose down` or failure injection against an unrelated project.

*Original evidence files remain on the operator's Windows workstation. No fabricated hash, CSV content, or post-hoc test result is attributed to this report.*
