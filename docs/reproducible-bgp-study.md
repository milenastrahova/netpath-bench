# Reproducible routed-network validation study — operator protocol

**Target:** independent, repeatable measurements of userspace UDP echo behavior over a live four-AS FRRouting Docker laboratory. The outcome can be healthy or contain missing echoes; **neither result should be selected, edited or discarded to make the project look better**. The benchmark does not prove physical-link latency, NIC tuning, wire loss, or protocol convergence duration.

## Existing code and evidence

- The benchmark image is `netpath-bench-lab:1.0` (current Docker Compose; current GitHub orchestrator uses the same version).
- `scripts/bgp_routed_trial.py` runs one bounded baseline/failover over **edge** and **core** namespaces.
- `scripts/repeat_control.py` checks BGP health before and after each baseline run, validates each run's original JSON/CSV/events, and retains source bundles.
- `scripts/repeat_failover.py` requires explicit `--allow-primary-stop`, checks BGP health before and after each run and attempts restoration of `transit_primary`. It retains individual reports and refuses to overwrite prior series.
- `scripts/audit_conditions.py` compares reviewed source archives and explicitly reports measurement limitations.
- The earlier two-control/two-fault experiments remain an **independent earlier data set**, not part of this new study.

## Baseline preflight (safe, read-only)

In Windows PowerShell, using the same local paths as the verified operator machine:

```powershell
$lab = 'C:\Users\user\Downloads\bgp-routing-laboratory-main\bgp-routing-laboratory-main'
$bench = 'C:\Users\user\Downloads\netpath-bench-main\netpath-bench-main'
Set-Location $lab
py -3 scripts/labctl.py check --timeout 120
Set-Location $bench
docker image inspect netpath-bench-lab:1.0 --format '{{.Id}}'
```

Stop if any assertion fails. Download the newest project ZIP from GitHub into **a separate folder** rather than overwriting the `reports/` folder. Previously downloaded ZIP versions may still have `IMAGE = "netpath-bench-lab:0.4"` in the Python trial script; the latest GitHub revision uses `1.0`. Local scripts must match the latest source before running a study.

## Stage A — one BGP-routed pilot without failover

```powershell
py -3 scripts/bgp_routed_trial.py --compose "$lab\compose.yaml" --mode baseline --seconds 15 --run-id pilot1030
```

Confirm that a client on `10.10.10.1` reached a server on `10.40.40.1` and that three files appeared under `reports/`. Failure at this stage is an investigation result; do not inject faults until the pilot is understood.

## Stage B — independent repeated measurements

**Only if the pilot passed.** These are separate series with non-overwritten output folders. The default is **3 controls plus 3 deliberately injected faults**, the same 64-byte payload, 24-second run, 20-ms issue interval and 200-ms application timeout. For any rerun, choose a new alphanumeric series ID.

```powershell
py -3 scripts/repeat_control.py --compose "$lab\compose.yaml" --series-id hft1030ctl --runs 3 --seconds 24 --interval-us 20000 --timeout-ms 200
```

Examine each run. To run the optional deliberate faults, the operator must understand that the next command stops **only** the named `transit_primary` container in this specific isolated FRRouting Docker project, and then attempts to restore it. Never use against shared or production networks.

```powershell
py -3 scripts/repeat_failover.py --compose "$lab\compose.yaml" --series-id hft1030fau --runs 3 --seconds 24 --fault-at 6 --fault-seconds 5 --interval-us 20000 --timeout-ms 200 --allow-primary-stop
```

After the fault series:

```powershell
Set-Location $lab
py -3 scripts/labctl.py check --timeout 120
Set-Location $bench
```

If the fault script or a recovery check fails, **stop further injections**. Preserve the incomplete evidence and diagnose the lab before continuing. Do not count the absence of errors in the control plane as proof of continuous application availability.

## Operator control series — 30 October 2026 (terminal evidence)

The operator completed the **no-fault control** half of the proposed study on Windows 11 / Docker Desktop using `scripts/repeat_control.py` with **three 24-second runs**, `--interval-us 20000`, `--timeout-ms 200`, and the isolated four-AS BGP lab. The screenshots of the script's console output confirm:

| Run | Application echo replies | Unsuccessful echoes |
| --- | ---: | ---: |
| Control 1 | 1,179 / 1,179 | 0 |
| Control 2 | 1,178 / 1,178 | 0 |
| Control 3 | 1,178 / 1,178 | 0 |
| **Total** | **3,535 / 3,535** | **0** |

The controller printed BGP healthy checks **before and after every run**, a verified report bundle for each run, and `PASS: 3 no-fault runs, verified original sample files`. The saved local series directory is `reports/control-ctrl261030004525/` on the operator's workstation. The original per-probe ZIP/JSON/CSV evidence and p99 values were **not independently supplied for this entry**; no numerical p99 or source SHA-256 is claimed on the basis of this screenshot alone.

**Pending:** matched deliberate-fault trials and independent cross-condition inspection of the source evidence. A healthy 3/3 control series is a useful baseline, not proof of failover performance or physical-network zero-loss operation.

## Expected artifacts (not hypothetical results)

When completed, `reports/control-hft1030ctl/` and `reports/series-hft1030fau/` contain original report triples, per-trial ZIPs, and series summaries. File hashes are computed by the scripts. Do not overwrite or selectively delete these files.

An actual result is recorded **only after the operator executes these commands and the source reports have been reviewed**. The planned test is not completed merely because CI passes on the scripts.

## Reporting contract

Include **all** completed runs, not only the fastest. Per condition, report:
- Trial count, attempted echo requests, successes, timeouts, invalid replies and application-level failure ratio.
- Distribution of successful RTT: p50/p95/p99/p99.9, maximum, and **run-level** median p99.
- Exact settings and sequence sample count; original source SHA-256, operating system/Docker/FRRouting image versions and image digest if available.
- Whether the primary was deliberately stopped and **separately verified to recover**.
- Uncontrolled load / time order and approximate Windows-Docker event timestamps.

Explicitly label each result as **userspace application RTT in a virtual Docker routing network**. Two sets of different successful-response percentiles cannot by themselves establish an improvement or causal performance effect. A missed application reply is not proof of wire packet loss or exact BGP convergence time.

## Follow-up limitations and improvements

This 3+3 study is a **first new replication**. Controls precede failures, so order/time and CPU/host load can confound comparisons. A later controlled study should interleave conditions when safe, add matched traffic-load logging, track CPU/IRQ/softnet counters and validate NIC-level claims using actual NIC and timestamping equipment. Do not retrofit those claims into existing Docker data.
