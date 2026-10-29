#!/usr/bin/env python3
"""Verify original 29 October 2026 TCP/UDP userspace evidence without network access.

Offline verifier: ZIP CRC, source SHA-256, CSV sequences, UTC timing,
summary counts, nearest-rank percentiles and adjacent absolute RTT differences.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import sys
import zipfile

SOURCE_ARCHIVE_SHA256 = '9914f7a4cd7259f1f43b53644b3ba79320fc7f38d8665b8e0ebacdb951526d81'
SOURCES = {
    'udp.json': '521a5096ea3ad5d8dba4e984c71ee1382531459abf7185cef7b6f188776cce67',
    'udp.csv': '6ac0de68c6300c0968fbbec2e25a84eb3c0665d94e8063d3d1a9bd51fe9bae0d',
    'tcp.json': 'd214090ce33c85ccfe138056ac0701ae72d98970d05de1fc366c32a4eadaf2aa',
    'tcp.csv': '98b88caf7c0d9022fa5d8c22766e1cd3fcfcbacc7859d1af491edf02719096e8',
}
FIELDS = ('sequence', 'start_offset_ms', 'status', 'rtt_ms')

def require(condition, reason):
    if not condition:
        raise ValueError(reason)

def numeric(x, name):
    try:
        f=float(x)
    except (ValueError, TypeError) as e:
        raise ValueError(f'Invalid {name}') from e
    require(math.isfinite(f), f'Non-finite {name}')
    return f

def rank(values, percentile):
    require(values, 'No successful RTT values')
    return sorted(values)[math.ceil(percentile*len(values))-1]

def compare(a, b, key):
    require(abs(a-numeric(b,key)) <= 0.0000011, f'{key} CSV/JSON mismatch: {a} != {b}')

def check_pair(protocol, raw_json, raw_csv):
    report=json.loads(raw_json.decode('utf-8'))
    rows=list(csv.DictReader(io.StringIO(raw_csv.decode('utf-8'))))
    require(len(rows)==500, f'{protocol}: expected 500 original records')
    require(list(rows[0])==list(FIELDS), f'{protocol}: unexpected CSV header')
    require(report.get('schema_version')==1 and report.get('experiment')=='app_echo_rtt', f'{protocol}: wrong schema')
    require(report.get('protocol')==protocol and report.get('host')=='server', f'{protocol}: wrong protocol/host')
    require(report.get('port')==9000 and report.get('packet_bytes')==64, f'{protocol}: wrong port or payload')
    require(report.get('attempted')==500 and report.get('sample_count')==500, f'{protocol}: attempt/sample mismatch')
    require(report.get('successful_echoes')==500, f'{protocol}: successful echoes mismatch')
    require(all(report.get(k)==0 for k in ('timeouts','errors','unexpected_replies')), f'{protocol}: unexpected failures')
    compare(0, report['echo_failure_ratio'], f'{protocol}.echo_failure_ratio')
    offsets=[]; rtts=[]
    for i,row in enumerate(rows):
        require(set(row)==set(FIELDS), f'{protocol}: wrong columns at row {i}')
        try:
            seq=int(row['sequence'])
        except (TypeError,ValueError) as e:
            raise ValueError(f'{protocol}: invalid sequence') from e
        require(seq==i, f'{protocol}: noncontiguous sequence at {i}')
        off=numeric(row['start_offset_ms'], 'offset')
        require(off>=0 and (not offsets or off>offsets[-1]), f'{protocol}: nonmonotonic sample offsets')
        require(row['status']=='ok', f'{protocol}: unexpected status')
        rtt=numeric(row['rtt_ms'],'rtt')
        require(rtt>=0, f'{protocol}: negative RTT')
        offsets.append(off);rtts.append(rtt)
    metrics={'min':min(rtts),'mean':statistics.mean(rtts),'p50':rank(rtts,.5),
             'p95':rank(rtts,.95),'p99':rank(rtts,.99),'p999':rank(rtts,.999),
             'max':max(rtts)}
    for key,value in metrics.items():
        compare(value,report['rtt_ms'][key],f'{protocol}.{key}')
    diffs=[abs(b-a) for a,b in zip(rtts,rtts[1:])]
    differences={'mean':statistics.mean(diffs),'p99':rank(diffs,.99)}
    for key,value in differences.items():
        compare(value,report['consecutive_abs_rtt_difference_ms'][key],f'{protocol}.difference.{key}')
    elapsed=numeric(report['observation_duration_ms'],'duration')
    require(elapsed>0 and offsets[-1]+rtts[-1]<=elapsed+2,f'{protocol}: samples beyond duration')
    try:
        started=datetime.fromisoformat(report['started_at_utc'].replace('Z','+00:00'))
        ended=datetime.fromisoformat(report['ended_at_utc'].replace('Z','+00:00'))
    except (KeyError,TypeError,ValueError) as e:
        raise ValueError(f'{protocol}: invalid timestamps') from e
    require(0 <= (ended-started).total_seconds()*1000 and
            abs((ended-started).total_seconds()*1000-elapsed)<2,
            f'{protocol}: rounded UTC and monotonic duration disagree')
    return {'protocol':protocol,'samples':len(rows),'successes':len(rtts),
            'rtt_ms':{k:round(v,6) for k,v in metrics.items()},
            'adjacent_abs_rtt_difference_ms':{k:round(v,6) for k,v in differences.items()},
            'max_rtt_sequence':max(range(len(rtts)),key=lambda i:rtts[i])}

def verify_zip(path):
    raw=Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==SOURCE_ARCHIVE_SHA256,
            'Source archive SHA-256 mismatch; only the reviewed original ZIP is accepted')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        info=z.infolist()
        require(len(info)==4 and set(i.filename for i in info)==set(SOURCES),
                'Unexpected ZIP contents or duplicate names')
        require(all(not i.is_dir() and i.file_size<5_000_000 for i in info),
                'Oversize or invalid ZIP members')
        entries={name:z.read(name) for name in SOURCES}
    for name,expected in SOURCES.items():
        require(hashlib.sha256(entries[name]).hexdigest()==expected,
                f'{name}: SHA-256 mismatch')
    return {
        'verification':'PASS',
        'source_archive_sha256':SOURCE_ARCHIVE_SHA256,
        'total_attempted':1000,
        'runs':{p:check_pair(p,entries[p+'.json'],entries[p+'.csv']) for p in ('udp','tcp')},
        'limits':'Internal data consistency, not measurement origin authentication or physical loss/one-way latency.',
    }

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_zip',type=Path,help='Original, unmodified NetPath_Evidence.zip')
    args=parser.parse_args(argv)
    try:
        report=verify_zip(args.source_zip)
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,json.JSONDecodeError,UnicodeDecodeError) as exc:
        print('EVIDENCE VERIFICATION FAILED:',exc,file=sys.stderr)
        return 1
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
