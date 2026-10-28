# Engineering design review — NetPath Bench v0.2.1

1. **What exactly is being measured?** An application echo RTT between `steady_clock` sample points in one C++ process, not network-only or hardware one-way latency.
2. **Why UDP as well as TCP?** UDP preserves datagram semantics without TCP retransmission/head-of-line effects, but UDP missing echoes do not tell us which direction or device failed. TCP returns reliable byte streams, so the protocol needs explicit framing.
3. **How is response attribution enforced?** Protocol header magic/version/session/sequence/length; UDP also checks the peer IP/port. Unmatched packets increment an explicit counter.
4. **How is p99 calculated?** Nearest-rank quantile on successful RTT measurements. This is sample-dependent; always include N and a repeatable load/topology.
5. **Why not claim 0.5 ms failover from a CLI poll?** Poll timing includes command dispatch and scheduler effects; no packet-level outage or BGP finite-state convergence interval was measured.
6. **Can we prove BGP path dependency?** The Edge source `10.10.10.1` and Core target `10.40.40.1` are advertised in the FRR lab; a correctly installed route in each namespace should forward probe traffic via a transit AS. Verify with FRR route tables and controlled packet captures before claiming it in results.
7. **Could a probe timeout originate elsewhere?** Yes: user-space process stalls, virtual NIC queues, responder overload, either packet direction, or socket buffers. This experiment cannot localize missing traffic.
8. **What happens when primary is lost?** If routing policies and BGP sessions permit, the lab should select the backup next hop. The trial tests whether application echoes continue or are briefly missed; this does not isolate cause without additional visibility.
9. **Why record every attempted sequence?** It makes the failure time series auditable, permits independent checks against summary counts, and avoids hiding bursty outages under a mean.
10. **Why do timing phases use approximate UTC?** Windows orchestrates container stop/start while C++ runs in a Linux VM; those clocks lack common PTP-grade calibration. Use precise monotonic timing within a single domain for outage bounds.
11. **Is the server production hardened?** No. It is isolated by design, has no published host ports, and is not intended for untrusted networks; denial-of-service and resource exhaustion protections are not complete.
12. **How would you make this more realistic for low-latency networking?** Physically controlled cross-connects, hardware timestamping, NIC queue/interrupt and CPU-affinity tuning, PTP, multicast market-feed simulation, pcap reconciliation, load/temperature controls, and repeated controlled trials with confidence intervals.
