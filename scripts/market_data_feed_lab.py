#!/usr/bin/env python3
"""Synthetic UDP market-data sequence continuity laboratory.

No real exchange connectivity. Local loopback demo and optional multicast receiver.
Missing sequences are NOT proven on-wire packet loss.
"""
from __future__ import annotations
import argparse
from collections import deque
import ipaddress
import json
from pathlib import Path
import socket
import struct
import threading
import time

MAGIC = b'MDL1'
HEADER = struct.Struct('!4sIQ')
DEFAULT_PORT = 19371
MAX_PACKET = 8192

def encode_packet(stream: int, seq: int, payload: bytes = b'') -> bytes:
    if not (1 <= stream <= 0xFFFFFFFF and 0 <= seq <= 0xFFFFFFFFFFFFFFFF):
        raise ValueError('Stream ID or sequence out of range')
    if not isinstance(payload, bytes) or len(payload) > MAX_PACKET - HEADER.size:
        raise ValueError('Invalid synthetic payload')
    return HEADER.pack(MAGIC, stream, seq) + payload

def decode_packet(data: bytes) -> tuple[int, int]:
    if len(data) < HEADER.size or len(data) > MAX_PACKET:
        raise ValueError('Invalid synthetic datagram size')
    magic, stream, seq = HEADER.unpack(data[:HEADER.size])
    if magic != MAGIC or stream == 0:
        raise ValueError('Invalid magic or stream ID')
    return stream, seq

class SequenceTracker:
    """Bounded gap and recent sequence accounting per synthetic stream."""
    def __init__(self, history_limit: int = 4096, max_gap: int = 10000):
        if history_limit < 1 or max_gap < 1:
            raise ValueError('Limits must be positive')
        self.history_limit = history_limit
        self.max_gap = max_gap
        self.streams: dict[int, dict] = {}

    def observe(self, stream: int, seq: int) -> str:
        if not (1 <= stream <= 0xFFFFFFFF and 0 <= seq <= 0xFFFFFFFFFFFFFFFF):
            raise ValueError('Invalid stream ID or sequence')
        state = self.streams.get(stream)
        if state is None:
            state = dict(highest=seq, received=0, duplicates=0, out_of_order=0,
                         missing_observed=0, gaps_recovered=0,
                         pending=set(), recent=deque(), seen=set(), discontinuities=0)
            self.streams[stream] = state
            event = 'first'
        elif seq in state['seen']:
            state['duplicates'] += 1
            state['received'] += 1
            return 'duplicate'
        elif seq > state['highest']:
            gap = seq - state['highest'] - 1
            if gap > self.max_gap:
                state['discontinuities'] += 1
                state['pending'].clear()
                event = 'discontinuity'
            elif gap:
                if len(state['pending']) + gap > self.max_gap:
                    state['pending'].clear()
                    state['discontinuities'] += 1
                    event = 'discontinuity'
                else:
                    state['pending'].update(range(state['highest'] + 1, seq))
                    state['missing_observed'] += gap
                    event = 'gap'
            else:
                event = 'in_order'
            state['highest'] = seq
        else:
            state['out_of_order'] += 1
            if seq in state['pending']:
                state['pending'].remove(seq)
                state['gaps_recovered'] += 1
                event = 'late_recovery'
            else:
                event = 'late_unknown'
        state['recent'].append(seq)
        state['seen'].add(seq)
        if len(state['recent']) > self.history_limit:
            state['seen'].discard(state['recent'].popleft())
        state['received'] += 1
        return event

    def report(self) -> dict:
        return {'method': 'synthetic_udp_sequence_continuity', 'version': 1,
                'streams': {str(k): {name: (len(value) if name == 'pending' else value)
                    for name,value in state.items() if name not in ('seen','recent')}
                    for k,state in sorted(self.streams.items())},
                'limitations': [
                    'Not observed does not mean physically lost; sender gaps, local drops and capture omissions are possible.',
                    'First received sequence establishes a baseline; earlier messages cannot be inferred.',
                    'Bounded history means extremely old duplicates cannot always be identified.',
                    'No real exchange protocol, multicast production feed or physical NIC performance is measured.'
                ]}

