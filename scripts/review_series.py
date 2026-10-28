#!/usr/bin/env python3
"""Offline audit of a complete repeat_failover.py series ZIP.

Checks nested bundles, raw file byte equality, SHA-256 references, run consistency,
CSV packet summaries and orchestration windows. No Docker and no fault injection.
Clocks are approximate: a missed application echo is NOT network packet loss.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
import statistics
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.analyze_trial import parse_utc, summary as sample_summary
from scripts.review_evidence import read_evidence_zip, build_review, read_data

MAX_TOTAL_BYTES = 100_000_000
MAX_SINGLE_BYTES = 16_000_000
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}\Z")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def nearly_equal(a: object, b: object, tolerance: float = 0.000002) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    try:
        f, g = float(a), float(b)
    except (ValueError, TypeError):
        return False
    return math.isfinite(f) and math.isfinite(g) and abs(f - g) <= tolerance


def safe_archive(archive: Path | io.BytesIO) -> dict[str, bytes]:
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > 50 or len(infos) != len({i.filename for i in infos}):
            raise ValueError("excessive or duplicate ZIP entries")
        total = 0
        for ent in infos:
            name = ent.filename
            if not name or name.startswith("/") or "\\" in name or name.startswith(".") or "/" in name or ".." in name:
                raise ValueError(f"unsafe ZIP member name: {name!r}")
            mode = ent.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                raise ValueError("symlink ZIP entry rejected")
            if ent.flag_bits & 1:
                raise ValueError("encrypted ZIP entry rejected")
            total += ent.file_size
            if ent.file_size > MAX_SINGLE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("evidence archive exceeds size limit")
        return {ent.filename: z.read(ent) for ent in infos}


def validate_run(summary: dict, raw: dict[str, bytes], nested: bytes,
                 series_settings: dict) -> tuple[dict, list]:
    run_id = summary.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid run_id")
    if summary.get("validation") != "PASS":
        raise ValueError(f"run {run_id} not validated")
    bundle_name = f"{run_id}.zip"
    if summary.get("bundle") != bundle_name or sha(nested) != summary.get("bundle_sha256"):
        raise ValueError(f"bundle SHA-256/name mismatch for {run_id}")
    files = read_evidence_zip(io.BytesIO(nested))
    review, samples = build_review(files)
    probe, _, events = read_data(files)
    recalculated=sample_summary([(s['start_offset_ms'],s['status'],s['rtt_ms']) for s in samples])
    for key in ('min','mean','p50','p95','p99','p999','max'):
        if not nearly_equal(probe.get('rtt_ms',{}).get(key),recalculated['rtt_ms'][key]):
            raise ValueError(f"JSON RTT summary {key} does not match raw CSV: {run_id}")
    if probe.get('errors') != sum(s['status']=='send_error' for s in samples) or probe.get('unexpected_replies') != sum(s['status']=='invalid_echo' for s in samples):
        raise ValueError(f"probe JSON error counts do not match raw CSV: {run_id}")
    if events.get("run_id") != run_id:
        raise ValueError(f"event run_id mismatch for {run_id}")
    if not nearly_equal(probe["observation_duration_ms"], series_settings["seconds"] * 1000, 1500):
        raise ValueError(f"wrong trial length for {run_id}")
    if events.get("probe_exit_code") != (2 if review["counts"]["missing_or_invalid_echoes"] else 0):
        raise ValueError(f"unexpected probe exit status for {run_id}")
    csv_hash = sha(files["bgp-failover-udp.csv"])
    if csv_hash != summary.get("raw_csv_sha256"):
        raise ValueError(f"CSV SHA mismatch for {run_id}")
    if summary.get("attempts") != review["counts"]["attempted"] or summary.get("missing_echoes") != review["counts"]["missing_or_invalid_echoes"]:
        raise ValueError(f"series run-level totals disagree with raw samples: {run_id}")
    if not nearly_equal(summary.get("failure_ratio"), review["counts"]["application_echo_failure_ratio"]):
        raise ValueError(f"run-level failure ratio mismatch: {run_id}")
    if not nearly_equal(summary.get("p99_rtt_ms"), review["rtt_ms"]["p99"]):
        raise ValueError(f"run-level p99 mismatch: {run_id}")
    evs = review["events_relative_to_probe_start_ms"]
    approx_stop_offset_ms = evs["primary_stop_requested"]
    approx_stop_at_s = approx_stop_offset_ms / 1000
    if abs(approx_stop_at_s - series_settings["fault_at"]) > 2.5:
        raise ValueError(f"fault event out of expected trial window: {run_id}")
    missed = []
    for m in review["non_successful_probes"]:
        missed.append({"sequence":m["sequence"], "outcome":m["status"],
            "offset_s":round(m["sample_start_offset_ms"]/1000,6),
            "approx_ms_after_stop_request":m["approx_ms_after_stop_request"],
            "approx_ms_after_stop_command_finished":m["approx_ms_after_stop_command_finished"]})
    public = {"run_id":run_id, "attempts":review["counts"]["attempted"],
          "successes":review["counts"]["successful_echoes"],
          "unsuccessful":review["counts"]["missing_or_invalid_echoes"],
          "failure_ratio":review["counts"]["application_echo_failure_ratio"],
          "rtt_ms":review["rtt_ms"], "phase_counts":review["phase_counts"],
          "missed_probes":missed,"approx_stop_at_s":round(approx_stop_at_s,6),
          "approx_restore_finished_at_s":round(evs["primary_restore_command_finished"]/1000,6),
          "evidence_sha256": review["evidence_sha256"],
          "bundle_sha256":sha(nested),"validation":"PASS"}
    return public, samples


def evaluate_series(contents: dict[str, bytes]) -> tuple[dict, list[list]]:
    if "series.json" not in contents or "series.md" not in contents:
        raise ValueError("series.json/series.md are required")
    series = json.loads(contents["series.json"].decode("utf-8-sig"))
    if series.get("schema_version") != 1 or series.get("status") != "PASS":
        raise ValueError("incomplete or unsupported series")
    settings=series.get("settings",{})
    if (settings.get("protocol") != "udp" or not isinstance(settings.get("seconds"),int) or
        not isinstance(settings.get("fault_at"),int) or not isinstance(settings.get("fault_seconds"),int)):
        raise ValueError("invalid or incompatible settings")
    runs=series.get("runs")
    if not isinstance(runs,list) or len(runs)<2 or len(runs)>5 or series.get("planned_runs") != len(runs):
        raise ValueError("unexpected run count")
    ids=[r.get("run_id") for r in runs]
    if len(set(ids))!=len(ids):
        raise ValueError("duplicate run IDs")
    expected={"series.json", "series.md"}
    for run_id in ids:
        if not isinstance(run_id,str) or not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("invalid run ID")
        stem=f"bgp-failover-udp-{run_id}"
        expected.update({f"{run_id}.zip",f"{stem}.json",f"{stem}.csv",f"{stem}-events.json"})
    if set(contents)!=expected:
        raise ValueError(f"series contents mismatch: missing={sorted(expected-set(contents))}, unexpected={sorted(set(contents)-expected)}")
    out=[]; rows=[]; fprints=set(); endpoints=set()
    for item in runs:
        run_id=item["run_id"]
        nested=contents[f"{run_id}.zip"]
        if sha(nested) != item.get("bundle_sha256"):
            raise ValueError(f"bundle SHA-256 mismatch for {run_id}")
        inner=read_evidence_zip(io.BytesIO(nested))
        stem=f"bgp-failover-udp-{run_id}"
        for inner_name,outer_name in (("bgp-failover-udp.json",f"{stem}.json"),
                    ("bgp-failover-udp.csv",f"{stem}.csv"),
                    ("bgp-failover-udp-events.json",f"{stem}-events.json")):
            if inner[inner_name] != contents[outer_name]:
                raise ValueError(f"loose/nested evidence disagreement: {outer_name}")
        v,samples=validate_run(item,contents,nested,settings)
        fp=v["evidence_sha256"]["bgp-failover-udp.csv"]
        if fp in fprints:raise ValueError("duplicate CSV evidence, not independent captures")
        fprints.add(fp)
        info=json.loads(contents[f"{stem}.json"])
        endpoints.add((info["host"],info["source_ip"],info["packet_bytes"],info["port"]))
        out.append(v); rows.append(samples)
    if len(endpoints)!=1:
        raise ValueError("run endpoints/settings are inconsistent")
    cmp=series.get("comparison",{})
    if cmp.get("run_count")!=len(runs) or cmp.get("runs_with_missing_echoes") != sum(r["unsuccessful"]>0 for r in out):
        raise ValueError("series comparison totals mismatch")
    median=statistics.median(r["rtt_ms"]["p99"] for r in out)
    if not nearly_equal(cmp.get("run_level_median_p99_ms"),median):
        raise ValueError("series comparison p99 mismatch")
    for a,b in zip(cmp.get("runs",[]),out):
        if a.get("file") != f"{b['run_id']}.zip" or a.get("evidence_csv_sha256") != b["evidence_sha256"]["bgp-failover-udp.csv"]:
            raise ValueError("series comparison source mismatch")
        for k,field in (("attempts","attempts"),("missing_echoes","unsuccessful")):
            if a.get(k) != b[field]:raise ValueError("series comparison count mismatch")
        for k,v in (("failure_ratio",b["failure_ratio"]),("p99_rtt_ms",b["rtt_ms"]["p99"]),
                    ("p999_rtt_ms",b["rtt_ms"]["p999"]),("mean_rtt_ms",b["rtt_ms"]["mean"])):
            if not nearly_equal(a.get(k),v):raise ValueError(f"comparison {k} mismatch")
    if len(cmp.get("runs",[])) != len(runs):raise ValueError("missing comparison entries")
    attempted=sum(x["attempts"] for x in out)
    unsuccessful=sum(x["unsuccessful"] for x in out)
    summary={"schema_version":1,"experiment":"independent_netpath_series_evidence_audit",
         "verification":"PASS", "series_id":series["series_id"],
         "run_count":len(out),"settings":settings,
         "counts":{"application_echo_attempts":attempted,"successful_echoes":attempted-unsuccessful,
                   "unsuccessful_echoes":unsuccessful,"overall_observed_echo_failure_ratio":round(unsuccessful/attempted,8)},
         "runs":out,
         "run_level_median_p99_rtt_ms":median,
         "series_sha256":sha(contents["series.json"]),
         "evidence_integrity":"byte-identical loose and nested raw files, original bundle hash checks and reconstructed summary match",
         "limitations":["Two runs do not establish high-confidence statistical repeatability or causality.",
           "Packet misses are application echo timeouts, not confirmed physical loss.",
           "Correlating Windows fault UTC and Linux container probe UTC is approximate; no PTP/hardware timestamps.",
           "Userspace sequential RTT is not one-way latency or sustained HFT throughput.",
           "This report does not measure BGP control-plane convergence or actual network outage duration.",
           "Release contains verified aggregate findings only; original raw data is not embedded."]}
    return summary,rows


def markdown_report(data: dict) -> str:
    s=["# NetPath Bench — Independent Repeated BGP Failover Evidence Review", "",
       f"**Series:** `{data['series_id']}` · **Verification:** {data['verification']} · **Independent runs:** {data['run_count']}","",
       "| Run | Probes | Successful | Missing echo | Mean RTT (ms) | p99 (ms) | p99.9 (ms) |",
       "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in data["runs"]:
        z=r["rtt_ms"]
        s.append(f"| `{r['run_id']}` | {r['attempts']} | {r['successes']} | {r['unsuccessful']} | {z['mean']:.6f} | {z['p99']:.6f} | {z['p999']:.6f} |")
    c=data["counts"]
    s += ["",f"**Aggregate echo observations:** {c['successful_echoes']} successful / {c['application_echo_attempts']} attempts, {c['unsuccessful_echoes']} unsuccessful; observed unsuccessful ratio {100*c['overall_observed_echo_failure_ratio']:.4f}%.",
          "", "## Missed application echoes", ""]
    for r in data["runs"]:
        for m in r["missed_probes"]:
            s.append(f"- **{r['run_id']}** seq {m['sequence']} ({m['outcome']}): started ≈ **{m['approx_ms_after_stop_request']:.1f} ms after** primary stop request in the approximate UTC alignment; exact network timing/causation is unproven.")
    s += ["", "## Scope and interpretation", "", 
          "- User-provided raw JSON/CSV/events and per-run ZIP bundles passed byte-level and semantic checks.",
          "- An application echo timeout around the fault command is a reproducible observation in *these two tests*, not proof that BGP caused it.",
          "- Do not call the 1/1168 and 1/1166 echo failures 'wire packet loss' or interpret request intervals as convergence time.",
          "- p99/p99.9 percentiles are computed separately for successful echo replies for each run; pooled percentiles are intentionally absent.",
          "- The published report retains only aggregate results and hashes, not user raw data.",
          "- Further work: control (no-outage) runs, randomized fault timing, full directional captures, and clock methodology.",""]
    return "\n".join(s)


def svg_timeline(data: dict, all_samples: list[list]) -> str:
    W,H=1180,640;left=74; right=26;top=64;row_h=245;gap=35
    n=len(all_samples)
    if n>5: raise ValueError("no more than five runs can be plotted")
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         '<rect width="100%" height="100%" fill="#ffffff"/>',
         '<text x="74" y="32" font-size="20" font-family="Arial,sans-serif" fill="#1e293b">NetPath Bench — independently captured UDP echo RTT</text>',
         '<text x="74" y="51" font-size="11" font-family="Arial,sans-serif" fill="#475569">Time from start of each probe run; vertical marks approximate Windows fault commands</text>']
    colors=["#147d8a","#9a5cbd","#a16b19","#2563eb","#2a824a"]
    # Keep deterministic dimensions for up to five runs by resizing viewbox if needed.
    H=max(200+n*(row_h+gap)+60, 640)
    parts[0]=f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
    for idx,(r,rows) in enumerate(zip(data["runs"],all_samples)):
        y0=84+idx*(row_h+gap); end=max(x["start_offset_ms"] for x in rows); ymax=max(1.25, max((x["rtt_ms"] or 0) for x in rows)*1.10)
        def sx(t):return left+(W-left-right)*t/end
        def sy(t):return y0+row_h-(t/ymax)*row_h
        parts.append(f'<text x="{left}" y="{y0-12}" fill="#1e293b" font-family="Arial,sans-serif" font-size="15">{escape(r["run_id"])} — {r["successes"]}/{r["attempts"]} echoes, p99 {r["rtt_ms"]["p99"]:.3f} ms</text>')
        parts.append(f'<rect x="{left}" y="{y0}" width="{W-left-right}" height="{row_h}" fill="#f8fafc" stroke="#cbd5e1"/>')
        for v in (0,0.5,1.0):
            y=sy(v)
            if y>=y0:
                parts.append(f'<line x1="{left}" x2="{W-right}" y1="{y:.2f}" y2="{y:.2f}" stroke="#e2e8f0"/>')
                parts.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" font-size="10" fill="#475569">{v:g}</text>')
        for key,col in (("approx_stop_at_s","#dc2626"),("approx_restore_finished_at_s","#16a34a")):
            x=sx(r[key]*1000)
            parts.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{y0}" y2="{y0+row_h}" stroke="{col}" stroke-width="2" stroke-dasharray="5 4"/>')
        col=colors[idx]
        for sample in rows:
            x=sx(sample["start_offset_ms"])
            if sample["status"]=="ok":
                parts.append(f'<circle cx="{x:.2f}" cy="{sy(sample["rtt_ms"]):.2f}" r="1.35" fill="{col}" opacity="0.57"/>')
            else:
                yy=y0+12
                parts.append(f'<path d="M{x-5:.2f} {yy-5} l10 10 m0 -10 l-10 10" stroke="#dc2626" stroke-width="2.6"/>')
        parts.append(f'<text x="{W-right}" y="{y0+row_h+19}" text-anchor="end" font-family="Arial,sans-serif" font-size="11" fill="#64748b">{end/1000:.1f} sec</text>')
    parts.append(f'<text x="{left}" y="{H-22}" font-family="Arial,sans-serif" font-size="11" fill="#475569">Userspace RTT (ms) · one marker = one probe · cross = missing application echo · not wire packet loss</text>')
    return "\n".join(parts+["</svg>",""])


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--series-zip",type=Path,required=True,help="ZIP created from the contents of series-<id> folder")
    p.add_argument("--output-dir",type=Path,required=True,help="New folder for non-raw report artifacts")
    a=p.parse_args(argv)
    try:
        if a.output_dir.exists():raise ValueError("refusing to overwrite output directory")
        contents=safe_archive(a.series_zip)
        result,raw=evaluate_series(contents)
        a.output_dir.mkdir(parents=True,exist_ok=False)
        (a.output_dir/"series-review.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        (a.output_dir/"series-review.md").write_text(markdown_report(result),encoding="utf-8")
        (a.output_dir/"series-timeline.svg").write_text(svg_timeline(result,raw),encoding="utf-8")
        print(f"PASS: {result['run_count']} independently captured runs; {result['counts']['application_echo_attempts']} application echoes audited")
        for r in result['runs']:
            print(f"  {r['run_id']}: {r['successes']}/{r['attempts']} replies, p99={r['rtt_ms']['p99']:.6f} ms")
        print(f"Reports: {a.output_dir.resolve()}")
        return 0
    except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile,UnicodeError,json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr);return 1

if __name__=="__main__": sys.exit(main())
