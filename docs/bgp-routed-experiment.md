# BGP-routed application RTT experiment — operator runbook

## Goal

Transmit C++-generated UDP/TCP application traffic from the **Edge router network namespace** (source `10.10.10.1`) to a C++ echo server hosted in the **Core router network namespace** (destination `10.40.40.1`). Forwarding between those addresses depends on the FRRouting BGP lab's primary/backup route selection. Any sample interruption is an observed application-level failure; **do not call it physical-link packet loss or BGP convergence time**.

## Prerequisites

- Docker Desktop Linux engine running; BGP Laboratory v0.2 already known-good.
- `docker compose -f "..\BGP_Routing_Laboratory_v0.2\compose.yaml" ps` shows 4 running routers.
- `docker compose build` in NetPath Bench folder has produced image `netpath-bench-lab:0.2.1`.
- Check BGP baseline before/after with `py -3 "..\BGP_Routing_Laboratory_v0.2\scripts\labctl.py" check --timeout 120` (run in the directory containing the script or adapt paths).
- Stop any other BGP failure experiments. This trial changes **only** `transit_primary`, not Windows routes.
- Use a fresh output directory or move previous `reports\bgp-*` files; orchestrator refuses to overwrite raw evidence.

## Stage A: safe baseline

```powershell
py -3 .\scripts\bgp_routed_trial.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --mode baseline --seconds 15
```

Expect locally generated `reports\bgp-baseline-udp.json`, `.csv` and `-events.json`. The namespace routing integration itself is **pending verification** on the user's Docker Desktop; this is an expected workflow, not a claim that it has already passed.

## Stage B: explicitly authorized controlled failure

```powershell
py -3 .\scripts\bgp_routed_trial.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --mode failover --allow-primary-stop --seconds 24 --fault-at 6 --fault-seconds 5
```

It runs the probe, waits approximately 6 seconds, requests `docker compose stop transit_primary`, waits approximately 5 more seconds, requests `docker compose up -d transit_primary`, then gathers the probe evidence. All timings include Windows, Docker CLI and VM scheduler overhead. This script checks that all 4 BGP containers are running before it starts and always attempts recovery after a stop request.

## Stage C: independent offline interpretation

```powershell
py -3 .\scripts\analyze_trial.py --json .\reports\bgp-failover-udp.json --csv .\reports\bgp-failover-udp.csv --events .\reports\bgp-failover-udp-events.json --output .\reports\bgp-failover-analysis.json
```

The analysis groups samples by sample *start time* relative to coarse host event timestamps. Those times **cannot establish precise network interruption duration**, because client Docker clocks and orchestration Windows clocks are not calibrated for sub-ms comparison. For reliable outage-length measurements, use a continuous test in one clock domain with explicit probe timestamps and interval bounds.

## Recovery and abort

If the experiment aborts and the primary is still down:

```powershell
docker compose -f "..\BGP_Routing_Laboratory_v0.2\compose.yaml" up -d transit_primary
py -3 "..\BGP_Routing_Laboratory_v0.2\scripts\labctl.py" check --timeout 120
```

If your current directory/path differs, adjust it to the real extracted BGP lab path. A restored **container** is not proof that all eBGP sessions have converged: run `labctl check`.

## Evidence checklist

Preserve three raw files per trial (client JSON, sample CSV, orchestrator events). Record exact Docker Desktop, Windows and FRRouting versions, the fault command, BGP post-check and a checksum for each file. Do not publish raw files without reviewing internal details. Note whether any attempt status was `timeout`, `send_error` or `invalid_echo`, and report how many samples were collected per phase.