def process_datagrams(items: list[bytes]) -> dict:
    tracker = SequenceTracker()
    rejected = 0
    for b in items:
        try:
            tracker.observe(*decode_packet(b))
        except ValueError:
            rejected += 1
    return {**tracker.report(), 'rejected_datagrams': rejected}

def synthetic_sequence(count: int = 80) -> list[int]:
    if not (8 <= count <= 100000):
        raise ValueError('count out of range')
    vals = [i for i in range(1, count + 1) if i != 7]
    vals.insert(min(30, len(vals)), 18)
    vals.insert(min(34, len(vals)), 7)
    return vals

def run_loopback_demo(count: int = 80) -> dict:
    """Exercise actual OS UDP sockets on loopback; no Internet and no multicast."""
    packets = synthetic_sequence(count)
    received = []
    err = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(('127.0.0.1', 0))
        server.settimeout(2)
        port = server.getsockname()[1]
        def reader():
            try:
                for _ in packets:
                    data, _ = server.recvfrom(MAX_PACKET)
                    received.append(data)
            except (socket.timeout, OSError) as exc:
                err.append(str(exc))
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            for seq in packets:
                client.sendto(encode_packet(1, seq, b'simulated-data'), ('127.0.0.1', port))
                time.sleep(0.0003)
        t.join(timeout=4)
    result = process_datagrams(received)
    result.update({'transport':'udp_ipv4_loopback','sent':len(packets),
                   'received':len(received),'completed':len(received)==len(packets) and not err,
                   'receiver_errors':err})
    return result

def receive_multicast(group: str, port: int, duration: float, stream_id: int) -> dict:
    """Optional multicast listener. Only IPv4 multicast group allowed."""
    address = ipaddress.ip_address(group)
    if address.version != 4 or not address.is_multicast:
        raise ValueError('Group must be an IPv4 multicast address')
    if not (1 <= port <= 65535 and 0 < duration <= 120 and 1 <= stream_id <= 0xFFFFFFFF):
        raise ValueError('Invalid port, duration, or stream ID')
    tracker = SequenceTracker()
    rejected = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as receiver:
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        receiver.bind(('', port))
        receiver.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            socket.inet_aton(group) + socket.inet_aton('0.0.0.0'))
        receiver.settimeout(0.2)
        end=time.monotonic() + duration
        while time.monotonic() < end:
            try:
                packet, _ = receiver.recvfrom(MAX_PACKET)
                sid, seq = decode_packet(packet)
                if sid == stream_id:
                    tracker.observe(sid,seq)
            except socket.timeout:
                pass
            except ValueError:
                rejected += 1
    return {**tracker.report(),'transport':'ipv4_multicast_local_subscription',
            'group':group,'port':port,'rejected_datagrams':rejected}

def write_json_unique(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(result,f,indent=2,sort_keys=True)
        f.write('\n')

def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    demo=sub.add_parser('demo',help='Exercise a synthetic UDP feed on local loopback')
    demo.add_argument('--count',type=int,default=80)
    demo.add_argument('--output',type=Path)
    listen=sub.add_parser('listen',help='Subscribe to a multicast group you are authorized to receive')
    listen.add_argument('--group',required=True)
    listen.add_argument('--port',type=int,default=DEFAULT_PORT)
    listen.add_argument('--duration',type=float,default=5)
    listen.add_argument('--stream-id',type=int,default=1)
    listen.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        result=run_loopback_demo(args.count) if args.command=='demo' else receive_multicast(
            args.group,args.port,args.duration,args.stream_id)
        if args.output:
            write_json_unique(args.output,result)
        print(json.dumps(result,indent=2,sort_keys=True))
        return 0 if (args.command != 'demo' or result['completed']) else 2
    except (OSError,ValueError) as exc:
        parser.error(str(exc))
    return 2

if __name__=='__main__':
    raise SystemExit(main())
