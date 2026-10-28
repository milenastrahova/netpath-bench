# Controlled networking benchmark methodology

## Questions for rigorous performance engineering reviews

**Q: What does this tool actually measure?**

Application-level, sequential request/reply RTT from immediately before the client calls `send()`/`sendto()` to immediately after a matching `recv()`/`recvfrom()` completes. It includes the client and server userspace, kernel socket paths, Docker bridge/virtualization and scheduling. It does not directly report NIC-to-NIC wire latency.

**Q: Why TCP and UDP?**

TCP provides in-order reliable byte streams, with retransmission and congestion-control behaviors. UDP provides datagram semantics but application-level reliability must be designed. Comparing their echo RTT distributions under otherwise similar conditions is informative, but it does not prove one universally faster.

**Q: How is jitter calculated?**

Adjacent-successful-echo absolute RTT differences. Useful as a stability proxy, but *not* RFC 3550 one-way interarrival jitter or clock-synchronized one-way delay variation.

**Q: Does 0.5% timeout mean the network dropped 0.5% of packets?**

No. A missing reply can originate in client code, receive buffers, host scheduling, request path, response path or server logic. The denominator is application echo attempts, not all IP packets. Independent captures/counters are needed for attribution.

**Q: What does p99.9 mean on 200 samples?**

Under nearest-rank definition it is the maximum observed RTT. It is not an accurate estimate of the population's 99.9th percentile. Larger sample counts and independent repeated trials are necessary.

## Suggested field protocol

1. `docker info`: verify engine; `docker compose up -d server` and confirm healthy process.
2. Before stressing the laptop, run 200 pings with UDP, 200 with TCP, and save the *actual* JSON.
3. Repeat with 64-byte and 1200-byte messages, 1000 and 10000 attempts; use identical interval/timeout across comparisons. Label warm-up separately.
4. Record CPU pressure, host environment, virtualized network stack and actual software versions. If possible, log process CPU affinity and IRQ placement in dedicated Linux.
5. For faults, use isolated-container `tc netem` in a separately privileged *test-only* network namespace; **never** host networking or production systems. Compare baselines and after-fault.
6. Preserve original JSON, tool commit SHA, Docker image digest, test parameters and date of each run.
7. Summarize actual p50/p95/p99/p99.9, echo success ratio and sample size. Highlight that tail confidence is limited and Docker scheduling dominates some runs.
8. Describe an optimization as a hypothesis until it is verified with repeated measurements and a control group.

## What to improve next

- Windowed/pipelined UDP send and receive with explicit sender-truth sequence ledger; drops/reorder/dup validation.
- Optional SPSC queue and timestamp collection without JSON I/O on the critical path.
- Clock discipline and one-way delay only when clocks are independently calibrated and verified.
- Linux `recvmmsg` and `SO_TIMESTAMPING` feature probes; platform-specific implementations behind controlled interfaces.
- Explicit `tc netem` integration and correlated BGP failure injection; measurements in an isolated namespace only.
