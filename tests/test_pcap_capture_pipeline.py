"""Offline PCAP fixtures for per-session UDP trace/application correlation."""
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from correlate_pcap_echo import correlate
from packet_trace_review import review
from socket_buffer_study import percentile

def packet(session,sequence,client_port,server_port,reply):
    payload=struct.pack('!4sII',b'NPS1',session,sequence)
    udp=struct.pack('!HHHH',server_port if reply else client_port,
                    client_port if reply else server_port,len(payload)+8,0)+payload
    ip=bytearray(20)
    ip[0]=0x45
    struct.pack_into('!H',ip,2,20+len(udp))
    ip[8]=64
    ip[9]=17
    ip[12:16]=bytes([127,0,0,1])
    ip[16:20]=bytes([127,0,0,1])
    return bytes(12)+b'\x08\x00'+bytes(ip)+udp

def write_pcap(path,frames):
    with path.open('wb') as f:
        f.write(b'\xd4\xc3\xb2\xa1'+struct.pack('<HHIIII',2,4,0,0,65535,1))
        for i,p in enumerate(frames):
            f.write(struct.pack('<IIII',100,i*100,len(p),len(p)))
            f.write(p)

def fixture(root,missing=False):
    root.mkdir()
    csv_file=root/'trial.csv'
    with csv_file.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['sequence','status','rtt_us'])
        w.writeheader()
        w.writerows([{'sequence':0,'status':'ok','rtt_us':10.0},
                     {'sequence':1,'status':'ok','rtt_us':20.0}])
    summary={'schema_version':1,'kind':'linux_socket_buffer_loopback_study',
        'configuration':{'server_port':19371},
        'runs':[{'profile':'baseline','repeat':1,'capture_session_id':100,
            'capture_client_port':44000,'capture_server_port':19371,
            'capture_warmup':1,'csv':'trial.csv',
            'csv_sha256':hashlib.sha256(csv_file.read_bytes()).hexdigest(),
            'attempted':2,'replies':2,'application_timeouts':0,
            'rtt_p50_us':percentile([10,20],50),
            'rtt_p95_us':percentile([10,20],95),
            'rtt_p99_us':percentile([10,20],99)}]}
    (root/'summary.json').write_text(json.dumps(summary),encoding='utf-8')
    frames=[]
    for seq in range(3):
        frames.append(packet(100,seq,44000,19371,False))
        if not missing or seq != 2:
            frames.append(packet(100,seq,44000,19371,True))
    write_pcap(root/'trial.pcap',frames)
    return root/'summary.json',root/'trial.pcap'

class CorrelationTests(unittest.TestCase):
    def test_complete_round_trips(self):
        with tempfile.TemporaryDirectory() as temp:
            summary,pcap=fixture(Path(temp)/'sample')
            result=correlate(summary,pcap,19371)
            self.assertEqual(result['status'],'PASS')
            self.assertEqual(result['observed_udp_echo_frames'],6)
            self.assertEqual(result['runs'][0]['application_replies_with_both_capture_sides'],2)
            self.assertEqual(result['runs'][0]['missing_reply_observations'],0)
            self.assertEqual(review(pcap)['decoded_tcp_udp_packets'],6)

    def test_missing_capture_is_not_application_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            summary,pcap=fixture(Path(temp)/'sample',missing=True)
            result=correlate(summary,pcap,19371)
            self.assertEqual(result['status'],'REVIEW')
            self.assertEqual(result['application_timeouts'],0)
            self.assertEqual(result['runs'][0]['missing_reply_observations'],1)

    def test_wrong_port_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            summary,pcap=fixture(Path(temp)/'sample')
            with self.assertRaises(ValueError): correlate(summary,pcap,19372)

    def test_tampered_csv_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            summary,pcap=fixture(Path(temp)/'sample')
            with (summary.parent/'trial.csv').open('ab') as f: f.write(b'bad')
            with self.assertRaises(ValueError): correlate(summary,pcap,19371)

    def test_unexpected_session_flagged(self):
        with tempfile.TemporaryDirectory() as temp:
            summary,pcap=fixture(Path(temp)/'sample')
            frames=[packet(100,i,44000,19371,b) for i in range(3) for b in (False,True)]
            frames.append(packet(400,0,45000,19371,False))
            write_pcap(pcap,frames)
            self.assertEqual(correlate(summary,pcap,19371)['status'],'REVIEW')

if __name__=='__main__': unittest.main()
