# Portfolio evidence and technical interview guide

**Scope:** independently developed educational network laboratories; not production HFT infrastructure or a commercial trading system. Treat all measured results as laboratory observations, not SLA claims.

## Demonstration order (10–15 minutes)

1. Show FRRouting 4-AS topology and route-maps in **BGP Routing Laboratory**. Explain primary path selection (Local Preference 200 vs 100), backup route, and prefix allowlists.
2. Show **Network Operations Toolkit** logs and before/during/after snapshots. Explain why `Established` does not guarantee working forwarding.
3. Demonstrate **NetPath Bench** normal UDP/TCP echo measurement and interpretation of successful RTT percentiles. Show verified aggregate control and fault series, not invented numbers.
4. Show **Linux network diagnostics** counters and an offline comparison. Explain namespace-level limitation and how to confirm an actual physical NIC issue using packet capture and switch counters.

## Verified observations

Four controlled trials from October 2026: 2 healthy runs with 2,353/2,353 application echoes, and 2 injected primary outage runs with 2,332/2,334 echoes. This is a descriptive finding, not proof of loss caused by BGP. The run-level median p99 of successful RTT was lower in the outage runs; never claim a performance improvement from that.

## Questions a reviewer is likely to ask

- Why use Local Preference instead of an artificial latency-based route selector?
- Where would BGP RIB, kernel FIB, ACLs and MTU affect delivery?
- What changed when the primary transit container stopped? Why don't observations equal convergence time?
- What does a missing echo mean, and what other causes are possible?
- Why was the UDP client stop-and-wait instead of a concurrent load generator?
- What are the limitations of percentile estimates with two independent trials?
- How would you instrument real NIC drops, IRQ/NAPI behavior, timestamps and capture for better evidence?
- Which portions were AI-assisted, and which configurations, tests and investigations can you independently reproduce?

## Honest boundary

A strong laboratory project shows disciplined reasoning and reproducibility. It does not demonstrate 3+ years of operating production HFT connectivity, colocation hardware or exchange cross-connects. Avoid claims of measured one-way microseconds, PTP, FPGA, DPDK or hardware acceleration. Emphasize what you can independently defend.
