#!/usr/bin/env python3
"""Independent NO-FAULT control runs across existing FRRouting lab routing.

Read-only FRRouting checks; does not call 'docker stop', 'docker compose stop',
or the fault-injection mode. Stops series on any error, never overwrites results.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.repeat_failover import validate_series_id, run_command, write_json, utc_now
from scripts.control_evidence import bundle_baseline, read_baseline_bundle


def validate_inputs(series_id:str,runs:int,seconds:int,interval_us:int,timeout_ms:int)->None:
    validate_series_id(series_id)
    if not 2 <= runs <= 10:
        raise ValueError('Control --runs must be 2..10')
    if not 8 <= seconds <= 180:
        raise ValueError('--seconds must be 8..180')
    if not 0 <= interval_us <= 10_000_000 or not 1 <= timeout_ms <= 60_000:
        raise ValueError('Invalid probe timing')


def execute_controls(*,compose:Path,series_id:str,runs:int,seconds:int,
                     interval_us:int,timeout_ms:int,reports_root:Path,
                     runner:Callable[...,str]=run_command)->dict:
    validate_inputs(series_id,runs,seconds,interval_us,timeout_ms)
    compose=compose.resolve(strict=True)
    labctl=compose.parent/'scripts'/'labctl.py'
    if not labctl.is_file():raise ValueError('Expected labctl.py beside BGP Compose')
    folder=(reports_root/f'control-{series_id}').resolve()
    if folder.exists(): raise FileExistsError('Control series folder already exists')
    folder.mkdir(parents=True)
    journal={'schema_version':1,'condition':'NO_FAULT_CONTROL','series_id':series_id,
             'created_at_utc':utc_now(),'status':'IN_PROGRESS',
             'settings':{'protocol':'udp','seconds':seconds,'timeout_ms':timeout_ms,'interval_us':interval_us},
             'planned_runs':runs,'runs':[],
             'limitations':'Userspace echo RTT, not NIC wire latency or independent physical loss. Observed baseline snapshots do not prove absence of other network faults.'}
    outfile=folder/'control-series.json'
    write_json(outfile,journal)
    try:
        for i in range(1,runs+1):
            run_id=f'{series_id}-{i:02d}'
            print(f'[CONTROL {i}/{runs}] Check BGP healthy before trial',flush=True)
            runner([sys.executable,str(labctl),'check','--timeout','120'],timeout=180)
            print(f'[CONTROL {i}/{runs}] UDP probe with NO container outage',flush=True)
            runner([sys.executable,str(ROOT/'scripts'/'bgp_routed_trial.py'),
                    '--compose',str(compose),'--mode','baseline','--protocol','udp',
                    '--run-id',run_id,'--seconds',str(seconds),'--interval-us',str(interval_us),
                    '--timeout-ms',str(timeout_ms),'--reports',str(folder)],timeout=seconds+200)
            print(f'[CONTROL {i}/{runs}] Check BGP healthy after trial',flush=True)
            runner([sys.executable,str(labctl),'check','--timeout','120'],timeout=180)
            archive=folder/f'{run_id}.zip'
            bundle_baseline(folder,run_id,archive)
            result=read_baseline_bundle(archive)
            result.update(run_id=run_id,archive=archive.name,bundle_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
            journal['runs'].append(result)
            write_json(outfile,journal)
            print(f'[CONTROL {i}/{runs}] PASS {result["successes"]}/{result["attempts"]} echoes',flush=True)
        journal['status']='PASS'
        journal['aggregate']={
            'runs':len(journal['runs']),
            'attempts':sum(r['attempts'] for r in journal['runs']),
            'unsuccessful':sum(r['unsuccessful'] for r in journal['runs']),
            'run_level_median_p99_ms':statistics.median(r['rtt_ms']['p99'] for r in journal['runs'])}
        return journal
    except Exception as exc:
        journal['status']='ERROR'
        journal['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        journal['finished_at_utc']=utc_now()
        write_json(outfile,journal)
        (folder/'control-series.md').write_text(markdown(journal),encoding='utf-8')
        print(f'Control reports: {folder}',flush=True)


def markdown(d:dict)->str:
    lines=['# NetPath Bench — No-fault BGP control series','',
           f'Series: `{d["series_id"]}` | status: **{d["status"]}**','',
           '| Run | Echoes | Missing | p99 RTT (ms) |','| --- | ---: | ---: | ---: |']
    for r in d['runs']:
        lines.append(f'| {r["run_id"]} | {r["successes"]}/{r["attempts"]} | {r["unsuccessful"]} | {r["rtt_ms"]["p99"]:.6f} |')
    lines += ['', 'No fault was intentionally injected. Per-run baseline and recovery BGP checks were performed.','',
              'RTT is userspace application echo RTT; missing echoes are not verified network packet loss.','',
              'Do not interpret this series as a control for unrelated CPU load, other traffic, or unmeasured environmental differences.','']
    if d.get('error'):lines.extend([f'Incomplete series: `{d["error"]}`',''])
    return '\n'.join(lines)


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compose',type=Path,required=True)
    p.add_argument('--series-id',required=True)
    p.add_argument('--runs',type=int,default=2)
    p.add_argument('--seconds',type=int,default=24)
    p.add_argument('--interval-us',type=int,default=20000)
    p.add_argument('--timeout-ms',type=int,default=200)
    p.add_argument('--reports',type=Path,default=ROOT/'reports')
    args=p.parse_args(argv)
    try:
        out=execute_controls(compose=args.compose,series_id=args.series_id,runs=args.runs,seconds=args.seconds,
                             interval_us=args.interval_us,timeout_ms=args.timeout_ms,reports_root=args.reports)
        print(f'PASS: {len(out["runs"])} no-fault runs, verified original sample files')
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired,KeyError,TypeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1
if __name__=='__main__':sys.exit(main())
