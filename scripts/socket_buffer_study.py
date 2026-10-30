#!/usr/bin/env python3
"""Bounded Linux loopback UDP socket-buffer A/B study; no sysctl or host changes.

This measures application-level echoed RTT, NOT network-wire or HFT latency.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import platform
from pathlib import Path
import socket
import statistics
import struct
import threading
import time

MAGIC = b'NPS1'
PACKET = struct.Struct('!4sII')
BUFFER_PROFILES = {'baseline': 65536, 'larger_buffer': 524288}
LIMITATIONS = [
    'Loopback user-space RTT is not wire latency or one-way latency.',
    'Socket buffers are process-local; no Linux sysctl, NIC, or host setting is changed.',
    'SO_RCVBUF/SO_SNDBUF return effective values; Linux commonly doubles requested buffers.',
    'Serial echo testing does not saturate receive queues; buffer size may have no measurable benefit.',
    'RTT percentiles exclude timeouts, which are always reported separately.',
    'A difference between conditions is not causal without repeated controlled tests and independent confirmation.',
]


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if not 0 <= pct <= 100:
        raise ValueError('Invalid percentile')
    ordered = sorted(values)
    idx = (len(ordered) - 1) * pct / 100.0
    lo, hi = math.floor(idx), math.ceil(idx)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo), 3)


def linux_kernel_snapshot() -> dict:
    values = {}
    for name in ('rmem_max', 'wmem_max', 'netdev_max_backlog'):
        path = Path('/proc/sys/net/core') / name
        try:
            values[name] = path.read_text(encoding='ascii').strip()
        except (OSError, UnicodeError):
            values[name] = None
    return values


def run_trial(profile: str, requested_buffer: int, count: int, interval_ms: float,
              timeout_ms: int, warmup: int = 10, server_port: int = 0) -> tuple[dict, list[dict]]:
    if profile not in BUFFER_PROFILES or not (10 <= count <= 100000):
        raise ValueError('Invalid profile or sample count')
    if not (4096 <= requested_buffer <= 4 * 1024 * 1024):
        raise ValueError('Invalid requested socket buffer')
    if not (0 <= interval_ms <= 100 and 1 <= timeout_ms <= 5000 and 0 <= warmup <= 10000 and 0 <= server_port <= 65535):
        raise ValueError('Invalid timing or warmup')
    stopper = threading.Event()
    server_errors = []
    session = (time.monotonic_ns() & 0xFFFFFFFF)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, \
         socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, requested_buffer)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, requested_buffer)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, requested_buffer)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, requested_buffer)
        actual = {
            'client_rcvbuf': client.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF),
            'client_sndbuf': client.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF),
            'server_rcvbuf': server.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF),
            'server_sndbuf': server.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF),
        }
        server.bind(('127.0.0.1', server_port))
        client.bind(('127.0.0.1', 0))
        server_addr = server.getsockname()
        client_addr = client.getsockname()
        server.settimeout(0.1)
        def responder():
            while not stopper.is_set():
                try:
                    payload, addr = server.recvfrom(4096)
                    if len(payload) >= PACKET.size and payload[:4] == MAGIC:
                        server.sendto(payload, addr)
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not stopper.is_set():
                        server_errors.append(str(exc))
                    return
        worker = threading.Thread(target=responder, name='udp-loopback-echo', daemon=True)
        worker.start()
        samples = []
        try:
            for seq in range(warmup + count):
                message = PACKET.pack(MAGIC, session, seq) + b'Z' * (64 - PACKET.size)
                sent_ns = time.monotonic_ns()
                client.sendto(message, server_addr)
                deadline = time.monotonic() + timeout_ms / 1000.0
                elapsed_us = None
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    client.settimeout(remaining)
                    try:
                        response, origin = client.recvfrom(4096)
                    except socket.timeout:
                        break
                    if origin == server_addr and response == message:
                        elapsed_us = (time.monotonic_ns() - sent_ns) / 1000
                        break
                if seq >= warmup:
                    samples.append({'sequence': seq - warmup, 'status': 'ok' if elapsed_us is not None else 'timeout',
                                    'rtt_us': round(elapsed_us, 3) if elapsed_us is not None else ''})
                if interval_ms:
                    time.sleep(interval_ms / 1000)
        finally:
            stopper.set()
            worker.join(timeout=1.0)
    if server_errors or worker.is_alive():
        raise RuntimeError(f'Responder failure: {server_errors or "thread did not stop"}')
    good = [row['rtt_us'] for row in samples if row['status'] == 'ok']
    summary = {
        'capture_session_id': session, 'capture_client_port': client_addr[1],
        'capture_server_port': server_addr[1], 'capture_warmup': warmup,
        'profile': profile, 'requested_socket_buffer': requested_buffer,
        'effective_socket_buffers': actual, 'attempted': count, 'replies': len(good),
        'application_timeouts': count - len(good), 'rtt_units': 'microseconds',
        'rtt_p50_us': percentile(good, 50), 'rtt_p95_us': percentile(good, 95),
        'rtt_p99_us': percentile(good, 99), 'rtt_max_us': max(good, default=None),
        'rtt_median_abs_successive_delta_us': (round(statistics.median([abs(a - b) for a, b in zip(good, good[1:])]), 3)
                                               if len(good) >= 2 else None),
    }
    return summary, samples


def write_study(output_dir: Path, repetitions: int, count: int, interval_ms: float,
                timeout_ms: int, warmup: int = 10, server_port: int = 0) -> dict:
    if not (1 <= repetitions <= 20):
        raise ValueError('Repetitions must be between 1 and 20')
    output_dir.mkdir(parents=True, exist_ok=False)
    runs = []
    for repeat in range(repetitions):
        # AB/BA ordering reduces simple drift effects; it does not ensure causal identification.
        names = ('baseline', 'larger_buffer') if repeat % 2 == 0 else ('larger_buffer', 'baseline')
        for name in names:
            details, samples = run_trial(name, BUFFER_PROFILES[name], count, interval_ms, timeout_ms, warmup, server_port)
            fn = f'{repeat + 1:02d}_{name}.csv'
            path = output_dir / fn
            with path.open('x', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['sequence', 'status', 'rtt_us'])
                writer.writeheader()
                writer.writerows(samples)
            details['repeat'] = repeat + 1
            details['csv'] = fn
            details['csv_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            runs.append(details)
    result = {
        'schema_version': 1, 'kind': 'linux_socket_buffer_loopback_study',
        'platform': platform.platform(), 'python': platform.python_version(),
        'kernel_params_read_only': linux_kernel_snapshot(),
        'configuration': {'repetitions': repetitions, 'count_per_trial': count,
                          'interval_ms': interval_ms, 'timeout_ms': timeout_ms, 'warmup_per_trial': warmup, 'server_port': server_port},
        'runs': runs, 'limitations': LIMITATIONS,
        'interpretation': 'Descriptive A/B observations only: no claim of optimization, wire loss or HFT performance.',
    }
    (output_dir / 'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--repetitions', type=int, default=3)
    p.add_argument('--count', type=int, default=200)
    p.add_argument('--interval-ms', type=float, default=1)
    p.add_argument('--timeout-ms', type=int, default=200)
    p.add_argument('--warmup', type=int, default=10)
    p.add_argument('--server-port', type=int, default=0, help='Bind loopback UDP responder to this port for isolated tcpdump capture')
    args = p.parse_args(argv)
    if platform.system() != 'Linux':
        p.error('Run in WSL2 or a Linux container; Windows host settings must remain unchanged')
    if args.output_dir.exists():
        p.error('Output directory already exists; refusing to overwrite evidence')
    if args.output_dir.parent and not args.output_dir.parent.exists():
        args.output_dir.parent.mkdir(parents=True)
    result = write_study(args.output_dir, args.repetitions, args.count, args.interval_ms,
                         args.timeout_ms, args.warmup, args.server_port)
    for run in result['runs']:
        print(f"{run['repeat']} {run['profile']}: replies={run['replies']}/{run['attempted']}, "
              f"p99={run['rtt_p99_us']} us, timeouts={run['application_timeouts']}")
    print(f"Saved evidence: {args.output_dir / 'summary.json'}")


if __name__ == '__main__':
    main()
