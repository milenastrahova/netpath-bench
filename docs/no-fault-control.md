# No-Fault Control Experiment (v0.6)

## Question
Do failed application echo requests also appear when we do **not** intentionally stop the primary transit? Previous observations: the injected-fault series had one unsuccessful echo in each of two trials; the control series is intentionally **not** fabricated here and remains to be measured on the user's own Docker system.

## Setup
- Existing four-AS FRRouting lab (`edge`, `core`, `transit_primary`, `transit_backup`).
- `netpath-bench-lab:0.4` binary/container built from v0.6 release (version name in the image is retained to avoid altering verified C++ runtime code).
- Independent runs: 24 s, UDP, 64-byte echo payload, 20,000 µs interval, 200 ms echo timeout.
- Source `10.10.10.1` in Edge, destination `10.40.40.1` in Core.
- Docker/WSL2 and background CPU/GPU load may alter measurement jitter; note environment and run order.

## Control protocol
1. Verify the BGP baseline and ICMP connectivity with the lab's `labctl.py check`.
2. Start server bound to Core loopback and NetPath client from Edge namespace.
3. Send UDP echo probes for 24 seconds. **No BGP fault injection** is enabled or accepted.
4. Check full routing baseline again; reject the run/series if BGP health fails.
5. Bundle the original JSON, CSV and event timestamps, then independently validate every sample and the aggregate summary.
6. Run at least two controls and then compare with the verified failover summary on a per-run basis.

## Commands

```powershell
py -3 .\scripts\repeat_control.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --series-id control-set-01 --runs 2 --seconds 24 --interval-us 20000 --timeout-ms 200
```

Use a new `--series-id` for further trials; the program refuses overwrites. There is no `--allow-primary-stop` option.

The comparison input for the fault condition must be the **independent audit's** `series-review.json`, not a manually edited result. Both conditions must match protocol, duration, timeout and interval.

## Interpretation
- Missing responses are **application echo failures**, not verified physical packet loss.
- RTT values are userspace round-trip times, not hardware NIC measurements or one-way latency.
- The scripts verify route health before and after runs, not continuously during controls.
- Even if the fault trials have more unsuccessful probes, temporal association alone does not establish fault causality. Host CPU contention, Docker scheduling and software clocks are not controlled or hardware synchronized.
- With two trials per group any differences are descriptive; no statistical significance, confidence interval, or exchange/HFT performance claim is justified.

## Safety
This control experiment runs its own temporary Docker probe/server but never calls `docker stop`, `docker compose stop`, or mutates host network settings. It requires an existing isolated lab. On failure, it leaves the original BGP routers running and stores partial evidence with `status: ERROR`.
