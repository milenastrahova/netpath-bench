# Measurement methodology and limitations

**Measurement object:** user-space C++ application request/echo RTT for TCP and UDP. For UDP the client sends one datagram per attempt then waits for a matching echo (stop-and-wait). For TCP the client uses one already-established connection.

**Start/stop:** a single `std::chrono::steady_clock` measures each send-to-reply interval, unaffected by NTP wall-clock adjustments. `started_at_utc` and CSV offsets help place samples near faults but are not precision-synchronized across host/VM.

**Denominators:** `attempted` is the actual number of sends attempted (can be below a maximum when `--duration-sec` is used). `successful_echoes` counts echoes with correct magic/version/session/sequence/size; UDP checks source address/port. `echo_failure_ratio = (attempted - successful_echoes)/attempted` is application acknowledgment failure, **not wire loss**.

**Sample CSV:** `sequence,start_offset_ms,status,rtt_ms` for each attempted exchange. A timeout has `rtt_ms=null`; no fabricated zero delay. Time starts before send attempt, and the offset is against monotonic run start. Some TCP errors terminate the series; no samples are invented for unsent attempts.

**Percentiles:** sorted successful RTT values, nearest-rank p50/p95/p99/p99.9. Do not imply accurate p99.9 with a few dozen/hundred samples. With 200 successes, p99.9 equals the maximum. Always report sample count, errors, test topology and configuration.

**Jitter:** the reported adjacent-successful-RTT absolute difference is a *rough variability indicator*. It is **not** RFC 3550 jitter and not packet inter-arrival variation or one-way-delay variation.

**Uncontrolled sources of noise:** Windows host scheduling, Docker Desktop virtualization, WSL2, Linux guest scheduling, timer granularity, CPU power management, application load, virtual NIC bridging, container overhead, reverse-route changes and the echo server's own scheduling.

**Next-step higher-fidelity testing:** receiver-side UDP stream accounting (unique sequences, duplicates/reorder), capture with pcap, Linux perf/eBPF, and only later hardware/NIC timestamping on appropriately supported physical equipment. Do not infer data-center SLA or production deployment readiness from lab measurements.
