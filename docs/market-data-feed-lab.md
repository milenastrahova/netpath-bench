# Market Data Feed Continuity Lab (synthetic UDP)

An educational market-data-like UDP sequence tracker. There is **no real exchange connection**, no FIX/FAST protocol, and no demonstrated production multicast performance.

## What it actually does

- Defines a simple original 16-byte datagram header: ASCII `MDL1`, 32-bit stream ID, 64-bit sequence number; network byte order.
- Tracks unobserved sequence gaps, late recovery, duplicate packets, and out-of-order sequence numbers separately per stream.
- Uses bounded recent-history and pending-gap sets to avoid unbounded memory on large sequence discontinuities.
- Validates malformed/oversized datagrams and explicitly distinguishes application observations from physical packet loss.
- Has a real UDP loopback end-to-end demonstration; a separate opt-in local IPv4 multicast subscription is available for a user-provided group.

## Reproducible demo

From the repository root:

```bash
python scripts/market_data_feed_lab.py demo --count 80 --output reports/synthetic-feed.json
python -m unittest discover -s tests -p 'test_*.py' -v
```

The demo exercises real operating-system UDP sockets on `127.0.0.1`. It deliberately omits sequence 7 on first pass, later delivers it, and duplicates sequence 18. Expected within an un-congested loopback test: `gaps_recovered=1`, `duplicates=1`, `pending=0`. A failed or congested host may legitimately produce incomplete data; the tool returns `completed=false` rather than fabricating a PASS.

## Optional multicast mode

Use only on a network where you are authorized to subscribe. The listener does not generate multicast traffic:

```bash
python scripts/market_data_feed_lab.py listen --group 239.255.42.42 --port 19371 --duration 5 --stream-id 1 --output reports/multicast.json
```

Whether membership succeeds depends on OS/WSL2/Docker networking and interface configuration. No multicast end-to-end production validation is claimed.

## Interview discussion

1. Why does missing sequence 7 **not** prove that a physical NIC dropped a packet?
2. Why might the market-data application pause, request retransmission, or reset its session if a gap is detected?
3. How are out-of-order messages different from permanent gaps?
4. Why is network multicast (IGMP/PIM/SSM) distinct from the application-level sequence tracker?
5. How would you instrument hardware NIC counters, user-space queues, kernel drops, timestamps, and both ends of the channel?

### Verification and limitations

Nine local unit tests passed, including real loopback UDP, before publication. GitHub Actions independently runs the project's Python unit tests. This module is an additional educational feature of NetPath Bench; it is not a full multicast market data receiver or recovery protocol.
