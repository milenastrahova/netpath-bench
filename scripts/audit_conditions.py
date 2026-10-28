#!/usr/bin/env python3
"""Audits original no-fault and fault-series ZIPs; compares descriptive observations.

This offline verifier never touches Docker, Windows networking, or any router.
It excludes raw traces from the published output and does not claim causality.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import statistics
import sys
import zipfile
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.control_evidence import BASENAMES, check_triplet
from scripts.review_series import safe_archive, evaluate_series, RUN_ID_RE
from scripts.compare_conditions import compare


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verified_control(contents: dict[str,bytes]) -> dict:
    if not {"control-series.json", "control-series.md"}.issubset(contents):
        raise ValueError("Control source missing series manifest or Markdown")
    d = json.loads(contents["control-series.json"].decode("utf-8-sig"))
    if d.get("schema_version") != 1 or d.get("condition") != "NO_FAULT_CONTROL" or d.get("status") != "PASS":
        raise ValueError("Control is not a complete NO_FAULT_CONTROL series")
    settings = d.get("settings")
    if not isinstance(settings,dict) or settings.get("protocol") != "udp":
        raise ValueError("Invalid control settings")
    for key in ("seconds", "timeout_ms", "interval_us"):
        if type(settings.get(key)) is not int or settings[key] <= 0:
            raise ValueError(f"Invalid control setting: {key}")
    runs = d.get("runs")
    if not isinstance(runs,list) or not 2 <= len(runs) <= 10 or d.get("planned_runs") != len(runs):
        raise ValueError("Invalid number of control runs")
    ids = [r.get("run_id") if isinstance(r,dict) else None for r in runs]
    if len(set(ids)) != len(ids) or any(not isinstance(x,str) or not RUN_ID_RE.fullmatch(x) for x in ids):
        raise ValueError("Invalid or duplicate control run ID")
    expected = {"control-series.json", "control-series.md"}
    for rid in ids:
        base = f"bgp-baseline-udp-{rid}"
        expected.update({f"{rid}.zip",f"{base}.json",f"{base}.csv",f"{base}-events.json"})
    if set(contents) != expected:
        raise ValueError("Control ZIP missing or containing extra files")
    verified = []
    fingerprints=set()
    endpoints=set()
    for entry in runs:
        rid=entry["run_id"]
        nested_name=f"{rid}.zip"
        if entry.get("archive")!=nested_name or sha(contents[nested_name])!=entry.get("bundle_sha256"):
            raise ValueError(f"Control bundle hash/name mismatch: {rid}")
        with zipfile.ZipFile(io.BytesIO(contents[nested_name])) as nested_zip:
            infos=nested_zip.infolist()
            if len(infos)!=len(BASENAMES) or len(set(i.filename for i in infos))!=len(BASENAMES) or set(i.filename for i in infos)!=set(BASENAMES):
                raise ValueError(f"Unexpected control bundle entries: {rid}")
            if any(i.is_dir() or i.file_size>12_000_000 for i in infos):
                raise ValueError(f"Oversized control bundle entry: {rid}")
            inner={n:nested_zip.read(n) for n in BASENAMES}
        for inner_name, suffix in zip(BASENAMES, (".json", ".csv", "-events.json")):
            outer_name=f"bgp-baseline-udp-{rid}{suffix}"
            if contents[outer_name]!=inner[inner_name]:
                raise ValueError(f"Nested/loose control mismatch: {outer_name}")
        validated=check_triplet(inner)
        probe=json.loads(inner[BASENAMES[0]].decode('utf-8-sig'))
        events=json.loads(inner[BASENAMES[2]].decode('utf-8-sig'))
        if events.get('run_id')!=rid or abs(float(probe['observation_duration_ms'])-1000*settings['seconds'])>1500:
            raise ValueError(f"Unexpected control duration/run identity: {rid}")
        endpoints.add((probe.get('host'),probe.get('source_ip'),probe.get('port'),probe.get('packet_bytes')))
        if entry.get('verification')!='PASS':
            raise ValueError(f"Unverified control run: {rid}")
        for k in ('attempts','successes','unsuccessful'):
            if entry.get(k)!=validated[k]:raise ValueError(f"Control {k} disagrees with raw CSV: {rid}")
        for k in ('mean','p50','p95','p99','p999','max'):
            if abs(float(entry.get('rtt_ms',{}).get(k, -100))-validated['rtt_ms'][k])>0.00005:
                raise ValueError(f"Control {k} disagrees with raw CSV: {rid}")
        if entry.get('csv_sha256')!=validated['csv_sha256'] or entry.get('sha256')!=validated['sha256']:
            raise ValueError(f"Control raw file digest mismatch: {rid}")
        fp=validated['csv_sha256']
        if fp in fingerprints:raise ValueError("Repeated control CSV is not independent")
        fingerprints.add(fp)
        verified.append({**validated,'run_id':rid,'archive':nested_name,'bundle_sha256':sha(contents[nested_name])})
    if len(endpoints)!=1 or next(iter(endpoints))!=('10.40.40.1','10.10.10.1',9000,64):
        raise ValueError("Inconsistent or unexpected control endpoints")
    aggregate=d.get('aggregate',{})
    if (aggregate.get('runs')!=len(verified) or aggregate.get('attempts')!=sum(x['attempts'] for x in verified)
        or aggregate.get('unsuccessful')!=sum(x['unsuccessful'] for x in verified)
        or abs(float(aggregate.get('run_level_median_p99_ms', -100))-statistics.median(x['rtt_ms']['p99'] for x in verified))>0.000005):
        raise ValueError('Control aggregate does not match original per-sample records')
    return {"schema_version":1,"condition":"NO_FAULT_CONTROL","status":"PASS",
            "series_id":d['series_id'],"settings":settings,"runs":verified,
            "aggregate":aggregate,"source_sha256":sha(contents['control-series.json'])}


def audit_archives(control_path: Path, failure_path: Path) -> dict:
    if control_path.resolve()==failure_path.resolve():
        raise ValueError("Control and failover input must be different files")
    # Archives are read in memory with per-member caps, no filesystem extraction.
    control_contents=safe_archive(control_path)
    failure_contents=safe_archive(failure_path)
    control=verified_control(control_contents)
    failure,_=evaluate_series(failure_contents)
    result=compare(control, failure)
    result.update({
        'source_archives_sha256':{
            'control':sha(control_path.read_bytes()),'failover':sha(failure_path.read_bytes())},
        'control_run_ids':[r['run_id'] for r in control['runs']],
        'failover_run_ids':[r['run_id'] for r in failure['runs']],
        'failover_missed_probes':[
            {'run_id':r['run_id'],'observed':r['missed_probes']} for r in failure['runs']
        ],
        'data_provenance':'Original CSV, JSON, events, nested ZIP bytes and original hashes verified independently',
        'no_fault_network_checks':'Lab routing checks executed by control orchestrator, not independently re-measured by offline review',
        'cross_series_causality':'NOT_ESTABLISHED',
    })
    return result


def markdown(d: dict) -> str:
    c,f=d['control'],d['failover']
    lines=[
      '# NetPath Bench — Verified control versus failover observations','',
      '## Test conditions','',
      f'- Protocol: UDP, 64-byte application payload; {d["settings"]["seconds"]}-second trials, '
      f'interval {d["settings"]["interval_us"]} microseconds, timeout {d["settings"]["timeout_ms"]} milliseconds.',
      '- Traffic: Edge 10.10.10.1 to Core 10.40.40.1 through FRRouting in Docker/WSL2.',
      '- Conditions were collected sequentially; operating-system load and clock synchronization were not controlled.',
      '', '## Original-data verification','',
      '**PASS:** both source archives were checked against raw CSV/JSON, event records, original nested bundles and SHA-256 references.',
      '', '| Metric | Healthy control | Injected primary failure |',
      '| --- | ---: | ---: |',
      f'| Independent runs | {c["runs"]} | {f["runs"]} |',
      f'| Application echo requests | {c["attempts"]:,} | {f["attempts"]:,} |',
      f'| Successful echoes | {c["successful_echoes"]:,} | {f["successful_echoes"]:,} |',
      f'| Unsuccessful echoes | {c["unsuccessful_echoes"]} | {f["unsuccessful_echoes"]} |',
      f'| Observed failure ratio | {100*c["observed_echo_failure_ratio"]:.4f}% | {100*f["observed_echo_failure_ratio"]:.4f}% |',
      f'| Median of run-level p99 successful RTT | {c["run_level_median_p99_ms"]:.6f} ms | {f["run_level_median_p99_ms"]:.6f} ms |',
      '', '## Interpretation','',
      'A missing application-level echo was seen in each injected-failure run and none in the two control runs.',
      'The p99 RTT of **successful** echoes was numerically lower in the injected-failure runs: '
      'this is not an improvement claim, because missing echoes are excluded from successful-RTT percentiles '
      'and the trials are not matched for host load.',
      'The time alignment of each missed echo and the stop request is approximate; the analyzer does not measure '
      'network outage duration or BGP protocol convergence.',
      '', '## Per-run p99 (ms)', '',
    ]
    for condition in ('control','failover'):
        group=d[condition]
        lines.extend([f'### {condition.title()}','',f'Runs: {group["runs"]}; median p99: {group["run_level_median_p99_ms"]:.6f} ms.',''])
    lines.extend(['## Source archive SHA-256','',f'- Control: `{d["source_archives_sha256"]["control"]}`',
                  f'- Failover: `{d["source_archives_sha256"]["failover"]}`','',
                  '## Methodological limits',''] + ['- '+x for x in d['limitations']])
    lines+=['','**Conclusion:** descriptively different results under two controlled lab conditions; '
              '**no causal claim, production-grade HFT claim, or physical packet-loss claim is made.**','']
    return '\n'.join(lines)


def svg_chart(d: dict) -> str:
    # Static, self-contained vector diagram. Only verified numerical values are rendered.
    c,f=d['control'],d['failover']; W,H=920,510
    y0=165; bottom=394; maxv=max(c['run_level_median_p99_ms'],f['run_level_median_p99_ms'],0.01)*1.30
    def y(v):return bottom-(v/maxv)*(bottom-y0)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="Measured run-level p99 and unsuccessful echoes">',
           '<rect width="920" height="510" rx="16" fill="#f8fafc"/>',
           '<text x="36" y="48" font-family="Arial,sans-serif" font-size="24" font-weight="700" fill="#17253a">NetPath Bench — observed conditions</text>',
           '<text x="36" y="76" font-family="Arial,sans-serif" font-size="14" fill="#506178">Four Docker/FRR trials, 28 October 2026 · descriptive only</text>',
           '<text x="36" y="112" font-family="Arial,sans-serif" font-size="15" font-weight="600" fill="#17253a">Median per-run p99 RTT (successful UDP echoes, ms)</text>',
           f'<line x1="75" y1="{bottom}" x2="842" y2="{bottom}" stroke="#9baabc" stroke-width="1.5"/>']
    for i in range(5):
        v=maxv*i/4;pos=y(v)
        parts.extend([f'<line x1="75" x2="842" y1="{pos:.1f}" y2="{pos:.1f}" stroke="#dfe6ec"/>',
                      f'<text x="66" y="{pos+4:.1f}" text-anchor="end" font-family="Arial" font-size="12" fill="#506178">{v:.2f}</text>'])
    for x,k,label,color in [(250,'control','No fault','#16838a'),(585,'failover','Primary outage','#bd5c45')]:
        v=d[k]['run_level_median_p99_ms']; yy=y(v)
        parts += [f'<rect x="{x}" y="{yy:.1f}" width="115" height="{bottom-yy:.1f}" fill="{color}" rx="5"/>',
                  f'<text x="{x+58}" y="{yy-12:.1f}" font-family="Arial" font-size="17" font-weight="700" text-anchor="middle" fill="#18253a">{v:.3f}</text>',
                  f'<text x="{x+58}" y="418" font-family="Arial" font-size="14" text-anchor="middle" fill="#233146">{escape(label)}</text>',
                  f'<text x="{x+58}" y="441" font-family="Arial" font-size="13" text-anchor="middle" fill="#516075">{d[k]["unsuccessful_echoes"]} / {d[k]["attempts"]} echo misses</text>']
    parts += ['<text x="36" y="482" font-family="Arial" font-size="13" fill="#56657a">Missing replies are application observations, not verified wire loss. Causality NOT established.</text>','</svg>']
    return '\n'.join(parts)+'\n'


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--control-zip',type=Path,required=True)
    p.add_argument('--failover-zip',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise FileExistsError('Refusing to overwrite an existing output directory')
        result=audit_archives(args.control_zip,args.failover_zip)
        args.output_dir.mkdir(parents=True)
        (args.output_dir/'condition-comparison.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        (args.output_dir/'condition-comparison.md').write_text(markdown(result),encoding='utf-8')
        (args.output_dir/'condition-comparison.svg').write_text(svg_chart(result),encoding='utf-8')
        print('PASS: independently verified 2 conditions; '+str(result['control']['attempts']+result['failover']['attempts'])+' raw UDP samples audited')
        print('Control unsuccessful: '+str(result['control']['unsuccessful_echoes']))
        print('Outage unsuccessful: '+str(result['failover']['unsuccessful_echoes']))
        print('Causality: NOT_ESTABLISHED; output: '+str(args.output_dir))
        return 0
    except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile,json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1

if __name__=='__main__':sys.exit(main())
