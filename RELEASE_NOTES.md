# NetPath Bench v1.0 Release Candidate — verified condition comparison (2026-10-28)

- Introduced `scripts/audit_conditions.py`, an **offline full-source** comparison of original no-fault and failover series archives. Rechecks SHA-256, inner/outer byte identity, individual CSV samples, episode metadata, run IDs and settings; refuses unsafe or altered reports.
- Independently audited 4,687 real field UDP echo probes from four Docker/FRRouting lab runs. Control: 0 misses / 2,353; fault: 2 misses / 2,334. Two runs per condition are not enough for causal inference.
- Added reproducible comparative JSON/Markdown/SVG, validation tests, `.gitattributes` consistent checkout, versioned CMake project and Docker image tag.
- **No source raw user measurements in release package**, only validated aggregates, SHA-256 identifiers, and anonymized portable plots.
- Assistant-side Linux: 71 Python tests and both CTest cases passed; Windows v1.0 RC and hosted GitHub CI remain unconfirmed.

# NetPath Bench v0.6 — No-fault Control Series (28 October 2026)

- Adds repeatable 2–10-run FRRouting-routed UDP **control** series with no intentional container outages.
- Adds independently checked per-run JSON/CSV/event bundles and SHA-256 fingerprints.
- Adds offline `compare_conditions.py` for verified no-fault versus controlled-outage series summaries. Descriptive statistics **only**, no causality claims.
- Adds negative tests for unexpected stop events, corrupted counts, changed RTT statistics, duplicate/overwritten series, and experimental condition mismatches.
- Leaves C++ socket/measurement code and existing proven failover runner unchanged.
- New control scenario has not yet been field-executed on Windows 11; test matrix is offline synthetic only until the user runs it.
- No user raw evidence included.

# v0.5.1 — Windows/Unix path portability regression fix (2026-10-28)

- Fixed an OS-specific unit-test expectation for `docker compose -f`: the actual Compose path is preserved using native Windows or POSIX spelling. No production orchestration or C++ benchmark logic changed.
- Added a cross-platform regression test using `PureWindowsPath` and `PurePosixPath`, including paths with spaces.
- Real series evidence audit and network measurements remain from v0.5; no new live network results are claimed for this patch.

# v0.5.0 — Independent Series Evidence Audit (2026-10-28)

- Added standard-library-only `scripts/review_series.py`, independent offline checks on a full repeated-run ZIP, source-level SHA-256 checks, per-run RTT/timeout recomputation, and a multi-run SVG visualization.
- Added **12 synthetic unit tests** for tampered ZIP members, altered checksums, inconsistent series metadata, duplicate runs and output overwrite protection.
- Field-validated v0.4 repeat orchestrator: two separate runs on Windows Docker (1,168 and 1,166 UDP echo attempts); both show one application timeout; BGP baseline and post-fault recovery checks passed.
- Independently verified the actual user-supplied raw series evidence; original user ZIP and raw packet traces are deliberately excluded from this release.
- Added field series Markdown, aggregate JSON and SVG visualization with clear interpretation limits.
- Retained unchanged C++ benchmark and Docker runtime fix from previous releases.
- No claim of packet-level network loss, HFT performance, precise convergence, or root-cause proof.

# v0.4.0 — Repeatable Opt-In Failover Series (2026-10-28)

- Added `scripts/repeat_failover.py`: 2–5 sequential UDP lab trials with explicit authorization, per-run unique raw files, BGP health checks **before and after every run**, automatic evidence bundling and independent validation.
- Writes durable `series.json` and human-readable English `series.md`, with per-run packet echo counts and run-level p99; keeps previous reports intact.
- Stops series immediately on any lab, capture or integrity failure. The child and outer orchestration each attempt best-effort restoration of only `transit_primary`.
- Added synthetic offline regression tests including refusal of missing opt-in, invalid labels, overwrites, missing lab checks and failed recovery.
- Retained real 28 October field evidence and the v0.2.1 Alpine runtime dependency fix. New multi-trial runner has not yet been executed on the user's Docker Desktop. No experimental results are invented.

# v0.3.0 — Field Evidence and Repeated-run Analysis

- Added independent input validation for measured JSON/CSV/event archives (raw evidence never included in releases).
- Added trace plot (SVG), source SHA-256 hashes, markdown case study and 250ms summaries; actual field report includes the one timeout at sequence 294.
- Added `--run-id`, named-run bundle helper and independent run comparison that explicitly avoids pooling samples.
- Retained v0.2.1 fixed Alpine C++ runtime. No native Windows networking changes.
- Docker BGP fault injection still requires `--allow-primary-stop` and is not automatically invoked for tests.
- New analysis and unique-name features require Windows field validation; this release is not a claim of production HFT or wire latency.

# NetPath Bench release notes

## v0.2.1 — Docker Alpine runtime fix (2026-10-28)

- Fixed the final runtime image missing `libstdc++` and `libgcc`, which caused `Error relocating ... symbol not found` when running the C++ executable in Docker Desktop.
- Added an **unprivileged image build-time selftest** (`RUN /usr/local/bin/netpath-bench selftest`) so CI/builds fail if shared-library linking is broken.
- Added a Docker smoke job in GitHub Actions. The existing FRRouting namespace experiment has not yet been verified on Windows/Docker.
- C++ benchmark logic and measurement methodology are unchanged. Docker Desktop runtime verification remains pending on user's machine.

## v0.2.0 — Time series + routed laboratory integration (2026-10-28)

- Retains the functioning C++ TCP/UDP echo server and portable client from v0.1.
- Adds per-attempt CSV trace with sequence number, monotonic start offset, outcome, and actual RTT or `null`.
- Adds UTC run envelope and sample count to JSON, with optional duration-limited measurements.
- Adds C++ `--source-ip` and `serve --bind` for reuse in the Edge/Core FRRouting network namespaces.
- Adds opt-in `scripts/bgp_routed_trial.py` with Compose-discovered FRRouting target checks, explicit authorization for primary transit stop and best-effort restoration in a `finally` block.
- Adds offline analyzer validating JSON+CSV consistency and splitting into approximate fault phases. Explicitly documents clocks/causality limitations.
- Adds portable CTest integration and Python standard-library unit tests; expanded GitHub Actions OS/Python matrix.
- Actual local TCP/UDP loopback tests executed with GCC on Linux. Live BGP namespace trial, Docker Desktop v0.2 and hosted CI remain unverified pending user execution.

## v0.1.0

- C++17 TCP and UDP echo server and client; versioned binary frame, nearest-rank RTT statistics, JSON reports, Docker Compose; local loopback integration tests.
