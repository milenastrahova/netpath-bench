#!/usr/bin/env python3
"""Offline classic-PCAP Ethernet/IPv4 TCP/UDP evidence review (stdlib only).

No promiscuous capture, network access or host changes. PCAPNG is not supported.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import ipaddress
import json
from pathlib import Path
import struct

MAGICS = {b'\xd4\xc3\xb2\xa1': ('<', 1_000_000),
          b'\xa1\xb2\xc3\xd4': ('>', 1_000_000),
          b'\x4d\x3c\xb2\xa1': ('<', 1_000_000_000),
          b'\xa1\xb2\x3c\x4d': ('>', 1_000_000_000)}
MAX_PACKET = 4 * 1024 * 1024


def iter_pcap(path: Path):
    with path.open('rb') as f:
        header = f.read(24)
        if len(header) != 24 or header[:4] not in MAGICS:
            raise ValueError('Expected classic PCAP file (not PCAPNG)')
        endian, resolution = MAGICS[header[:4]]
        major, minor, _, _, snaplen, linktype = struct.unpack(endian + 'HHIIII', header[4:])
        if (major, minor) != (2, 4) or linktype != 1 or not 14 <= snaplen <= MAX_PACKET:
            raise ValueError('Unsupported PCAP version, link type or snaplen; Ethernet required')
        count = 0
        while True:
            pkthead = f.read(16)
            if not pkthead:
                return
            if len(pkthead) != 16:
                raise ValueError('Truncated PCAP packet header')
            sec, fract, incl, orig = struct.unpack(endian + 'IIII', pkthead)
            if fract >= resolution or incl > snaplen or incl > orig or incl > MAX_PACKET:
                raise ValueError('Invalid timestamp, lengths or captured packet size')
            packet = f.read(incl)
            if len(packet) != incl:
                raise ValueError('Truncated PCAP packet')
            count += 1
            if count > 2_000_000:
                raise ValueError('Capture exceeds bounded processing limit')
            yield sec + fract / resolution, packet


def decode_ether_ipv4(frame: bytes):
    if len(frame) < 14:
        return None
    ethertype = struct.unpack_from('!H', frame, 12)[0]
    offset = 14
    for _ in range(2):
        if ethertype not in (0x8100, 0x88a8):
            break
        if len(frame) < offset + 4:
            return None
        ethertype = struct.unpack_from('!H', frame, offset + 2)[0]
        offset += 4
    if ethertype != 0x0800 or len(frame) < offset + 20:
        return None
    verihl = frame[offset]
    version, ihl = verihl >> 4, (verihl & 15) * 4
    if version != 4 or ihl < 20 or len(frame) < offset + ihl:
        return None
    total = struct.unpack_from('!H', frame, offset + 2)[0]
    flags_frag = struct.unpack_from('!H', frame, offset + 6)[0]
    if total < ihl or (flags_frag & 0x3fff):
        return None  # Fragmented: do not reconstruct incomplete datagrams.
    available = min(total, len(frame) - offset)
    proto = frame[offset + 9]
    src = str(ipaddress.IPv4Address(frame[offset + 12:offset + 16]))
    dst = str(ipaddress.IPv4Address(frame[offset + 16:offset + 20]))
    data = frame[offset + ihl: offset + available]
    if proto == 17:
        if len(data) < 8:
            return None
        sp, dp, udplen, _ = struct.unpack_from('!HHHH', data)
        if udplen < 8 or udplen > total - ihl:
            return None
        payload = data[8:min(len(data), udplen)]
        seq = None
        stream = None
        if len(payload) >= 12 and payload[:4] == b'NPS1':
            stream, seq = struct.unpack_from('!II', payload, 4)
        elif len(payload) >= 16 and payload[:4] == b'MDL1':
            stream, seq = struct.unpack_from('!IQ', payload, 4)
        return {'protocol': 'UDP', 'src': src, 'dst': dst, 'sport': sp, 'dport': dp,
                'payload_bytes': max(0, udplen - 8), 'stream': stream, 'sequence': seq}
    if proto == 6:
        if len(data) < 20:
            return None
        sp, dp, seq, ack = struct.unpack_from('!HHII', data)
        header_size = (data[12] >> 4) * 4
        if header_size < 20 or len(data) < header_size:
            return None
        return {'protocol': 'TCP', 'src': src, 'dst': dst, 'sport': sp, 'dport': dp,
                'payload_bytes': max(0, len(data) - header_size), 'tcp_sequence': seq,
                'tcp_ack': ack, 'tcp_flags': data[13]}
    return None


def nearest_rank_percentile(values, pct):
    if not values:
        return None
    sorted_vals = sorted(values)
    rank = (len(sorted_vals) - 1) * (pct / 100)
    lo, hi = int(rank), min(len(sorted_vals) - 1, int(rank) + 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (rank - lo), 3)


def review(path: Path) -> dict:
    groups = defaultdict(lambda: {'count': 0, 'bytes': 0, 'last_time': None,
                                  'gaps_us': [], 'observed_sequences': set(),
                                  'highest_seq': None, 'seq_gaps': 0,
                                  'out_of_order': 0, 'duplicate_sequences': 0,
                                  'repeated_tcp_segments': 0, 'tcp_seen': set()})
    decoded = 0
    skipped = 0
    for when, frame in iter_pcap(path):
        item = decode_ether_ipv4(frame)
        if item is None:
            skipped += 1
            continue
        decoded += 1
        key = (item['protocol'], item['src'], item['sport'], item['dst'], item['dport'])
        g = groups[key]
        g['count'] += 1
        g['bytes'] += item['payload_bytes']
        if g['last_time'] is not None and when >= g['last_time']:
            g['gaps_us'].append((when - g['last_time']) * 1e6)
        g['last_time'] = when
        if item['protocol'] == 'UDP' and item['sequence'] is not None:
            sequence = (item['stream'], item['sequence'])
            if sequence in g['observed_sequences']:
                g['duplicate_sequences'] += 1
            elif g['highest_seq'] is None or sequence[0] != g['highest_seq'][0]:
                g['highest_seq'] = sequence
            elif sequence[1] > g['highest_seq'][1]:
                gap = sequence[1] - g['highest_seq'][1] - 1
                if 0 < gap <= 1_000_000:
                    g['seq_gaps'] += gap
                g['highest_seq'] = sequence
            else:
                g['out_of_order'] += 1
            g['observed_sequences'].add(sequence)
        if item['protocol'] == 'TCP' and item['payload_bytes']:
            segment = (item['tcp_sequence'], item['payload_bytes'])
            if segment in g['tcp_seen']:
                g['repeated_tcp_segments'] += 1
            g['tcp_seen'].add(segment)
    flows = []
    for key, g in sorted(groups.items()):
        proto, src, sp, dst, dp = key
        flows.append({'protocol': proto, 'source': f'{src}:{sp}', 'destination': f'{dst}:{dp}',
                      'packets': g['count'], 'payload_bytes': g['bytes'],
                      'interarrival_p50_us': nearest_rank_percentile(g['gaps_us'], 50),
                      'interarrival_p95_us': nearest_rank_percentile(g['gaps_us'], 95),
                      'observed_udp_sequence_gaps': g['seq_gaps'],
                      'observed_udp_duplicates': g['duplicate_sequences'],
                      'observed_udp_out_of_order': g['out_of_order'],
                      'repeated_tcp_payload_sequence_candidates': g['repeated_tcp_segments']})
    return {
        'schema_version': 1, 'kind': 'offline_classic_pcap_review',
        'capture_file': path.name, 'capture_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'decoded_tcp_udp_packets': decoded, 'skipped_frames': skipped,
        'protocol_counts': dict(Counter({p: sum(x['packets'] for x in flows if x['protocol'] == p)
                                         for p in ('TCP', 'UDP')})),
        'flows': flows,
        'limitations': [
            'Capture order, drops and timestamp precision can affect results.',
            'UDP sequence gaps do not demonstrate physical packet loss or application timeouts.',
            'Repeated TCP segment sequence numbers are candidates, not confirmed retransmissions.',
            'This parser supports classic Ethernet/IPv4 PCAP only, not PCAPNG, IPv6 or IP fragments.',
            'Interarrival time is NOT RTT, jitter at the NIC or end-to-end trading latency.',
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pcap', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args(argv)
    if not args.pcap.is_file():
        p.error('Input PCAP not found')
    if args.output.exists():
        p.error('Refusing to overwrite existing evidence')
    data = review(args.pcap)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f"Decoded {data['decoded_tcp_udp_packets']} packets from {len(data['flows'])} flows")
    print(f'Saved: {args.output}')


if __name__ == '__main__':
    main()
