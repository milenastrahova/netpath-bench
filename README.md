# NetPath Bench — TCP/UDP Latency and Network Resilience Lab

**v1.0 release candidate · C++17 · CMake · TCP/UDP · Docker Desktop · FRRouting namespace integration · Python offline analysis**

> **Independent educational networking lab, not commercial infrastructure operations.** All numbers originate from actual executions. A user-space echo RTT is not one-way wire latency, and a missing UDP echo is not proof of on-wire packet loss. No unverified production-network benchmarks are claimed.

## v1.0 release candidate — original-data audit of no-fault and injected-outage conditions

**Latest independently checked field results (28 October 2026):** two no-fault control runs (2,353/2,353 application echo replies) and two injected-primary-outage runs (2,332/2,334 replies). Parameters match: UDP, 24 seconds, 20 ms send interval, 200 ms timeout, 64-byte payload, Edge-to-Core FRRouting namespace path. Run-level median p99 of **successful** RTT: 0.800839 ms control versus 0.680034 ms injected fault. The fault group has two missing echoes and a lower successful-RTT p99; neither proves precise convergence, physical packet loss, performance improvement or causality.

**Source audit:** `scripts/audit_conditions.py` reads both **original** user series ZIPs, verifies nested bundles and SHA-256 references against loose raw CSV/JSON/events, reconstructs the per-sample statistics, and writes a portable public aggregate report. Raw field data stays outside version control.

```powershell
py -3 .\scripts\audit_conditions.py --control-zip "..\NetPath_Bench_CPP_v0.6\NetPath_Control_Evidence.zip" --failover-zip "..\NetPath_Bench_CPP_v0.4\NetPath_Series_Evidence.zip" --output-dir .\reports\conditions-original
py -3 -m unittest discover -s tests -p "test_*.py" -v
docker compose build
```

The ZIP paths are examples; point them to the locations of your own evidence archives. The audit runs **offline**, never stops routers, and refuses to overwrite an existing report folder. See [verified comparison](docs/verified-conditions-2026-10-28.md) and [release quality gates](docs/validation-v1.0.md). The release candidate still requires **Windows test acceptance and GitHub-hosted CI** before being called a fully validated v1.0 release.

## Engineering objective

NetPath Bench is designed to answer measurable questions about latency-sensitive networking:

1. How do TCP and UDP application **echo RTT distributions**, including tail percentiles, change between repeated runs?
2. Which individual sequence numbers fail to receive matching echoes, and *when* did they occur?
3. Does a laboratory BGP path switchover coincide with changes in the **application-level** RTT/echo time series?
4. What can and cannot be inferred from those observations under Windows 11 + Docker Desktop + WSL2?

The project does **not** claim nanosecond timing, production-network performance, loss localization, one-way delay, or hardware timestamping.

## Components

| Component | Implementation | Status |
| --- | --- | --- |
| TCP/UDP echo server | C++17, versioned 28-byte network-order framing, session + sequence | Built / loopback tested |
| RTT probe client | Persistent TCP or sequential UDP, monotonic sample timings | Built / loopback tested |
| Summary statistics | p50, p95, p99, p99.9, min, mean, max, adjacent successful-RTT difference | Built / unit tested |
| Per-attempt evidence | CSV sequence, start offset, `ok`/`timeout`/error status and RTT | Built / loopback tested |
| Controlled run length | `--duration-sec` or `--count` | Built / loopback tested |
| Linux namespace binding | `--source-ip`, `serve --bind`, Docker `--network container:...` | Code tested; BGP Docker path field-tested (Oct 2026) |
| BGP-routed trial | Python orchestrator with opt-in primary stop, try/finally restoration | Validated in the v0.2.1 Windows lab; v0.4 repeat-run trial verified with two real runs |
| Offline phase analysis | Validate JSON+CSV, approximate before/stop/after summaries | Built / offline tested |
| GitHub Actions | Ubuntu/Windows + Python 3.10/3.13 matrix | Defined; remote CI **pending** |

## Windows 11: first local benchmark (no Windows networking changes)

Prerequisite: Docker Desktop running with Linux containers. Open PowerShell in the unzipped folder containing `compose.yaml`.

**Docker runtime repair retained from v0.2.1:** This release installs the Alpine C++ runtime (`libstdc++` and `libgcc`) and runs the unprivileged executable during `docker compose build`. If you previously built v0.2, use the new separate v1.0 RC folder and `docker compose build --no-cache` to make sure the fixed image is used.

