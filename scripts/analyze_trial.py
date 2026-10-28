#!/usr/bin/env python3
"""Independent offline summary of NetPath Bench probe CSV vs optional orchestration events.

Correlation uses UTC system clocks across Windows/Docker; NOT precision packet timing.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path
import statistics
import sys


def parse_utc(value: str) -> dt.datetime:
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("UTC timestamp must include timezone")
    return result.astimezone(dt.timezone.utc)


def percentile(items: list[float], pct: float):
    if not items:
        return None
    return sorted(items)[max(0, math.ceil(len(items) * pct) - 1)]


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError("empty sample CSV")
    if len(rows) > 100000:
        raise ValueError("sample CSV exceeds maximum allowed rows")
    data = []
    previous = -1.0
    for i, row in enumerate(rows):
        if int(row["sequence"]) != i:
            raise ValueError(f"nonconsecutive sample sequence at line {i+2}")
        offset = float(row["start_offset_ms"])
        if not math.isfinite(offset) or offset < previous:
            raise ValueError("nonfinite or unsorted sample times")
        previous = offset
        status = row["status"]
        if status not in ("ok", "timeout", "send_error", "invalid_echo"):
            raise ValueError("unrecognized sample status")
        rtt = None if row["rtt_ms"] == "null" else float(row["rtt_ms"])
        if (status == "ok") != (rtt is not None):
            raise ValueError("RTT/status mismatch")
        if rtt is not None and (not math.isfinite(rtt) or rtt < 0):
            raise ValueError("invalid RTT")
        data.append((offset, status, rtt))
    return data


def summary(data):
    ok = [rtt for _, status, rtt in data if status == "ok"]
    return {"samples": len(data), "successful_echoes": len(ok),
            "missing_or_invalid_echoes": len(data)-len(ok),
            "application_echo_failure_ratio": round((len(data)-len(ok))/len(data), 6) if data else None,
            "rtt_ms": {"min": min(ok) if ok else None,
                       "mean": statistics.mean(ok) if ok else None,
                       "p50": percentile(ok, .5), "p95": percentile(ok, .95),
                       "p99": percentile(ok, .99), "p999": percentile(ok, .999),
                       "max": max(ok) if ok else None}}


def analyze(json_path: Path, csv_path: Path, events_path: Path | None = None) -> dict:
    info = json.loads(json_path.read_text(encoding="utf-8"))
    data = read_csv(csv_path)
    if info.get("sample_count") != len(data) or info.get("attempted") != len(data):
        raise ValueError("JSON and CSV sample counts mismatch")
    if info.get("successful_echoes") != sum(s == "ok" for _, s, _ in data):
        raise ValueError("JSON/CSV success counts mismatch")
    start = parse_utc(info["started_at_utc"])
    groups = {"complete": data}
    report = {"schema_version": 1, "experiment": "netpath-bench_offline_echo_review",
              "probe_source": str(json_path), "sample_source": str(csv_path),
              "protocol": info["protocol"], "phase_correlation": "NOT_REQUESTED", "phases": {},
              "limitations": "Userspace echo RTT, not one-way NIC latency or wire loss. "
              "Sample timestamps use Docker/Windows system clocks and a client steady-clock offset; "
              "clock skew and orchestration latency prohibit precise BGP outage estimation."}
    if events_path is not None:
        event_json = json.loads(events_path.read_text(encoding="utf-8"))
        if event_json.get("status") != "CAPTURED":
            raise ValueError("trial metadata is incomplete")
        if event_json.get("mode") == "failover":
            phase_times = {event["phase"]: parse_utc(event["utc"])
                           for event in event_json["events"]}
            first = phase_times.get("primary_stop_requested")
            last = phase_times.get("primary_restore_command_finished")
            if first is None or last is None or last < first:
                raise ValueError("missing or invalid orchestration fault timestamps")
            buckets = {"before_stop_request": [], "stop_to_restore_command_finished": [],
                       "after_restore_command_finished": []}
            for offset, status, rtt in data:
                sample_time = start + dt.timedelta(milliseconds=offset)
                key = ("before_stop_request" if sample_time < first else
                       "stop_to_restore_command_finished" if sample_time <= last else
                       "after_restore_command_finished")
                buckets[key].append((offset,status,rtt))
            groups.update(buckets)
            report["phase_correlation"] = "APPROXIMATE_UTC_ONLY"
            report["phase_windows_utc"] = {"stop_requested": first.isoformat(),
                                            "restore_command_finished": last.isoformat()}
        else:
            report["phase_correlation"] = "BASELINE_NO_FAULT"
    report["phases"] = {key: summary(items) for key, items in groups.items()}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--output", type=Path)
    args=parser.parse_args(argv)
    try:
        result=analyze(args.json,args.csv,args.events)
        output=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n"
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(output,encoding="utf-8")
        print(output)
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 1

if __name__ == "__main__":sys.exit(main())
