"""Tests for additive Linux socket/PCAP portfolio extension."""
import importlib.util
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPT))
from socket_buffer_study import percentile, run_trial, write_study
from audit_socket_study import audit
from packet_trace_review import review, iter_pcap, decode_ether_ipv4


def mk_ipv4(proto, body):
    # No IP checksum check: parser deliberately decodes stored capture headers.
    head = bytearray(20)
    head[0] = 0x45
    struct.pack_into('!H', head, 2, 20 + len(body))
    head[8] = 64
    head[9] = proto
    head[12:16] = bytes([127, 0, 0, 1])
    head[16:20] = bytes([127, 0, 0, 2])
    eth = bytes(12) + b'\x08\x00'
    return eth + bytes(head) + body


def udp_packet(seq):
    payload = struct.pack('!4sII', b'NPS1', 55, seq)
    header = struct.pack('!HHHH', 9000, 9001, 8 + len(payload), 0)
    return mk_ipv4(17, header + payload)


def tcp_packet(seq):
    tcp = bytearray(20)
    struct.pack_into('!HHII', tcp, 0, 5000, 5001, seq, 0)
    tcp[12] = 0x50
    tcp[13] = 0x18
    return mk_ipv4(6, bytes(tcp) + b'abcd')


def write_pcap(path, packets):
    with path.open('wb') as f:
        f.write(b'\xd4\xc3\xb2\xa1')
        f.write(struct.pack('<HHIIII', 2, 4, 0, 0, 65535, 1))
        for i, p in enumerate(packets):
            f.write(struct.pack('<IIII', 100, i * 1000, len(p), len(p)))
            f.write(p)


class PcapReviewTests(unittest.TestCase):
    def test_sequence_gap_duplicate_tcp_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.pcap'
            write_pcap(path, [udp_packet(1), udp_packet(3), udp_packet(3),
                              udp_packet(2), tcp_packet(100), tcp_packet(100)])
            data = review(path)
            self.assertEqual(data['decoded_tcp_udp_packets'], 6)
            udp = next(x for x in data['flows'] if x['protocol'] == 'UDP')
            tcp = next(x for x in data['flows'] if x['protocol'] == 'TCP')
            self.assertEqual(udp['observed_udp_sequence_gaps'], 1)
            self.assertEqual(udp['observed_udp_duplicates'], 1)
            self.assertEqual(udp['observed_udp_out_of_order'], 1)
            self.assertEqual(tcp['repeated_tcp_payload_sequence_candidates'], 1)
            self.assertGreater(udp['interarrival_p95_us'], 0)

    def test_truncated_pcap_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.pcap'
            path.write_bytes(b'\xd4\xc3\xb2\xa1' + bytes(10))
            with self.assertRaises(ValueError):
                list(iter_pcap(path))

    def test_not_ipv4_skipped(self):
        self.assertIsNone(decode_ether_ipv4(b'\x00' * 14))


class SocketStudyTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(percentile([1, 2, 3], 50), 2)
        self.assertIsNone(percentile([], 95))
        with self.assertRaises(ValueError):
            percentile([1], 101)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux loopback experiment only')
    def test_socket_loopback_measurement_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'new-study'
            data = write_study(output, repetitions=1, count=12,
                               interval_ms=0.1, timeout_ms=200, warmup=2)
            self.assertEqual(len(data['runs']), 2)
            checked = audit(output / 'summary.json')
            self.assertEqual(checked['status'], 'PASS')
            self.assertEqual(checked['attempts'], 24)
            self.assertGreater(checked['replies'], 0)
            with self.assertRaises(FileExistsError):
                write_study(output, repetitions=1, count=12,
                            interval_ms=0, timeout_ms=100)
            bad = output / data['runs'][0]['csv']
            bad.write_bytes(bad.read_bytes() + b'junk\n')
            with self.assertRaises(ValueError):
                audit(output / 'summary.json')


if __name__ == '__main__':
    unittest.main()
