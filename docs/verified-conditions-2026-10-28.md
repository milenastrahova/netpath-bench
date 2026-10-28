# NetPath Bench — Verified control versus failover observations

## Test conditions

- Protocol: UDP, 64-byte application payload; 24-second trials, interval 20000 microseconds, timeout 200 milliseconds.
- Traffic: Edge 10.10.10.1 to Core 10.40.40.1 through FRRouting in Docker/WSL2.
- Conditions were collected sequentially; operating-system load and clock synchronization were not controlled.

## Original-data verification

**PASS:** both source archives were checked against raw CSV/JSON, event records, original nested bundles and SHA-256 references.

| Metric | Healthy control | Injected primary failure |
| --- | ---: | ---: |
| Independent runs | 2 | 2 |
| Application echo requests | 2,353 | 2,334 |
| Successful echoes | 2,353 | 2,332 |
| Unsuccessful echoes | 0 | 2 |
| Observed failure ratio | 0.0000% | 0.0857% |
| Median of run-level p99 successful RTT | 0.800839 ms | 0.680033 ms |

## Interpretation

A missing application-level echo was seen in each injected-failure run and none in the two control runs.
The p99 RTT of **successful** echoes was numerically lower in the injected-failure runs: this is not an improvement claim, because missing echoes are excluded from successful-RTT percentiles and the trials are not matched for host load.
The time alignment of each missed echo and the stop request is approximate; the analyzer does not measure network outage duration or BGP protocol convergence.

## Per-run p99 (ms)

### Control

Runs: 2; median p99: 0.800839 ms.

### Failover

Runs: 2; median p99: 0.680033 ms.

## Source archive SHA-256

- Control: `50c081e4db761eebe0887b0474ce9b97157e4f87266c1903bf2ee23c60eb7bdf`
- Failover: `be27c00da7b0813ba13c337c5112d02929b2e19adb693962c4700822681f3c4f`

## Methodological limits

- Runs are sequential Docker/WSL2 observations; background CPU load and host scheduling are uncontrolled.
- Echo failures are missing application replies by deadline, not proof of physical on-wire packet loss.
- User-space RTT is not NIC hardware latency. No PTP/hardware timestamping.
- Small run counts cannot establish statistical confidence, formal significance or BGP convergence time.
- Run-level p99 medians and failure-ratio differences are descriptive, not causal evidence.

**Conclusion:** descriptively different results under two controlled lab conditions; **no causal claim, production-grade HFT claim, or physical packet-loss claim is made.**
