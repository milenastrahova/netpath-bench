#!/usr/bin/env python3
"""Run-level comparison of 2-50 independently collected NetPath Bench evidence bundles.

Never pools individual samples across runs; reports per-run statistics and the
median of per-run p99s only. Runs need the same lab/protocol/settings for causal comparison.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import statistics
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.review_evidence import read_evidence_zip,build_review,FIELDS

def compare(paths:list[pathlib.Path])->dict:
    if not 2<=len(paths)<=50:raise ValueError('Supply 2 to 50 unique evidence ZIP files')
    result=[];unique=set()
    for path in paths:
        files=read_evidence_zip(path)
        review,_=build_review(files)
        fingerprint=review['evidence_sha256'][FIELDS[1]]
        if fingerprint in unique:raise ValueError('Duplicate sample CSV evidence (not independent run)')
        unique.add(fingerprint)
        result.append({'file':path.name,'evidence_csv_sha256':fingerprint,
                       'attempts':review['counts']['attempted'],
                       'missing_echoes':review['counts']['missing_or_invalid_echoes'],
                       'failure_ratio':review['counts']['application_echo_failure_ratio'],
                       'mean_rtt_ms':review['rtt_ms']['mean'],
                       'p99_rtt_ms':review['rtt_ms']['p99'],
                       'p999_rtt_ms':review['rtt_ms']['p999']})
    return {'schema_version':1,'description':'comparison of separate field runs; not pooled samples',
            'runs':result,'run_count':len(result),
            'run_level_median_p99_ms':statistics.median(x['p99_rtt_ms'] for x in result),
            'runs_with_missing_echoes':sum(x['missing_echoes']>0 for x in result),
            'limitations':'Independent runs may differ in CPU load, clock skew, Docker scheduling, and route state. No causal inference or network wire loss claims.'}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('evidence_zips',type=pathlib.Path,nargs='+')
    p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args(argv)
    try:
        if a.output.exists(): raise ValueError('Refusing to overwrite existing comparison')
        data=compare(a.evidence_zips)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        print(f'PASS: {data["run_count"]} unique runs; output={a.output}')
        return 0
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
