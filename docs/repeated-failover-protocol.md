# Repeated FRRouting Failover — Field Protocol (v0.4)

## Objective

Collect 2–5 **separate** UDP userspace echo traces while the primary FRRouting transit container is deliberately stopped and restored during each trace. Observe application echo failures and RTT tails; **do not** infer wire packet loss, hardware timestamp performance, BGP control-plane convergence, or causal effects from these alone.

A single run on October 28, 2026 was independently reviewed in v0.3; it is **not** part of the new replication series and is not counted as new evidence here.

## Prerequisites

- Docker Desktop (Linux containers) and existing isolated four-AS FRRouting lab are running.
- Python 3.10+ and the tested FRR lab `scripts/labctl.py` are available on the Windows computer.
- No other failover experiment, BGP test, or editing of the same Compose project is in progress.
- `docker compose build` has built the new `netpath-bench-lab:0.4` image; the image runs its C++ `selftest` during build.
- Do **not** run against production routers, shared infrastructure or external servers.

## What exactly happens (this is disruptive within the lab)

The command below causes **two distinct stop/start cycles** of the Compose service named `transit_primary` (three if `--runs 3` is selected). For each run:

1. Run existing `labctl.py check --timeout 120` against the supplied BGP Compose lab. This checks 8 directional neighbor perspectives, path preference, two-way sourced ICMP.
2. Launch the existing measured, opt-in `bgp_routed_trial.py` in Edge/Core namespaces. It performs a *single* deliberate primary-transit outage and restores it in a `finally` block if needed.
3. Run `labctl.py check --timeout 120` again, waiting for the *full* expected BGP and forwarding recovery before allowing the next run.
4. Bundle the **raw** client JSON, per-sequence CSV, and host event JSON into a uniquely labelled ZIP.
5. Independently audit JSON/CSV/event consistency and record exact SHA-256 of the saved ZIP and original CSV.
6. Only after all runs pass, compare **per-run** p99 RTTs and the count of runs with missing application echoes (without pooling individual probes).

If any run, pre/post health check, or integrity check fails, the series **stops**. Both the child and outer runner make a best-effort attempt to restore only `transit_primary`. If automated recovery fails, follow the manual recovery command below and verify the lab. Prior files are not overwritten.

## Exact Windows commands

Open PowerShell in the v0.4 project folder (contains `compose.yaml`).

```powershell
# Build the runtime. This verifies the C++ executable *inside* its final Alpine image.
docker compose build --no-cache

# Two opt-in controlled outages; do not run in parallel with other BGP tests.
py -3 .\scripts\repeat_failover.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --series-id trial-set-01 --runs 2 --seconds 24 --fault-at 6 --fault-seconds 5 --allow-primary-stop
```

**Use a new `--series-id` on later runs**. This prevents accidental overwriting of earlier evidence. IDs are limited to 1–24 ASCII alphanumerics, underscores or hyphens.

### Where results appear

```
reports/series-trial-set-01/
  series.json                 # progress + run-level counts + verdict
  series.md                   # human-readable, English report
  bgp-failover-udp-trial-set-01-01.json
  bgp-failover-udp-trial-set-01-01.csv
  bgp-failover-udp-trial-set-01-01-events.json
  trial-set-01-01.zip         # canonical raw evidence
  ...-02.json/.csv/-events.json
  trial-set-01-02.zip
```

The `reports` directory is `.gitignore`'d. Review evidence for personal/host information before making it public. Report `status=PASS` means the orchestration, **lab checks**, and file consistency checks succeeded; it **does not** mean zero failed application echoes.

### Emergency recovery (only the isolated lab)

```powershell
docker compose -f "..\BGP_Routing_Laboratory_v0.2\compose.yaml" up -d transit_primary
py -3 ..\BGP_Routing_Laboratory_v0.2\scripts\labctl.py check --timeout 120
```

## Benchmark controls and interpretation

- Keep one laptop, Docker configuration, probe payload (64 bytes), timeouts, inter-probe interval, background workload and FRR configuration constant between runs.
- Timeouts are *missing echoed responses by an application deadline*, not proof of NIC/wire loss.
- Capture of the `up` and `stop` events happens on the Windows side; client RTT uses C++ steady clock inside Linux/Docker. Phase boundaries should be treated as approximate.
- With a handful of runs, the median per-run p99 is a descriptive number, not a statistical confidence interval or a proof that BGP caused the single missed echo.
- For stronger scientific inference, later work should include receiver-side sequence capture, matched no-fault controls, many randomized repetitions, and more accurate time synchronization.
