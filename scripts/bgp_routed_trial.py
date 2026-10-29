#!/usr/bin/env python3
"""Run NetPath Bench inside existing FRRouting namespaces. No host network changes.

No fault is injected unless --mode failover AND --allow-primary-stop are provided.
Only transit_primary from the specifically supplied Compose project is stopped.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

IMAGE = "netpath-bench-lab:1.0"
SERVICES = {"edge", "core", "transit_primary", "transit_backup"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def call(args: list[str], *, timeout: int = 40) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def compose_cmd(path: Path, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(path), *args]


def check_preflight(compose_path: Path) -> tuple[str, str, str]:
    """Resolve exactly the expected FRRouting services without hard-coded project names.

    The supplied compose file, not a company-specific Docker name, determines
    the router containers. Fail closed before optional fault injection.
    """
    if not compose_path.is_file():
        raise RuntimeError(f"Missing BGP Compose file: {compose_path}")
    try:
        cfg = json.loads(call(compose_cmd(compose_path, "config", "--format", "json")))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Cannot parse Docker Compose configuration as JSON") from exc
    services = cfg.get("services")
    if not isinstance(services, dict) or set(services) != SERVICES:
        raise RuntimeError("Compose must contain exactly edge, core, transit_primary and transit_backup")
    for name in SERVICES:
        image_name = services[name].get("image", "")
        if not isinstance(image_name, str) or not image_name.startswith("quay.io/frrouting/frr:"):
            raise RuntimeError(f"Not a supported FRRouting lab image for service {name}")
    project = cfg.get("name")
    if not isinstance(project, str) or not project:
        raise RuntimeError("Compose project has no valid name")
    running = set(call(compose_cmd(compose_path, "ps", "--services", "--status", "running")).splitlines())
    if running != SERVICES:
        raise RuntimeError(f"All four BGP routers must be running. Found: {sorted(running)}")
    containers = []
    for name in ("edge", "core"):
        container_id = call(compose_cmd(compose_path, "ps", "-q", name)).strip()
        if not container_id or len(container_id.splitlines()) != 1:
            raise RuntimeError(f"Unable to resolve unique router container: {name}")
        state = call(["docker", "inspect", "--format", "{{.State.Running}}", container_id])
        if state != "true":
            raise RuntimeError(f"BGP router container is not running: {name}")
        containers.append(container_id)
    call(["docker", "image", "inspect", IMAGE])
    return (project, containers[0], containers[1])


def make_probe_cmd(report_dir: Path, *, run_name: str, seconds: int,
                   timeout_ms: int, interval_us: int, tcp: bool, edge_container: str) -> list[str]:
    mode = "tcp" if tcp else "udp"
    return ["docker", "run", "--rm", "--name", f"netpath-bench-bgp-probe-{os.getpid()}",
            "--network", f"container:{edge_container}",
            "--mount", f"type=bind,source={report_dir.resolve()},target=/reports",
            IMAGE, mode, "--host", "10.40.40.1", "--source-ip", "10.10.10.1",
            "--port", "9000", "--duration-sec", str(seconds), "--bytes", "64",
            "--timeout-ms", str(timeout_ms), "--interval-us", str(interval_us),
            "--json", f"/reports/{run_name}.json", "--csv", f"/reports/{run_name}.csv"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--mode", choices=["baseline", "failover"], default="baseline")
    parser.add_argument("--allow-primary-stop", action="store_true",
                        help="Explicitly permit stopping ONLY transit_primary in the named Compose lab")
    parser.add_argument("--seconds", type=int, default=24)
    parser.add_argument("--fault-at", type=int, default=6)
    parser.add_argument("--fault-seconds", type=int, default=5)
    parser.add_argument("--interval-us", type=int, default=20000)
    parser.add_argument("--timeout-ms", type=int, default=200)
    parser.add_argument("--protocol", choices=["udp", "tcp"], default="udp")
    parser.add_argument("--run-id", help="Unique alphanumeric run label; prevents overwriting past evidence")
    parser.add_argument("--reports", type=Path, default=Path(__file__).resolve().parents[1]/"reports")
    args = parser.parse_args(argv)
    if args.mode == "failover" and not args.allow_primary_stop:
        parser.error("Failover requires explicit --allow-primary-stop")
    if args.run_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}",args.run_id):
        parser.error("--run-id must be 1-40 ASCII alphanumeric, underscore or hyphen")
    if not 8 <= args.seconds <= 180:
        parser.error("--seconds must be between 8 and 180")
    if not 1 <= args.fault_at < args.seconds:
        parser.error("--fault-at must be >=1 and < --seconds")
    if args.mode == "failover" and not 1 <= args.fault_seconds < args.seconds-args.fault_at-2:
        parser.error("--fault-seconds must leave >=3 seconds after recovery")
    if not 1 <= args.timeout_ms <= 60000 or not 0 <= args.interval_us <= 10000000:
        parser.error("invalid timeout or interval")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    compose_path = args.compose.resolve()
    report_dir = args.reports.resolve()
    # Prevent overwriting a prior experiment's evidence.
    name = "bgp-" + args.mode + "-" + args.protocol + ("-" + args.run_id if args.run_id else "")
    report_files = [report_dir/(name+suffix) for suffix in (".json", ".csv", "-events.json")]
    if any(p.exists() for p in report_files):
        print(f"ERROR: existing report. Move old files first: {report_files}", file=sys.stderr)
        return 1
    server_name = f"netpath-bench-bgp-server-{os.getpid()}"
    probe_name = f"netpath-bench-bgp-probe-{os.getpid()}"
    metadata = {"schema_version": 1, "mode": args.mode, "protocol": args.protocol,
                "run_id": args.run_id,
                "network": None, "probe_source_ip": "10.10.10.1",
                "server_ip": "10.40.40.1", "started_at_utc": utc_now(),
                "events": [], "status": "INCOMPLETE",
                "limitations": "Docker/Windows observation timestamps are not synchronized hardware timestamps. "
                "Application echo misses are NOT verified on-wire packet loss or BGP protocol convergence. "
                "Traffic uses two FRR namespaces; routing validation requires separate FRR checks."}
    server_started = False
    primary_stop_attempted = False
    probe = None
    report_dir.mkdir(parents=True, exist_ok=True)
    try:
        project_name, edge_container, core_container = check_preflight(compose_path)
        metadata["network"] = project_name
        print("PASS preflight: 4 BGP routers running and NetPath Bench Docker image present")
        call(["docker", "run", "-d", "--rm", "--name", server_name,
              "--network", f"container:{core_container}", IMAGE, "serve",
              "--bind", "10.40.40.1", "--port", "9000"])
        server_started = True
        for _ in range(30):
            logs = call(["docker", "logs", server_name])
            if "READY" in logs:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Core echo server did not become ready")
        metadata["events"].append({"phase": "server_ready", "utc": utc_now()})
        probe = subprocess.Popen(make_probe_cmd(report_dir, run_name=name,
                                 seconds=args.seconds, timeout_ms=args.timeout_ms,
                                 interval_us=args.interval_us, tcp=args.protocol == "tcp",
                                 edge_container=edge_container),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        metadata["events"].append({"phase": "probe_command_started", "utc": utc_now()})
        if args.mode == "failover":
            time.sleep(args.fault_at)
            if probe.poll() is not None:
                raise RuntimeError("Probe exited before the fault stage")
            metadata["events"].append({"phase": "primary_stop_requested", "utc": utc_now()})
            primary_stop_attempted = True
            call(compose_cmd(compose_path, "stop", "transit_primary"), timeout=60)
            metadata["events"].append({"phase": "primary_stop_command_finished", "utc": utc_now()})
            time.sleep(args.fault_seconds)
            metadata["events"].append({"phase": "primary_restore_requested", "utc": utc_now()})
            call(compose_cmd(compose_path, "up", "-d", "transit_primary"), timeout=60)
            primary_stop_attempted = False
            metadata["events"].append({"phase": "primary_restore_command_finished", "utc": utc_now()})
        stdout, stderr = probe.communicate(timeout=args.seconds+45)
        metadata["probe_exit_code"] = probe.returncode
        if probe.returncode not in (0, 2):
            raise RuntimeError(f"NetPath Bench probe failed: {stderr[-1500:]}")
        if not report_files[0].is_file() or not report_files[1].is_file():
            raise RuntimeError("Probe did not save its JSON and CSV reports")
        result = json.loads(report_files[0].read_text(encoding="utf-8"))
        if result.get("attempted", 0) == 0 or result.get("sample_count") != result.get("attempted"):
            raise RuntimeError("Invalid/incomplete probe sample counts")
        metadata["attempted"] = result["attempted"]
        metadata["successful_echoes"] = result["successful_echoes"]
        metadata["echo_timeouts"] = result["timeouts"]
        metadata["status"] = "CAPTURED"  # not a claim that the network remained healthy
        metadata["events"].append({"phase": "probe_finished", "utc": utc_now()})
        print(f"CAPTURED {result['attempted']} real {args.protocol.upper()} probes; "
              f"{result['successful_echoes']} echoes, {result['timeouts']} timeouts")
        print(f"Reports: {report_files[0]} and {report_files[1]}")
        return 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        metadata["status"] = "ERROR"
        metadata["error"] = str(exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if primary_stop_attempted:
            try:
                call(compose_cmd(compose_path, "up", "-d", "transit_primary"), timeout=60)
                metadata["events"].append({"phase": "primary_restored_in_finally", "utc": utc_now()})
            except Exception as exc:
                metadata["events"].append({"phase": "RESTORE_FAILED", "details": str(exc), "utc": utc_now()})
                metadata["status"] = "ERROR"
                print("WARNING: restore manually: docker compose -f <BGP compose> up -d transit_primary", file=sys.stderr)
        if probe is not None and probe.poll() is None:
            subprocess.run(["docker", "rm", "-f", probe_name], capture_output=True)
            try:
                probe.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                probe.kill()
        if server_started:
            subprocess.run(["docker", "stop", server_name], capture_output=True, timeout=15)
        metadata["finished_at_utc"] = utc_now()
        report_files[2].write_text(json.dumps(metadata, indent=2, ensure_ascii=False)+"\n",encoding="utf-8")
        print(f"Trial events: {report_files[2]}")


if __name__ == "__main__":
    sys.exit(main())
