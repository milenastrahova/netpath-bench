#!/usr/bin/env python3
"""Validate raw NetPath Bench field evidence and produce a reproducible report + SVG.

Independent offline analysis. It never runs Docker or alters networking.
Clock correlation is APPROXIMATE UTC ONLY; application echo timeouts are not wire loss.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import sys
from xml.sax.saxutils import escape
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.analyze_trial import parse_utc, read_csv, analyze, summary  # noqa: E402

FIELDS = (
    "bgp-failover-udp.json", "bgp-failover-udp.csv",
    "bgp-failover-udp-events.json", "bgp-failover-analysis.json",
)
MAX_BYTES = 12_000_000


def read_evidence_zip(archive: Path) -> dict[str, bytes]:
    """Read fixed-name artifacts only; reject duplicate entries and oversized inputs."""
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) != len({i.filename for i in infos}):
            raise ValueError("duplicate ZIP entries")
        names = {i.filename for i in infos}
        required = set(FIELDS[:3])
        if not required.issubset(names):
            raise ValueError(f"missing evidence ZIP files: {sorted(required - names)}")
        if names - set(FIELDS):
            raise ValueError("unexpected file names inside evidence ZIP")
        if any(i.file_size > MAX_BYTES for i in infos) or sum(i.file_size for i in infos) > 2*MAX_BYTES:
            raise ValueError("evidence ZIP exceeds safe uncompressed size")
        return {info.filename: z.read(info) for info in infos}


def read_data(files: dict[str, bytes]) -> tuple[dict, list, dict]:
    # Existing analyzer is used as the baseline, with stricter independent validation below.
    probe = json.loads(files[FIELDS[0]].decode("utf-8-sig"))
    events = json.loads(files[FIELDS[2]].decode("utf-8-sig"))
    lines = list(csv.DictReader(io.StringIO(files[FIELDS[1]].decode("utf-8-sig"))))
    if not (1 <= len(lines) <= 100000):
        raise ValueError("invalid CSV sample count")
    required_cols = {"sequence", "start_offset_ms", "status", "rtt_ms"}
    if set(lines[0]) != required_cols:
        raise ValueError("unexpected CSV column schema")
    samples=[]
    prev=-1.0
    statuses={"ok", "timeout", "send_error", "invalid_echo"}
    for idx, row in enumerate(lines):
        if set(row) != required_cols or int(row["sequence"]) != idx:
            raise ValueError(f"invalid sample sequence or fields at {idx}")
        off=float(row["start_offset_ms"])
        if not math.isfinite(off) or off < 0 or off < prev:
            raise ValueError("invalid/non-monotonic sample offset")
        prev=off
        st=row["status"]
        if st not in statuses: raise ValueError("invalid sample status")
        rtt=None if row["rtt_ms"] == "null" else float(row["rtt_ms"])
        if (st=="ok") != (rtt is not None):
            raise ValueError("RTT/status mismatch")
        if rtt is not None and (not math.isfinite(rtt) or rtt < 0):
            raise ValueError("invalid RTT")
        samples.append({"sequence":idx,"start_offset_ms":off,"status":st,"rtt_ms":rtt})
    if probe.get("protocol") != "udp" or events.get("protocol") != "udp":
        raise ValueError("only UDP trial evidence is supported")
    if events.get("mode") != "failover" or events.get("status") != "CAPTURED":
        raise ValueError("not a completed, captured failover trial")
    if probe.get("attempted") != len(samples) or probe.get("sample_count") != len(samples):
        raise ValueError("probe JSON/CSV attempt mismatch")
    counts={x:sum(s["status"]==x for s in samples) for x in statuses}
    if probe.get("successful_echoes") != counts["ok"] or probe.get("timeouts") != counts["timeout"]:
        raise ValueError("probe JSON/CSV result count mismatch")
    if events.get("attempted") != len(samples) or events.get("successful_echoes") != counts["ok"] or events.get("echo_timeouts") != counts["timeout"]:
        raise ValueError("event JSON/CSV result count mismatch")
    if events.get("probe_exit_code") not in (0,2):
        raise ValueError("unexpected probe exit code")
    if events.get("probe_source_ip") != probe.get("source_ip") or events.get("server_ip") != probe.get("host"):
        raise ValueError("source/destination mismatch between probe and events")
    if not isinstance(probe.get("observation_duration_ms"), (int,float)) or not math.isfinite(probe["observation_duration_ms"]):
        raise ValueError("invalid observation duration")
    if probe["observation_duration_ms"] <= 0 or samples[-1]["start_offset_ms"] > probe["observation_duration_ms"] + 10:
        raise ValueError("samples beyond observation duration")
    if abs(probe["echo_failure_ratio"]-(len(samples)-counts["ok"])/len(samples)) > 0.000002:
        raise ValueError("summary echo failure ratio mismatch")
    phase_names=[x["phase"] for x in events.get("events",[])]
    phases=["server_ready","probe_command_started","primary_stop_requested","primary_stop_command_finished","primary_restore_requested","primary_restore_command_finished","probe_finished"]
    if phase_names != phases:
        raise ValueError("unexpected or incomplete phase timeline")
    ts=[parse_utc(x["utc"]) for x in events["events"]]
    if any(a > b for a,b in zip(ts,ts[1:])):
        raise ValueError("out-of-order event timestamps")
    start=parse_utc(probe["started_at_utc"])
    end=parse_utc(probe["ended_at_utc"])
    if end < start:
        raise ValueError("probe wall clock ended before it started")
    event_offset={ev["phase"]:(parse_utc(ev["utc"])-start).total_seconds()*1000 for ev in events["events"]}
    if not 0 < event_offset["primary_stop_requested"] < event_offset["primary_restore_command_finished"] < probe["observation_duration_ms"]+500:
        raise ValueError("events outside probe duration")
    return probe,samples,events


def build_review(files: dict[str, bytes]) -> tuple[dict, list]:
    probe,samples,events=read_data(files)
    start=parse_utc(probe["started_at_utc"])
    eventms={x["phase"]:(parse_utc(x["utc"])-start).total_seconds()*1000 for x in events["events"]}
    first=eventms["primary_stop_requested"];last=eventms["primary_restore_command_finished"]
    # Phase grouping via client wall-clock start + monotonic offset; APPROXIMATE only.
    groups={"pre_stop":[],"stop_to_restore_finished":[],"post_restore":[]}
    for s in samples:
        key="pre_stop" if s["start_offset_ms"]<first else "stop_to_restore_finished" if s["start_offset_ms"]<=last else "post_restore"
        groups[key].append((s["start_offset_ms"],s["status"],s["rtt_ms"]))
    timeouts=[]
    for s in samples:
        if s["status"]=="ok":continue
        i=s["sequence"]
        timeouts.append({"sequence":i,"status":s["status"],
          "sample_start_offset_ms":round(s["start_offset_ms"],6),
          "approx_sample_utc":(start+dt.timedelta(milliseconds=s["start_offset_ms"])).isoformat(),
          "approx_ms_after_stop_request":round(s["start_offset_ms"]-first,3),
          "approx_ms_after_stop_command_finished":round(s["start_offset_ms"]-eventms["primary_stop_command_finished"],3),
          "gap_to_next_probe_start_ms":round(samples[i+1]["start_offset_ms"]-s["start_offset_ms"],3) if i+1<len(samples) else None,
          "gap_from_prev_probe_start_ms":round(s["start_offset_ms"]-samples[i-1]["start_offset_ms"],3) if i>0 else None})
    bucket_ms=250
    buckets={}
    for s in samples:
        idx=int(s["start_offset_ms"]//bucket_ms)
        buckets.setdefault(idx,[]).append((s["start_offset_ms"],s["status"],s["rtt_ms"]))
    windows=[]
    for idx,values in sorted(buckets.items()):
        su=summary(values)
        windows.append({"window_start_ms":idx*bucket_ms,"samples":su["samples"],"failed_echoes":su["missing_or_invalid_echoes"],"mean_rtt_ms":su["rtt_ms"]["mean"],"p99_rtt_ms":su["rtt_ms"]["p99"]})
    checksums={n:hashlib.sha256(files[n]).hexdigest() for n in FIELDS[:3]}
    measured=summary([(s["start_offset_ms"],s["status"],s["rtt_ms"]) for s in samples])
    review={"schema_version":1,"analysis":"independent_netpath_field_evidence_review",
      "verification":"PASS", "experiment":"controlled_primary_transit_stop_with_udp_echo",
      "probe_started_utc":probe["started_at_utc"],
      "evidence_sha256":checksums,"counts":{
       "attempted":measured["samples"],"successful_echoes":measured["successful_echoes"],
       "missing_or_invalid_echoes":measured["missing_or_invalid_echoes"],
       "application_echo_failure_ratio":measured["application_echo_failure_ratio"]},
      "rtt_ms":measured["rtt_ms"],"phase_counts":{key:summary(items) for key,items in groups.items()},
      "events_relative_to_probe_start_ms":{k:round(v,3) for k,v in eventms.items()},
      "non_successful_probes":timeouts,"time_windows_250ms":windows,
      "limitations":[
       "Latency is application-level userspace echo RTT, not NIC wire or one-way latency.",
       "Timeouts mean absent application echoes by deadline, not verified on-wire packet loss.",
       "Fault event timestamps come from Windows; probe wall-clock timestamps come from Linux/Docker and correlate only approximately.",
       "One run does not establish statistical repeatability or BGP convergence time.",
       "The observed failure occurring near a stop request is temporal association, not demonstrated causation."
      ]}
    return review,samples


def svg_plot(review: dict, samples: list) -> str:
    W,H=1160,480; left,right,top,bottom=80,30,40,65
    width=W-left-right;height=H-top-bottom
    end=max(s["start_offset_ms"] for s in samples)
    vals=[s["rtt_ms"] for s in samples if s["status"]=="ok"]
    maxy=max(1.05, max(vals)*1.07 if vals else 1.05)
    def x(t):return left+width*t/end
    def y(v):return top+height*(1-v/maxy)
    def esc(s):return escape(str(s))
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="NetPath Bench UDP application echo RTT vs elapsed time with failover events">',
      '<rect width="100%" height="100%" fill="#ffffff"/>',
      '<text x="80" y="22" font-family="Arial,sans-serif" font-size="17" font-weight="bold">UDP echo RTT during controlled primary-transit stop (one run)</text>']
    first=review["events_relative_to_probe_start_ms"]["primary_stop_requested"]
    last=review["events_relative_to_probe_start_ms"]["primary_restore_command_finished"]
    parts.append(f'<rect x="{x(first):.2f}" y="{top}" width="{x(last)-x(first):.2f}" height="{height}" fill="#e7edf8"/>')
    for val in [0,.25,.5,.75,1.0]:
        if val>maxy: continue
        yy=y(val)
        parts.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{W-right}" y2="{yy:.2f}" stroke="#e3e5e8"/>')
        parts.append(f'<text x="{left-11}" y="{yy+4:.2f}" text-anchor="end" font-family="Arial,sans-serif" font-size="13">{val:.2f}</text>')
    for sec in range(0,25,4):
        xx=x(sec*1000)
        parts.append(f'<line x1="{xx:.2f}" y1="{top}" x2="{xx:.2f}" y2="{H-bottom}" stroke="#eff1f4"/>')
        parts.append(f'<text x="{xx:.2f}" y="{H-bottom+23}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12">{sec}</text>')
    pts=' '.join(f'{x(s["start_offset_ms"]):.2f},{y(s["rtt_ms"]):.2f}' for s in samples if s["status"]=='ok')
    parts.append(f'<polyline fill="none" stroke="#2563eb" stroke-width="1.1" points="{pts}"/>')
    for failure in review["non_successful_probes"]:
        xx=x(failure["sample_start_offset_ms"])
        parts.append(f'<line x1="{xx:.2f}" y1="{top}" x2="{xx:.2f}" y2="{H-bottom}" stroke="#c0392b" stroke-width="1.5" stroke-dasharray="4 4"/>')
        parts.append(f'<circle cx="{xx:.2f}" cy="{H-bottom-4}" r="5" fill="#c0392b"/>')
    for t,label in [(first,"Stop requested"),(last,"Restore finished")]:
        xx=x(t)
        parts.append(f'<line x1="{xx:.2f}" y1="{top}" x2="{xx:.2f}" y2="{H-bottom}" stroke="#626d82" stroke-width="1.3"/>')
        parts.append(f'<text transform="translate({xx+12:.2f} {top+13}) rotate(90)" font-family="Arial,sans-serif" fill="#334155" font-size="12">{esc(label)}</text>')
    parts+= [f'<text x="{W/2}" y="{H-11}" font-family="Arial,sans-serif" text-anchor="middle" font-size="14">Seconds since probe start (monotonic offset)</text>',
      f'<text transform="translate(21 {H/2}) rotate(-90)" font-family="Arial,sans-serif" text-anchor="middle" font-size="14">Application echo RTT (ms)</text>',
      '</svg>']
    return '\n'.join(parts)+'\n'


def markdown_report(review:dict) -> str:
    counts=review['counts'];s=review['rtt_ms'];f=review['non_successful_probes']
    rows=['# NetPath Bench — Verified Field Experiment', '',
    f"Controlled BGP primary-transit stop · {review['probe_started_utc'][:10]} · one Windows 11 / Docker Desktop trial", '',
    '**Source:** Original user-collected UDP echo JSON, per-probe CSV and orchestration events. Raw evidence is not bundled into the public release.', '',
    '## Method and measurements', '',
    'The C++ client in the FRRouting Edge network namespace sent sequential UDP echo requests to a server in the Core network namespace. The orchestration script stopped and restarted the primary transit router. The alternate BGP path was available, but this run does not independently timestamp BGP bestpath transitions.', '',
    '| Observation | Value |', '|---|---:|',
    f'| Attempts | {counts["attempted"]:,} |',f'| Successful echoes | {counts["successful_echoes"]:,} |',
    f'| Missing application echo responses | {counts["missing_or_invalid_echoes"]} |',
    f'| Echo failure ratio | {100*counts["application_echo_failure_ratio"]:.4f}% |',
    f'| Mean RTT | {s["mean"]:.6f} ms |',f'| p50 RTT | {s["p50"]:.6f} ms |',
    f'| p95 RTT | {s["p95"]:.6f} ms |',f'| p99 RTT | {s["p99"]:.6f} ms |',
    f'| p99.9 RTT | {s["p999"]:.6f} ms |',f'| Maximum successful RTT | {s["max"]:.6f} ms |','',
    '![Application echo RTT time series](field-timeline.svg)', '',
    '## Approximate phase breakdown', '',
    '| Phase | Attempts | Missing echoes | Mean RTT (ms) | p99 RTT (ms) |', '|---|---:|---:|---:|---:|']
    for name, v in review['phase_counts'].items():
        rt=v['rtt_ms'];rows.append(f'| `{name}` | {v["samples"]} | {v["missing_or_invalid_echoes"]} | {rt["mean"]:.6f} | {rt["p99"]:.6f} |')
    rows+=['','## Individual unsuccessful probes','']
    for e in f:
        rows+= [f'- Sequence **{e["sequence"]}** (`{e["status"]}`), approximately {e["approx_ms_after_stop_request"]:.3f} ms after the Windows stop request; the next probe began {e["gap_to_next_probe_start_ms"]:.3f} ms later. This gap includes the application timeout and is **not network downtime**.']
    if not f:rows+=['- None observed in this run.']
    rows+=['','## Data integrity', '',
           'The analyzer verified the JSON/CSV counts, consecutive sequence numbering, valid sample statuses, timestamp ordering, the expected controlled-stop event sequence, and the source/destination identity.', '',
           '| Source artifact | SHA-256 |', '|---|---|']
    for path,digest in review['evidence_sha256'].items():rows.append(f'| `{path}` | `{digest}` |')
    rows+=['','## Interpretation and limitations','',
    'The absence of one application echo occurs inside the approximate period of the primary-stop request. It is a temporal association, **not proof that BGP reconvergence caused packet loss**. The mean and tail RTTs are from a single run and are not stable production performance claims.', '',
    '- RTT is a **userspace round trip**; no hardware timestamping or one-way latency measurement was performed.',
    '- A timeout is **not proof of physical packet loss**. No packet capture or receiver-side loss counters were collected.',
    '- Sample offsets are relative to the Linux client monotonic clock; event timestamps are Windows wall-clock values. Phase boundaries are **approximately** correlated.',
    '- The study cannot estimate precise BGP protocol convergence, forwarding outage, or network loss duration.',
    '- Single-run p99 and p99.9 should not be presented as statistically representative without repeated independent trials.', '',
    '## Next evidence to collect','',
    'Repeat multiple *independent* baseline and failover runs with uniquely named artifacts. Pair with FRR route observations and, when possible, a receiver-side packet capture to distinguish missing application acknowledgments from link-level loss. Compare run-level summaries rather than combining them into one artificially large sample.', '']
    return '\n'.join(rows)


def make_artifacts(archive:Path,output_dir:Path,overwrite=False)->dict:
    files=read_evidence_zip(archive)
    review,samples=build_review(files)
    # Read existing analyzer result only to cross-check, never trust it as source of truth.
    if FIELDS[3] in files:
        old=json.loads(files[FIELDS[3]].decode("utf-8-sig"))
        total=old.get('phases',{}).get('complete',{})
        if total.get('samples') != review['counts']['attempted'] or total.get('successful_echoes')!=review['counts']['successful_echoes']:
            raise ValueError("legacy summary disagrees with raw evidence")
    output_dir.mkdir(parents=True,exist_ok=True)
    targets={'json':output_dir/'field-review.json','markdown':output_dir/'field-review.md','svg':output_dir/'field-timeline.svg'}
    if not overwrite and any(p.exists() for p in targets.values()):
        raise ValueError('output files already exist; pass --overwrite only after reviewing them')
    targets['json'].write_text(json.dumps(review,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    targets['markdown'].write_text(markdown_report(review),encoding='utf-8')
    targets['svg'].write_text(svg_plot(review,samples),encoding='utf-8')
    return targets


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-zip',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,default=Path('reports')/'verified-review')
    parser.add_argument('--overwrite',action='store_true')
    args=parser.parse_args(argv)
    try:
        targets=make_artifacts(args.evidence_zip,args.output_dir,args.overwrite)
        print('PASS: raw sample and event consistency verified')
        for k,v in targets.items():print(f'{k}: {v}')
        return 0
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,UnicodeError) as e:
        print(f'ERROR: {e}',file=sys.stderr)
        return 1

if __name__=='__main__':sys.exit(main())
