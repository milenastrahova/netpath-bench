#!/usr/bin/env python3
"""Descriptive no-fault vs injected-fault comparison; never asserts causality.

Inputs: fully verified failover series-review.json and control-series.json.
No Docker access or mutable networking actions.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import statistics
import sys


def numeric(v, name: str) -> float:
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v < 0:
        raise ValueError(f'Invalid nonnegative metric: {name}')
    return float(v)


def compare(control:dict,failover:dict)->dict:
    if control.get('status') != 'PASS' or control.get('condition') != 'NO_FAULT_CONTROL':
        raise ValueError('Control series must be completed and verified')
    if failover.get('verification') != 'PASS' or failover.get('experiment') != 'independent_netpath_series_evidence_audit':
        raise ValueError('Failover input must be independently verified review JSON')
    cs,fs=control.get('settings',{}),failover.get('settings',{})
    for key in ('protocol','seconds','interval_us','timeout_ms'):
        if cs.get(key) != fs.get(key):
            raise ValueError(f'Experimental settings mismatch: {key}')
    if cs.get('protocol') != 'udp':
        raise ValueError('Only UDP comparison is supported')
    c_runs,f_runs=control.get('runs'),failover.get('runs')
    if not isinstance(c_runs,list) or not isinstance(f_runs,list) or len(c_runs) < 2 or len(f_runs) < 2:
        raise ValueError('Both conditions require at least two independently verified runs')
    if control.get('aggregate',{}).get('runs') != len(c_runs) or failover.get('run_count') != len(f_runs):
        raise ValueError('Run-count summary does not match')
    seen=set()
    def summarize(runs, condition):
        total=success=0
        p99=[]
        for row in runs:
            if row.get('verification',row.get('validation')) != 'PASS':
                raise ValueError('Invalid per-run verification')
            fp=row.get('csv_sha256') if condition=='control' else row.get('evidence_sha256',{}).get('bgp-failover-udp.csv')
            if not isinstance(fp,str) or len(fp)!=64 or any(c not in '0123456789abcdef' for c in fp) or fp in seen:
                raise ValueError('Duplicate/invalid run sample fingerprint')
            seen.add(fp)
            attempts=numeric(row.get('attempts'),'attempts')
            successes=numeric(row.get('successes'),'successes')
            failures=numeric(row.get('unsuccessful'),'unsuccessful')
            if attempts < 1 or any(int(x)!=x for x in (attempts,successes,failures)) or successes+failures != attempts:
                raise ValueError('Inconsistent run counters')
            total+=int(attempts);success+=int(successes)
            p99.append(numeric(row['rtt_ms']['p99'],'p99'))
        return {'runs':len(runs),'attempts':total,'successful_echoes':success,
                'unsuccessful_echoes':total-success,'observed_echo_failure_ratio':(total-success)/total,
                'run_level_median_p99_ms':statistics.median(p99)}
    c=summarize(c_runs,'control'); f=summarize(f_runs,'failover')
    if control['aggregate']['attempts'] != c['attempts'] or control['aggregate']['unsuccessful'] != c['unsuccessful_echoes']:
        raise ValueError('Control aggregate contradicted by runs')
    if failover['counts']['application_echo_attempts'] != f['attempts'] or failover['counts']['unsuccessful_echoes'] != f['unsuccessful_echoes']:
        raise ValueError('Failover aggregate contradicted by runs')
    return {'schema_version':1,'comparison':'no_fault_vs_injected_primary_outage',
            'verification':'PASS','settings':{k:cs[k] for k in ('protocol','seconds','interval_us','timeout_ms')},
            'control':c,'failover':f,
            'descriptive_delta_echo_failure_ratio':f['observed_echo_failure_ratio']-c['observed_echo_failure_ratio'],
            'descriptive_delta_run_median_p99_ms':f['run_level_median_p99_ms']-c['run_level_median_p99_ms'],
            'causal_claim':'NOT_ESTABLISHED',
            'limitations':[
                'Runs are sequential Docker/WSL2 observations; background CPU load and host scheduling are uncontrolled.',
                'Echo failures are missing application replies by deadline, not proof of physical on-wire packet loss.',
                'User-space RTT is not NIC hardware latency. No PTP/hardware timestamping.',
                'Small run counts cannot establish statistical confidence, formal significance or BGP convergence time.',
                'Run-level p99 medians and failure-ratio differences are descriptive, not causal evidence.'
            ]}


def markdown(d:dict)->str:
    lines=['# NetPath Bench — No-fault versus injected-outage comparison','',
           '**Descriptive comparison only. Causality NOT established.**','',
           '| Condition | Runs | UDP echo attempts | Unsuccessful | Echo failure ratio | Median run-level p99 RTT (ms) |',
           '| --- | ---: | ---: | ---: | ---: | ---: |']
    for key,label in [('control','No intentional fault'),('failover','Primary transit stopped')]:
        r=d[key];lines.append(f'| {label} | {r["runs"]} | {r["attempts"]} | {r["unsuccessful_echoes"]} | {r["observed_echo_failure_ratio"]:.6f} | {r["run_level_median_p99_ms"]:.6f} |')
    lines+=['','## Limitations','']+['- '+s for s in d['limitations']]+['']
    return '\n'.join(lines)


def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--control',type=Path,required=True)
    p.add_argument('--failover',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--markdown',type=Path,required=True)
    a=p.parse_args(argv)
    try:
        paths=[x.resolve() for x in (a.control,a.failover,a.output,a.markdown)]
        if len(set(paths))!=len(paths) or a.output.exists() or a.markdown.exists():
            raise ValueError('Refusing to overwrite existing results or inputs')
        data=compare(json.loads(a.control.read_text(encoding='utf-8')),json.loads(a.failover.read_text(encoding='utf-8')))
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.markdown.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        a.markdown.write_text(markdown(data),encoding='utf-8')
        print(f'PASS: {data["control"]["runs"]} control / {data["failover"]["runs"]} fault runs compared descriptively')
        return 0
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
