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

**Completed subsequently:** the three deliberate-fault trials listed in the following section. **Pending:** independent cross-condition verification of the original CSV/JSON/event evidence. This control result alone does not prove zero physical packet loss.

## Operator fault-injection series — 30 October 2026 (terminal evidence)

The operator completed three additional 24-second **deliberate primary-transit outage** runs in the same four-AS FRRouting Docker laboratory using `scripts/repeat_failover.py`, with `--fault-at 6`, `--fault-seconds 5`, `--interval-us 20000`, `--timeout-ms 200` and explicit `--allow-primary-stop`. Per-run results printed in the supplied PowerShell screenshots:

| Run | UDP attempts | Unsuccessful application echoes | Successful echoes |
| --- | ---: | ---: | ---: |
| Failover 1 | 1,169 | 1 | 1,168 |
| Failover 2 | 1,172 | 1 | 1,171 |
| Failover 3 | 1,172 | 1 | 1,171 |
| **Total** | **3,513** | **3** | **3,510** |

The script printed `VERIFIED` for all three runs and `PASS: 3 independent runs`. It checked baseline health before each fault and BGP restoration after each fault. A separate final operator `labctl.py check --timeout 120` also passed: eight eBGP neighbor perspectives Established, edge/core primary preference, and sourced two-way ICMP. Source files reside in `reports/series-fault261030005336/` on the workstation.

### Side-by-side outcomes (operator screenshots)

| Condition | Runs | Attempted UDP application echoes | Unsuccessful echoes | Observed application echo failure ratio |
| --- | ---: | ---: | ---: | ---: |
| No-fault controls | 3 | 3,535 | 0 | 0/3,535 = 0% |
| Controlled primary outages | 3 | 3,513 | 3 | 3/3,513 = **0.0854%** |

**Evidence status:** counts and command completion come from screenshots of the program. The underlying original per-probe JSON/CSV/events and series ZIP bundles are **not yet independently reviewed** for this new study; numerical RTT percentiles, timestamps, source SHA-256 and packet-level downtime remain unverified until that review. The screenshot shows three unsuccessful application echoes, not confirmed physical wire packet loss. This two-condition test was sequential (all controls before outages), so it does not prove causality or generalizable SLA behavior.

## Original evidence audit — completed

The operator supplied all **three original series archives**. All nine per-probe CSV/JSON/events triplets and nested per-run ZIP bundles passed independent source checking. Results: **7,067/7,067** control echoes, **3,510/3,513** fault echoes; source-level timeouts at sequence **294**, **295**, **297**, in the approximate primary-stop windows. Per-run mean, p50/p95/p99/p99.9/max and data-integrity checks match. [Read the complete independent audit](bgp-nine-run-source-audit-2026-10-30.md) and its [machine-readable summary](../evidence/bgp-nine-run-audit-2026-10-30.json). This supersedes earlier notes saying that the raw trial bundles had not yet been independently reviewed.

## Expected artifacts (not hypothetical results)

The completed local study uses `reports/control-ctrl261030004525/` and `reports/series-fault261030005336/`, containing original report triples, per-trial ZIPs, and series summaries. File hashes are computed by the scripts. Do not overwrite or selectively delete these files.

Both sets were executed and terminal results are documented above. An **independent full-file audit is still pending**; do not label these measurements as independently verified source-level results until original bundles have been inspected.

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