```powershell
# Build the C++17 executable *inside* Docker. No Windows compiler required.
docker compose build --no-cache
# Start isolated echo server. No host ports are published.
docker compose up -d server
# C++ self-check; independent of the server.
docker compose run --rm bench selftest
# UDP and TCP real probes, save raw per-probe CSV + JSON evidence.
docker compose run --rm bench udp --host server --count 500 --bytes 64 --timeout-ms 250 --interval-us 1000 --json /reports/udp.json --csv /reports/udp.csv
docker compose run --rm bench tcp --host server --count 500 --bytes 64 --timeout-ms 250 --interval-us 1000 --json /reports/tcp.json --csv /reports/tcp.csv
# Produce an independently calculated summary from raw outputs.
py -3 .\scripts\analyze_trial.py --json .\reports\udp.json --csv .\reports\udp.csv --output .\reports\udp-analysis.json
```

**Location of evidence:** `reports\udp.json`, `reports\udp.csv`, `reports\tcp.json`, `reports\tcp.csv`, `reports\udp-analysis.json` on your Windows disk. These files are ignored by Git. A probe returning exit code `2` signals one or more failed application echoes or unexpected replies: inspect the saved reports; do not delete those observations.

To stop **only** NetPath Bench's self-contained service (not the BGP lab):

```powershell
docker compose down
```

## Route real traffic through your FRRouting lab

The existing four-AS BGP laboratory has `edge` loopback `10.10.10.1/32` and `core` loopback `10.40.40.1/32`; BGP chooses primary/backup transit paths. A container joined to another container's network namespace can use its loopback addresses and routes **without adding routes to Windows**.

The optional orchestrator discovers the four FRRouting containers from the supplied Compose file, then places the NetPath Bench **server in the core namespace** and the **client in the edge namespace**, binds source `10.10.10.1`, targets `10.40.40.1`, saves packet-by-packet evidence, and cleans up its own containers.

First build the image with `docker compose build` (above), then run a harmless baseline:

```powershell
py -3 .\scripts\bgp_routed_trial.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --mode baseline --seconds 15
```

