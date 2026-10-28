#!/usr/bin/env python3
"""Reproducible, opt-in FRRouting failover replication (UDP application echoes).

Each run is an independent trial, with a clean labctl baseline/recovery check.
Fails closed on any run or evidence error. No Windows networking changes.
No BGP fault is injected unless --allow-primary-stop was explicitly supplied.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.bundle_trial import bundle
from scripts.compare_runs import compare
from scripts.review_evidence import read_evidence_zip, build_review


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def validate_series_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,23}", value):
        raise ValueError("--series-id must use 1-24 ASCII alphanumeric, '_' or '-' characters")
    return value


def run_command(argv: list[str], *, timeout: int) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {argv[0:3]}\n"
                           f"stdout: {result.stdout[-1600:]}\nstderr: {result.stderr[-1600:]}")
    return result.stdout


def validate_inputs(series_id: str, runs: int, seconds: int, fault_at: int,
                    fault_seconds: int, timeout_ms: int, interval_us: int) -> None:
    validate_series_id(series_id)
    if not 2 <= runs <= 5:
        raise ValueError("--runs must be between 2 and 5")
    if not 8 <= seconds <= 180:
        raise ValueError("--seconds must be 8..180")
    if not 1 <= fault_at < seconds:
        raise ValueError("--fault-at must occur during the trial")
    if not 1 <= fault_seconds < seconds - fault_at - 2:
        raise ValueError("--fault-seconds must leave >=3 seconds after recovery")
    if not 1 <= timeout_ms <= 60000 or not 0 <= interval_us <= 10_000_000:
        raise ValueError("invalid timeout or interval")


def write_json(path: Path, content: dict) -> None:
    """Update the local run journal; writes remain outside version control."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def markdown_report(data: dict) -> str:
    runs = data["runs"]
    lines = ["# NetPath Bench — Repeated BGP Failover Trials", "",
             f"Series: `{data['series_id']}` | status: **{data['status']}** | independent runs: {len(runs)}", "",
             "| Run | Application echo attempts | Missing/invalid echoes | Echo failure ratio | p99 RTT (ms) |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for x in runs:
        lines.append(f"| `{x['run_id']}` | {x['attempts']} | {x['missing_echoes']} | "
                     f"{x['failure_ratio']:.6f} | {x['p99_rtt_ms']:.6f} |")
    if data.get("comparison"):
        cmp = data["comparison"]
        lines.extend(["", f"Median of **run-level** p99 RTT values: {cmp['run_level_median_p99_ms']:.6f} ms",
                      f"Runs with one or more unsuccessful echoes: {cmp['runs_with_missing_echoes']} / {cmp['run_count']}"])
    lines += ["", "## Methodology and limits", "",
              "- These are consecutive, separately captured runs on the **same Docker/FRRouting lab**.",
              "- Each run verifies baseline route health and post-experiment route restoration before advancing.",
              "- p99 is computed over successful **userspace application echo RTT**, not NIC wire latency.",
              "- Unsuccessful application echoes are not confirmed network packet loss.",
              "- Run-level medians do not provide a confidence interval or establish causality.",
              "- Event windows are approximate due to Docker, Windows, and unsynchronized clocks.",
              "- Failure injection stopped only `transit_primary`, after explicit user opt-in.",
              "- Raw reports/bundles stay in the local reports directory, not in the GitHub release.", ""]
    if data.get("error"):
        lines.extend(["## Unfinished series", "", f"Stopped safely: `{data['error']}`", ""])
    return "\n".join(lines)


def execute_series(*, compose: Path, series_id: str, runs: int, seconds: int,
                   fault_at: int, fault_seconds: int, interval_us: int, timeout_ms: int,
                   reports_root: Path, allow_primary_stop: bool,
                   runner: Callable[..., str] = run_command) -> dict:
    """Execute serial trials; never retry a failed fault injection implicitly."""
    validate_inputs(series_id, runs, seconds, fault_at, fault_seconds, timeout_ms, interval_us)
    if not allow_primary_stop:
        raise ValueError("Explicit --allow-primary-stop required for repeated failover trials")
    compose = compose.resolve(strict=True)
    labctl = compose.parent / "scripts" / "labctl.py"
    if not labctl.is_file():
        raise ValueError("Expected labctl.py beside the supplied BGP Compose project")
    series_dir = (reports_root / f"series-{series_id}").resolve()
    if series_dir.exists():
        raise FileExistsError("Series folder already exists; use a new --series-id to preserve evidence")
    series_dir.mkdir(parents=True)
    journal = {"schema_version": 1, "series_id": series_id, "status": "IN_PROGRESS",
               "created_utc": utc_now(), "planned_runs": runs, "runs": [],
               "settings": {"protocol": "udp", "seconds": seconds,
                            "fault_at": fault_at, "fault_seconds": fault_seconds,
                            "timeout_ms": timeout_ms, "interval_us": interval_us},
               "limitations": "Userspace echo RTT. Timeout is not verified wire packet loss. UTC event correlation is approximate.",
               "comparison": None}
    manifest = series_dir / "series.json"
    write_json(manifest, journal)
    bundles = []
    started = False
    try:
        for index in range(1, runs+1):
            run_id = f"{series_id}-{index:02d}"
            print(f"[RUN {index}/{runs}] Checking healthy BGP baseline", flush=True)
            runner([sys.executable, str(labctl), "check", "--timeout", "120"], timeout=180)
            # Existing trial orchestrator's own preflight and try/finally are additional guards.
            cmd = [sys.executable, str(ROOT / "scripts" / "bgp_routed_trial.py"),
                   "--compose", str(compose), "--mode", "failover", "--allow-primary-stop",
                   "--protocol", "udp", "--run-id", run_id, "--seconds", str(seconds),
                   "--fault-at", str(fault_at), "--fault-seconds", str(fault_seconds),
                   "--interval-us", str(interval_us), "--timeout-ms", str(timeout_ms),
                   "--reports", str(series_dir)]
            started = True
            print(f"[RUN {index}/{runs}] Sending UDP probes with one controlled primary outage", flush=True)
            runner(cmd, timeout=seconds+200)
            print(f"[RUN {index}/{runs}] Verifying full BGP recovery", flush=True)
            runner([sys.executable, str(labctl), "check", "--timeout", "120"], timeout=180)
            zip_path = series_dir / f"{run_id}.zip"
            bundle(series_dir, run_id, zip_path)
            review,_ = build_review(read_evidence_zip(zip_path))
            row = {"run_id": run_id, "bundle": zip_path.name,
                   "bundle_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
                   "attempts": review["counts"]["attempted"],
                   "missing_echoes": review["counts"]["missing_or_invalid_echoes"],
                   "failure_ratio": review["counts"]["application_echo_failure_ratio"],
                   "p99_rtt_ms": review["rtt_ms"]["p99"],
                   "raw_csv_sha256": review["evidence_sha256"]["bgp-failover-udp.csv"],
                   "validation": "PASS"}
            journal["runs"].append(row)
            write_json(manifest,journal)
            bundles.append(zip_path)
            print(f"[RUN {index}/{runs}] VERIFIED; {row['attempts']} probes, {row['missing_echoes']} missing echoes", flush=True)
        # Use the existing independent-run comparator; it rejects duplicate raw CSV evidence.
        comparison = compare(bundles)
        journal["comparison"] = comparison
        journal["status"] = "PASS"
        return journal
    except Exception as exc:
        journal["status"] = "ERROR"
        journal["error"] = f"{type(exc).__name__}: {exc}"
        print(f"SERIES ABORTED: {exc}", file=sys.stderr)
        raise
    finally:
        if started:
            # Redundant safe restoration even when the child trial fails mid-stop.
            try:
                runner(["docker", "compose", "-f", str(compose), "up", "-d", "transit_primary"], timeout=90)
            except Exception as restore_exc:
                journal["status"] = "ERROR"
                journal["restore_error"] = str(restore_exc)
                print("RESTORE FAILED. Run: docker compose -f <lab compose> up -d transit_primary", file=sys.stderr)
        journal["finished_utc"] = utc_now()
        write_json(manifest,journal)
        (series_dir / "series.md").write_text(markdown_report(journal), encoding="utf-8")
        print(f"Series reports: {series_dir}", flush=True)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compose", type=Path, required=True, help="Local BGP lab compose.yaml")
    p.add_argument("--series-id", required=True, help="Unique label; never reuses/overwrites a previous series")
    p.add_argument("--runs", type=int, default=3, help="Number of independent controlled outages: 2..5")
    p.add_argument("--allow-primary-stop", action="store_true", help="EXPLICIT OPT-IN to stop only transit_primary once per run")
    p.add_argument("--seconds", type=int, default=24)
    p.add_argument("--fault-at", type=int, default=6)
    p.add_argument("--fault-seconds", type=int, default=5)
    p.add_argument("--interval-us", type=int, default=20000)
    p.add_argument("--timeout-ms", type=int, default=200)
    p.add_argument("--reports", type=Path, default=ROOT / "reports")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        report = execute_series(compose=args.compose, series_id=args.series_id,
                                runs=args.runs, seconds=args.seconds,
                                fault_at=args.fault_at, fault_seconds=args.fault_seconds,
                                interval_us=args.interval_us, timeout_ms=args.timeout_ms,
                                reports_root=args.reports, allow_primary_stop=args.allow_primary_stop)
        print(f"PASS: {len(report['runs'])} independent runs. See series.json/series.md")
        return 0 if report["status"] == "PASS" else 1
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
