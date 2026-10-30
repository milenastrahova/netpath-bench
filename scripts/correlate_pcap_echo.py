#!/usr/bin/env python3
"""Reconcile socket-buffer CSV outcomes with observed NPS1 classic-PCAP UDP frames.

Capture completeness is not application delivery or physical on-wire packet loss.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from packet_trace_review import iter_pcap, decode_ether_ipv4
from audit_socket_study import audit

def correlate(summary_file: Path, pcap_file: Path, server_port: int) -> dict:
    if not 1 <= server_port <= 65535:
        raise ValueError('Invalid local echo port')
    app_audit = audit(summary_file)
    summary = json.loads(summary_file.read_text(encoding='utf-8'))
    if summary.get('configuration', {}).get('server_port') != server_port:
        raise ValueError('Server port does not match the recorded trial')
    observations = Counter()
    unrelated = 0
    for _, frame in iter_pcap(pcap_file):
        item = decode_ether_ipv4(frame)
        if not item or item['protocol'] != 'UDP' or item['stream'] is None or item['sequence'] is None:
            unrelated += 1
            continue
        if item['src'] != '127.0.0.1' or item['dst'] != '127.0.0.1':
            unrelated += 1
            continue
        if item['dport'] == server_port:
            direction = 'request'
            client_port = item['sport']
        elif item['sport'] == server_port:
            direction = 'reply'
            client_port = item['dport']
        else:
            unrelated += 1
            continue
        observations[(item['stream'], client_port, item['sequence'], direction)] += 1

    expected_keys = set()
    runs = []
    for run in summary['runs']:
        session = run.get('capture_session_id')
        client_port = run.get('capture_client_port')
        warmup = run.get('capture_warmup')
        if not all(type(x) is int for x in (session, client_port, warmup)):
            raise ValueError('Capture correlation metadata missing: rerun with current runner')
        if not 0 <= session <= 0xffffffff or not 1 <= client_port <= 65535 or not 0 <= warmup <= 10000:
            raise ValueError('Invalid capture metadata')
        if run.get('capture_server_port') != server_port:
            raise ValueError('Run server-port mismatch')
        csv_file = summary_file.parent / run['csv']
        with csv_file.open(newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        paired = requests = replies = missing_req = missing_rep = duplicates = 0
        app_with_pair = 0
        for i in range(warmup + len(rows)):
            req_key = (session, client_port, i, 'request')
            rep_key = (session, client_port, i, 'reply')
            if req_key in expected_keys or rep_key in expected_keys:
                raise ValueError('Reused session/client/sequence across runs')
            expected_keys.update((req_key, rep_key))
            req, rep = observations[req_key], observations[rep_key]
            requests += bool(req)
            replies += bool(rep)
            paired += bool(req and rep)
            missing_req += not bool(req)
            missing_rep += not bool(rep)
            duplicates += max(req - 1, 0) + max(rep - 1, 0)
            if i >= warmup and req and rep and rows[i - warmup]['status'] == 'ok':
                app_with_pair += 1
        runs.append({
            'repeat': run['repeat'], 'profile': run['profile'],
            'application_attempts': run['attempted'], 'application_replies': run['replies'],
            'observed_requests_including_warmup': requests,
            'observed_replies_including_warmup': replies,
            'observed_request_reply_pairs_including_warmup': paired,
            'missing_request_observations': missing_req,
            'missing_reply_observations': missing_rep,
            'duplicate_capture_observations': duplicates,
            'application_replies_with_both_capture_sides': app_with_pair
        })
    unexpected = sum(v for k, v in observations.items() if k not in expected_keys)
    seen = sum(observations.values())
    complete = all(
        r['missing_request_observations'] == 0 and
        r['missing_reply_observations'] == 0 and
        r['duplicate_capture_observations'] == 0 for r in runs
    )
    return {
        'schema_version': 1, 'kind': 'socket_pcap_application_correlation',
        'status': 'PASS' if seen > 0 and unexpected == 0 and complete else 'REVIEW',
        'application_csv_integrity': app_audit['status'],
        'application_attempts': app_audit['attempts'],
        'application_replies': app_audit['replies'],
        'application_timeouts': app_audit['application_timeouts'],
        'pcap_sha256': hashlib.sha256(pcap_file.read_bytes()).hexdigest(),
        'observed_udp_echo_frames': seen,
        'unrelated_or_unrecognized_frames': unrelated,
        'unexpected_nps1_frames': unexpected,
        'runs': runs,
        'interpretation': 'PCAP completeness is not application delivery. Missing frames may reflect capture loss or late capture startup, not wire loss. PCAP timestamps are not NIC or one-way wire latency.'
    }

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--summary', type=Path, required=True)
    p.add_argument('--pcap', type=Path, required=True)
    p.add_argument('--server-port', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(argv)
    if args.output.exists():
        p.error('Refusing to overwrite existing evidence')
    data = correlate(args.summary, args.pcap, args.server_port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: data[k] for k in (
        'status', 'application_attempts', 'application_replies',
        'application_timeouts', 'observed_udp_echo_frames', 'unexpected_nps1_frames')}, indent=2))
    if data['status'] != 'PASS':
        raise SystemExit('PCAP review needs manual attention; not a complete capture')

if __name__ == '__main__':
    main()
