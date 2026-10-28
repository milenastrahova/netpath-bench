# NetPath Bench v1.0 Release Candidate — Quality and Acceptance

## Confirmed from user-supplied evidence (28 October 2026)

- Two healthy control runs, both BGP health-checked before and after by the runner: 1175/1175 and 1178/1178 echoed UDP probes.
- Two isolated primary-transit failure runs: 1167/1168 and 1165/1166 echoes, including one timeout per run. BGP restoration checks reported PASS after each injected failure.
- Source archives independently parsed and verified, including nested ZIP equality and SHA-256, individual probe counters and jitter/RTT statistics.
- Common experimental parameters: 64-byte payload, UDP request/response, timeout 200 ms, interval 20,000 microseconds, 24 seconds per run, same lab endpoint IPs.
- Run-level median successful-response p99: 0.800839 ms control, 0.680034 ms injected fault. No evidence of increased *successful-response* p99 in this small dataset.

## Not established

- Precise BGP convergence or forwarding outage in milliseconds, physical packet loss, PTP-synchronized one-way latency, hardware NIC timestamping, actual trading-exchange performance, or causal inference.
- Control runs were sequentially gathered later than failure runs; uncontrolled CPU and scheduling load may differ. Sample count alone is not the number of independent experimental replicates.
- Only application echo timeouts were measured, with sequential request/response rather than a concurrent high-throughput UDP stress workload.

## Acceptance gates

- [x] Assistant-side Linux Python unit tests (including corrupted/tampered input rejection).
- [x] Assistant-side Linux CMake/C++ selftest and real loopback integration test.
- [x] Full original evidence verification on four user-supplied experimental runs.
- [x] Original field archives excluded from source release; portable aggregates only.
- [ ] User's Windows 11 / Python verification of the release candidate.
- [ ] User's Windows Docker Desktop image selftest of the release candidate (same C++ core was field-validated in earlier release).
- [ ] Hosted GitHub Actions for Ubuntu and Windows matrix, including Docker smoke.
- [ ] Private repository creation and publication.

## Reproduction

```powershell
py -3 -m unittest discover -s tests -p 'test_*.py' -v
py -3 .\scripts\audit_conditions.py --control-zip 'PATH_TO_CONTROL.zip' --failover-zip 'PATH_TO_FAILOVER.zip' --output-dir .\reports\final-condition-audit
```

Avoid committing raw CSVs, timestamped events, diagnostic logs or personal paths. This is a controlled lab project, not commercial or production HFT experience.