**Optional controlled failure** (stops and restarts only the BGP lab's `transit_primary` service; do **not** run concurrently with any other lab experiment):

```powershell
py -3 .\scripts\bgp_routed_trial.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --mode failover --allow-primary-stop --seconds 24 --fault-at 6 --fault-seconds 5
```

Then review the real CSV/JSON trial and metadata:

```powershell
py -3 .\scripts\analyze_trial.py --json .\reports\bgp-failover-udp.json --csv .\reports\bgp-failover-udp.csv --events .\reports\bgp-failover-udp-events.json --output .\reports\bgp-failover-analysis.json
```

**Note:** `CAPTURED` means valid reports were saved. It does **not** assert zero network outages. The analysis correlates wall-clock timestamps only approximately: client timestamps in a Docker/Linux VM and orchestrator timestamps on Windows are not PTP synchronized. See [BGP runbook](docs/bgp-routed-experiment.md) for preflight/restore instructions.

## Build and test directly (Linux)

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
ctest --test-dir build --output-on-failure
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The unit test checks frame encoding / quantiles / CSV. The real loopback integration test sends **32 UDP echoes and 32 TCP echoes**, verifies actual JSON and CSV, runs a duration-limited UDP trial, and checks a real missing-echo scenario. Python tests check fail-safe orchestration and reject invalid analysis evidence.

`Windows native C++` builds are intended in the GitHub Actions matrix but were not locally validated in this release; Docker is the recommended Windows execution mode.

## Wire protocol and metric semantics

- **TCP:** a persistent stream carries complete frames (28-byte header + payload); echo RTT excludes connection establishment.
- **UDP:** stop-and-wait, one datagram and one matching echoed datagram at a time; this is **not** a UDP load generator or a reliable measure of reordering under concurrency.
- Version 1 header (network byte order): `magic` (4 bytes), `version` (2), `flags` (2), `session` (8), `seq` (4), `frame size` (4), `reserved` (4). Only a correct session+sequence+length counts as an echo; UDP additionally checks remote IP and port.
- **Monotonic clocks:** all RTTs use `std::chrono::steady_clock` in one process. CSV `start_offset_ms` is relative to the run start; JSON UTC start/end are wall-clock orientation, not hardware timestamps.
- **p99.9:** uses nearest rank over *successful replies only*. With small samples it may equal the maximum and is not statistically stable.
- **Echo failures:** errors/timeouts/unexpected replies reflect application observation, not exclusively physical packet drops or one-way latency.
- **No production latency assertions:** no dedicated NIC, hardware time sync, PTP, DPDK or kernel bypass was tested.

See [metrics methodology](docs/metrics-and-limitations.md), [BGP routed experiment](docs/bgp-routed-experiment.md) and [design review](docs/design-review.md).

## Security boundaries

- No host ports are published by Compose. The standalone self-contained benchmark uses an `internal: true` network.
- The BGP trial joins existing **container** namespaces, without Windows adapter, routing table, registry or firewall changes.
- The trial refuses to stop any container until `--mode failover --allow-primary-stop` is explicitly provided. On errors it tries to restore `transit_primary` and stops only its own experiment containers. The emergency manual recovery is in the runbook.
- **Do not** run external Internet scans or point the echo server at third-party production systems. This is a lab service not secured for Internet exposure.
- Raw measurements may contain machine/route information; review before publication.

## Release validation status

- **Verified locally in the assistant's Linux environment:** GCC C++17 compilation, CTest selftest and actual TCP/UDP loopback integration, Python offline tests, independent offline summary on actual loopback data. This is not user hardware benchmarking.
- **Validated by the user in v0.2.1:** Docker on Windows 11, a 500-probe TCP echo run, a 500-probe UDP echo run, FRR-routed UDP baseline (736/736 successful) and one FRR-routed 24-second controlled failover (1165/1166 successful echoes). **Repeated run and control orchestrators field-tested through v0.6:** two injected-outage and two no-fault trials; all original series files later independently audited. Hosted GitHub CI and native MSVC compilation of the latest release candidate are still pending.
- **Next independent capability, not asserted by v1.0:** packet capture and receiver-side UDP sequence/loss/reordering under concurrent traffic; hardware/NIC performance requires other infrastructure.

MIT license. Engineering portfolio project, developed and described as an educational laboratory.

## v0.3 — reproducible field evidence review and repeatable run identity

A verified **single real field trial** collected on Windows 11 on 28 October 2026 is documented in [field report](docs/field-report-2026-10-28.md), [source SHA-256 summary](docs/field-evidence-summary-2026-10-28.json) and [per-probe timeline](docs/field-timeline.svg). It included 1,166 attempts, 1,165 successful echoes and one `timeout` at sequence 294, approximately 168 ms after the recorded Windows stop request. This is **temporal association**, not proof of packet loss caused by BGP. **Raw evidence is intentionally excluded** from the public ZIP.

New **stdlib-only** analysis features:

- `scripts/review_evidence.py`: accepts a ZIP of original JSON, CSV and Windows event file; rejects inconsistent counts, timestamps, unexpected schema, duplicate ZIP entries and malicious paths; writes independent JSON, Markdown and SVG evidence.
- `scripts/bgp_routed_trial.py --run-id run02`: uniquely names raw results, avoiding overwrite. It **never injects failure without** `--mode failover --allow-primary-stop`.
- `scripts/bundle_trial.py`: safely creates a canonical-named ZIP from any labelled failover run.
- `scripts/compare_runs.py`: compares 2–50 **unique** runs without improperly pooling individual samples.

Review existing evidence (put `NetPath_Failover_Evidence.zip` beside the README):

```powershell
py -3 .\scripts\review_evidence.py --evidence-zip .\NetPath_Failover_Evidence.zip --output-dir .\reports\review-original
```

For the safe repeated-run procedure, see [evidence workflow](docs/field-review-usage.md). The v0.3 analysis pipeline was offline-tested on the user's genuine v0.2.1 data and on synthetic test fixtures; new Docker trial orchestration is **not yet field-verified**.

## v0.4 — opt-in, repeatable failover acceptance experiment

The v0.3 evidence analyzer has now been **validated on the user's original ZIP on Windows 11** (`PASS: raw sample and event consistency verified`, producing JSON/Markdown/SVG reports). This is not evidence of a new v0.4 lab run.

Version 0.4 adds `scripts/repeat_failover.py` and offline synthetic safety tests. It runs **two to five independently labelled failover experiments** with a `labctl.py` baseline/restore check around **every** outage, automatically bundles each raw trace, rejects inconsistent files, and writes a run-level comparison without pooling samples. This script is not yet field-verified on Windows; its tests never stop real containers.

**This command deliberately stops the primary BGP laboratory transit twice.** Only run it in your own isolated Docker lab. It requires the explicit `--allow-primary-stop` opt-in:

```powershell
docker compose build --no-cache
py -3 .\scripts\repeat_failover.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --series-id trial-set-01 --runs 2 --seconds 24 --fault-at 6 --fault-seconds 5 --allow-primary-stop
```

The results are saved in `reports/series-trial-set-01/` (`series.json`, `series.md`, per-run ZIP/JSON/CSV/events). See [replication runbook](docs/repeated-failover-protocol.md) for failure and recovery instructions. Raw user evidence is **not** bundled in the source release.

## v0.5 — evidence-first comparison of independent field trials

**Field-verified on Windows 11:** v0.4 repeated-failover runner completed **two** independent controlled lab experiments. The original series ZIP was independently rechecked: 1,168/1,166 UDP echo attempts, one missed echo in each trial, both post-fault FRR recovery checks passed. This only shows application echo responses during a lab experiment, not BGP convergence duration or physical network loss.

Version 0.5 adds **offline** `scripts/review_series.py`. It accepts the Windows `Compress-Archive` ZIP of a completed `series-<id>` directory and checks:

- all per-run source JSON/CSV/event evidence and their original nested bundles byte-for-byte;
- SHA-256 of bundles and CSV, duplicate run detection, unique and safe archive names;
- per-run probe counts, sample integrity, p99, comparison manifest, approximate UTC phases and event ordering;
- rejects modified/corrupt/extra entries and contradictory run-level statistics;
- writes a JSON review, English Markdown report and one SVG plot for all runs, without publishing raw user traces.

Run from PowerShell in the extracted project folder (no Docker needed):

```powershell
py -3 -m unittest discover -s tests -p "test_*.py" -v
py -3 .\scripts\review_series.py --series-zip "..\NetPath_Bench_CPP_v0.4\NetPath_Series_Evidence.zip" --output-dir ".\reports\review-trial-set-01"
```

The archive name/path above is only an example; supply the actual location of your saved evidence ZIP. The output directory must not already exist. Source ZIP stays unchanged. No BGP router is stopped.

Verified field artifacts (non-raw): [series report](docs/field-series-report-2026-10-28.md), [independently recomputed JSON](docs/field-series-verified-summary-2026-10-28.json), [two-run timeline](docs/field-series-timeline.svg).

**Not yet claimed:** native Windows Docker trial of v0.5 (the new code is offline-only), GitHub-hosted CI, receiver-side verified packet loss, hardware NIC RTT, or production use.


## v0.6 — independent no-fault control series (new)

The previously captured two **injected-outage** field runs are not sufficient to infer
that BGP failover caused a missing echo. The next step is to gather comparable runs
without intentionally changing the routing topology. `scripts/repeat_control.py`
performs this **non-faulting** control experiment using the same two router namespaces,
packet size, duration, timeout and probe interval. It performs a `labctl check` before
and after *each* run, writes unique JSON/CSV/event artifacts, validates them with an
independent read-only parser, and rejects incomplete or inconsistent results.

### Windows 11 / Docker Desktop: collect two control runs

Open PowerShell in the extracted **NetPath_Bench_CPP_v0.6** folder. Ensure the existing
FRRouting lab is already running and the NetPath Bench Docker image is built:

```powershell
# Doesn't change routes or stop any container.
docker compose build
py -3 .\scripts\repeat_control.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --series-id control-set-01 --runs 2 --seconds 24 --interval-us 20000 --timeout-ms 200
```

Expected outputs are in `reports/control-control-set-01/`:
`control-series.json`, `control-series.md`, and one immutable `.zip` for each run,
plus original per-run JSON/CSV/events. The script **does not take**
`--allow-primary-stop` and never calls `docker compose stop`.

When the control run completes, compare its reports descriptively with the earlier
validated injected-fault series-review.json:

```powershell
py -3 .\scripts\compare_conditions.py --control .\reports\control-control-set-01\control-series.json --failover "..\NetPath_Bench_CPP_v0.5\reports\review-trial-set-01\series-review.json" --output .\reports\condition-comparison.json --markdown .\reports\condition-comparison.md
```

If the `series-review.json` is still in the v0.5 folder, change only the
`--failover` path accordingly. The comparison **requires matching probe settings**;
it refuses invalid or nonverified inputs. The comparison is not a causal experiment
because Docker scheduling, CPU utilization and clock synchronization remain uncontrolled.

See [no-fault control methodology](docs/no-fault-control.md). Historical data and
screenshots are not embedded in this source archive.

## v1.0 evidence acceptance status (28 October 2026)

The v0.6 no-fault control collector was field-tested on Windows 11 with two BGP-routed UDP samplesets: **1175/1175** and **1178/1178** successful application echoes, with routing checks before and after each run. The same FRRouting lab previously produced two opt-in primary-fault runs: **1167/1168** and **1165/1166** echoes. Independent auditing of original files confirmed the four results and consistency of experimental settings. See `docs/verified-conditions-2026-10-28.md`.

The new v1.0 RC comparison audit is validated in the assistant-side Linux environment, but **requires a final Windows run and GitHub Actions acceptance** before claiming that the complete v1.0 workflow is cross-platform validated.
