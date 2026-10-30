#!/usr/bin/env python3
"""Independently recheck emitted CSV, hashes and summary stats for socket-buffer study."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from socket_buffer_study import percentile


def audit(summary_file: Path) -> dict:
    root = summary_file.parent
    data = json.loads(summary_file.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or data.get('kind') != 'linux_socket_buffer_loopback_study':
        raise ValueError('Unexpected study schema')
    attempts = replies = timeouts = 0
    for run in data['runs']:
        name = run['csv']
        if Path(name).name != name or not name.endswith('.csv'):
            raise ValueError('Unsafe CSV path')
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != run['csv_sha256']:
            raise ValueError(f'CSV hash mismatch: {name}')
        rows = list(csv.DictReader(raw.decode('utf-8').splitlines()))
        if len(rows) != run['attempted']:
            raise ValueError(f'Unexpected row count: {name}')
        ok = []
        n_timeout = 0
        for i, row in enumerate(rows):
            if set(row) != {'sequence', 'status', 'rtt_us'} or int(row['sequence']) != i:
                raise ValueError(f'Invalid sequence/columns: {name}')
            if row['status'] == 'ok':
                value = float(row['rtt_us'])
                if not (0 <= value < 1e9):
                    raise ValueError('Invalid RTT')
                ok.append(value)
            elif row['status'] == 'timeout' and row['rtt_us'] == '':
                n_timeout += 1
            else:
                raise ValueError(f'Invalid status: {name}')
        if len(ok) != run['replies'] or n_timeout != run['application_timeouts']:
            raise ValueError(f'Counts mismatch: {name}')
        for p in (50, 95, 99):
            if percentile(ok, p) != run[f'rtt_p{p}_us']:
                raise ValueError(f'p{p} mismatch: {name}')
        attempts += len(rows)
        replies += len(ok)
        timeouts += n_timeout
    return {'status': 'PASS', 'runs': len(data['runs']), 'attempts': attempts,
            'replies': replies, 'application_timeouts': timeouts,
            'evidence': str(summary_file),
            'interpretation': 'Integrity check only; not a demonstration of latency optimization.'}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('summary', type=Path)
    args = p.parse_args(argv)
    print(json.dumps(audit(args.summary), indent=2))


if __name__ == '__main__':
    main()
