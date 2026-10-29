# BGP-routed TCP/UDP benchmark — Windows/Docker operator runbook

## Purpose

This experiment runs a real C++ echo server in the **Core router's Linux network namespace** (`10.40.40.1`), with an echo client in the **Edge router's Linux network namespace** (`10.10.10.1`). Traffic therefore takes the route selected by the **separate four-AS FRRouting laboratory**, unlike the standalone Docker bridge benchmark.

The script uses the already-built Docker image **`netpath-bench-lab:1.0`**. It never changes Windows routes, Linux host `sysctl`, or production routing. The optional failover test briefly stops only the named `transit_primary` service in the explicitly supplied BGP Compose project.

## Preconditions

- Docker Desktop Linux engine running, Windows PowerShell and Python 3 available.
- BGP Routing Laboratory's four FRRouting services are running and **`labctl.py check --timeout 120`** passes.
- NetPath Bench image `netpath-bench-lab:1.0` already built with `docker compose build` in its own directory.
- No other fault-injection experiment is underway.
- Project folders can be anywhere; use absolute paths. The examples below match the tested ZIP extraction layout on the operator's workstation.

## Step 1 — check the healthy four-AS lab first

From any PowerShell window:

```powershell
$lab = "C:\Users\user\Downloads\bgp-routing-laboratory-main\bgp-routing-laboratory-main"
$bench = "C:\Users\user\Downloads\netpath-bench-main\netpath-bench-main"

Set-Location $lab
py -3 scripts/labctl.py check --timeout 120

Set-Location $bench
docker image inspect netpath-bench-lab:1.0
```

If either command fails, do not run the routed experiment. The `--compose` path below points to the **BGP lab**, not NetPath Bench.

## Step 2 — read-only baseline, no fault injection

```powershell
py -3 scripts/bgp_routed_trial.py --compose "$lab\compose.yaml" --mode baseline --seconds 15 --run-id baseline01
```

Expect a summary, and three new evidence files in the ignored `reports/` folder:
`bgp-baseline-udp-baseline01.json`, `.csv`, and `-events.json`.

The trial refuses to overwrite files with identical run IDs. Use a new run ID for additional repetitions, rather than deleting evidence.

## Step 3 — deliberate primary path failure (optional)

Only after the baseline passes, **and only in this isolated lab that you control**:

```powershell
py -3 scripts/bgp_routed_trial.py --compose "$lab\compose.yaml" --mode failover --allow-primary-stop --seconds 24 --fault-at 6 --fault-seconds 5 --run-id failover01
```

The controller starts echo traffic, then stops just `transit_primary`, subsequently restores it and records event timestamps. Data-plane observations are application-level. Missing echoes do not prove physical packet loss, and Docker/PowerShell event timing is not hardware clock synchronized.

## Step 4 — independently verify restoration

```powershell
Set-Location $lab
py -3 scripts/labctl.py check --timeout 120
Set-Location $bench
```

If the script reports a failed automatic restore, stop experimenting and inspect the exact Compose project before doing any manual recovery.

## Step 5 — analyze observations (offline)

```powershell
py -3 scripts/analyze_trial.py --json .\reports\bgp-failover-udp-failover01.json --csv .\reports\bgp-failover-udp-failover01.csv --events .\reports\bgp-failover-udp-failover01-events.json --output .\reports\bgp-failover-analysis01.json
```

Do not compare Docker script durations to packet-level outage times. Retain original CSV, JSON and events and describe the actual tested conditions, before claiming any change in p99.

## Experiment status

The earlier 28 October control/fault series was independently checked against original evidence. This is the current, reproducible operator path for a new run using the updated `1.0` Docker image. **A new operator run has not yet been completed as part of this revision.**
