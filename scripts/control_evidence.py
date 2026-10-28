#!/usr/bin/env python3
"""Fail-closed offline verifier for FRRouting baseline (NO outage) UDP captures.

Standard library only. Never calls Docker or changes network configuration.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import zipfile
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.analyze_trial import parse_utc, summary

BASENAMES = ('bgp-baseline-udp.json','bgp-baseline-udp.csv','bgp-baseline-udp-events.json')
MAX_FILE_BYTES = 12_000_000


def check_triplet(files: dict[str, bytes]) -> dict:
    if set(files) != set(BASENAMES):
        raise ValueError('Baseline evidence requires exactly the three canonical names')
    probe = json.loads(files[BASENAMES[0]].decode('utf-8-sig'))
    events = json.loads(files[BASENAMES[2]].decode('utf-8-sig'))
    rows = list(csv.DictReader(io.StringIO(files[BASENAMES[1]].decode('utf-8-sig'))))
    if not 1 <= len(rows) <= 100000 or set(rows[0]) != {'sequence','start_offset_ms','status','rtt_ms'}:
        raise ValueError('Invalid baseline CSV schema or count')
    if probe.get('protocol') != 'udp' or events.get('mode') != 'baseline' or events.get('protocol') != 'udp':
        raise ValueError('Not a UDP baseline control capture')
    if events.get('status') != 'CAPTURED' or events.get('probe_exit_code') not in (0, 2):
        raise ValueError('Control experiment not captured successfully')
    phases = [x['phase'] for x in events.get('events', [])]
    if phases != ['server_ready', 'probe_command_started', 'probe_finished']:
        raise ValueError('Control evidence contains unexpected events (possibly a fault injection)')
    ts = [parse_utc(x['utc']) for x in events['events']]
    if ts != sorted(ts):
        raise ValueError('Control event timestamps out of order')
    if parse_utc(probe['ended_at_utc']) < parse_utc(probe['started_at_utc']):
        raise ValueError('Probe start/end timestamps out of order')
    if (probe.get('source_ip'), probe.get('host')) != ('10.10.10.1','10.40.40.1'):
        raise ValueError('Unexpected BGP lab endpoint addresses')
    if (events.get('probe_source_ip'), events.get('server_ip')) != ('10.10.10.1','10.40.40.1'):
        raise ValueError('Probe and control event endpoint mismatch')
    if probe.get('attempted') != len(rows) or probe.get('sample_count') != len(rows) or events.get('attempted') != len(rows):
        raise ValueError('Sample counts do not match')
    seen = {'ok': 0,'timeout': 0,'send_error': 0,'invalid_echo': 0}
    samples = []
    prev = -1
    for i, row in enumerate(rows):
        if set(row) != {'sequence','start_offset_ms','status','rtt_ms'} or int(row['sequence']) != i:
            raise ValueError('Noncontiguous or invalid sample sequence')
        t = float(row['start_offset_ms'])
        if not math.isfinite(t) or not prev <= t or t < 0:
            raise ValueError('Unordered sample time offsets')
        prev = t
        status = row['status']
        if status not in seen:
            raise ValueError('Invalid sample status')
        seen[status] += 1
        v = None if row['rtt_ms'] == 'null' else float(row['rtt_ms'])
        if (status == 'ok') != (v is not None) or (v is not None and (v < 0 or not math.isfinite(v))):
            raise ValueError('Invalid sample RTT/status combination')
        samples.append((t, status, v))
    for key,count in (('successful_echoes',seen['ok']),('timeouts',seen['timeout']),('errors',seen['send_error']),('unexpected_replies',seen['invalid_echo'])):
        if probe.get(key) != count:
            raise ValueError('Probe summary/CSV mismatch: '+key)
    if events.get('successful_echoes') != seen['ok'] or events.get('echo_timeouts') != seen['timeout']:
        raise ValueError('Control events/CSV mismatch')
    duration = float(probe['observation_duration_ms'])
    if not math.isfinite(duration) or duration <= 0 or prev > duration + 10:
        raise ValueError('Invalid observation duration')
    bad = len(rows) - seen['ok']
    if abs(probe.get('echo_failure_ratio', -1) - bad / len(rows)) > 0.000002:
        raise ValueError('Echo failure ratio inconsistent')
    computed = summary(samples)
    for key in ('mean','p50','p95','p99','p999','max'):
        stated = probe.get('rtt_ms',{}).get(key)
        calculated = computed['rtt_ms'][key]
        if stated is None and calculated is None:
            continue
        if stated is None or calculated is None or abs(stated-calculated) > 0.00005:
            raise ValueError('RTT aggregate mismatch: '+key)
    return {
        'verification':'PASS', 'condition':'NO_FAULT_CONTROL',
        'attempts':len(rows),'successes':seen['ok'],'unsuccessful':bad,
        'observed_echo_failure_ratio':bad / len(rows),
        'rtt_ms': computed['rtt_ms'],
        'csv_sha256':hashlib.sha256(files[BASENAMES[1]]).hexdigest(),
        'sha256':{name:hashlib.sha256(files[name]).hexdigest() for name in BASENAMES},
        'limitations':'Userspace application echo RTT; a missing echo is NOT verified physical packet loss. Control experiment did not intentionally stop any BGP router.'
    }


def read_baseline_bundle(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or set(names) != set(BASENAMES):
            raise ValueError('Invalid baseline bundle member names')
        if any(i.file_size > MAX_FILE_BYTES or i.is_dir() for i in infos) or sum(i.file_size for i in infos) > 2 * MAX_FILE_BYTES:
            raise ValueError('Excessive or invalid baseline evidence size')
        return check_triplet({n:z.read(n) for n in BASENAMES})


def bundle_baseline(reports: Path, run_id: str, output: Path) -> Path:
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}',run_id):
        raise ValueError('Invalid run ID')
    if output.exists():
        raise FileExistsError('Refusing to overwrite control bundle')
    source = [reports / f'bgp-baseline-udp-{run_id}{suffix}' for suffix in ('.json','.csv','-events.json')]
    if any(not x.is_file() or x.stat().st_size > MAX_FILE_BYTES for x in source):
        raise ValueError('Missing or oversized baseline input file')
    check_triplet({n:p.read_bytes() for n,p in zip(BASENAMES,source)})
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for src,dst in zip(source,BASENAMES):
            z.write(src,arcname=dst)
    return output

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True)
    a = p.parse_args()
    print(json.dumps(read_baseline_bundle(a.bundle),indent=2,allow_nan=False))
