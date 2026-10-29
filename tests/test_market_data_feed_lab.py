import importlib.util
from pathlib import Path
import tempfile
import unittest

FILE=Path(__file__).resolve().parents[1]/'scripts'/'market_data_feed_lab.py'
spec=importlib.util.spec_from_file_location('market_data_feed_lab',FILE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TestMarketDataFeedLab(unittest.TestCase):
    def test_codec_round_trip(self):
        self.assertEqual(mod.decode_packet(mod.encode_packet(100, 1234, b'x')),(100,1234))
    def test_rejects_malformed_data(self):
        with self.assertRaises(ValueError):mod.decode_packet(b'garbage')
        with self.assertRaises(ValueError):mod.decode_packet(b'X'+mod.encode_packet(1,1)[1:])
        with self.assertRaises(ValueError):mod.encode_packet(0,1)
        with self.assertRaises(ValueError):mod.encode_packet(1,1,b'x'*9000)
    def test_gap_recovery_and_duplicates(self):
        t=mod.SequenceTracker()
        self.assertEqual([t.observe(7,i) for i in [1,2,4,4,3,5]],
                         ['first','in_order','gap','duplicate','late_recovery','in_order'])
        r=t.report()['streams']['7']
        self.assertEqual(r['missing_observed'],1)
        self.assertEqual(r['gaps_recovered'],1)
        self.assertEqual(r['pending'],0)
        self.assertEqual(r['duplicates'],1)
        self.assertEqual(r['out_of_order'],1)
    def test_multi_stream_isolated(self):
        r=mod.process_datagrams([mod.encode_packet(1,1),mod.encode_packet(2,1),mod.encode_packet(1,3)])
        self.assertEqual(r['streams']['1']['pending'],1)
        self.assertEqual(r['streams']['2']['pending'],0)
    def test_excessive_gap_does_not_allocate(self):
        t=mod.SequenceTracker(max_gap=3)
        t.observe(1,1)
        self.assertEqual(t.observe(1,1000000000),'discontinuity')
        self.assertEqual(t.report()['streams']['1']['pending'],0)
    def test_history_bounded(self):
        t=mod.SequenceTracker(history_limit=2)
        for i in [1,2,3,4]: t.observe(1,i)
        self.assertEqual(len(t.streams[1]['seen']),2)
    def test_unique_output(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json'
            mod.write_json_unique(p,{'ok':True})
            with self.assertRaises(FileExistsError):mod.write_json_unique(p,{'ok':False})
    def test_real_udp_loopback(self):
        r=mod.run_loopback_demo(80)
        self.assertTrue(r['completed'],r)
        self.assertEqual(r['received'],r['sent'])
        v=r['streams']['1']
        self.assertEqual(v['pending'],0)
        self.assertEqual(v['gaps_recovered'],1)
        self.assertGreaterEqual(v['duplicates'],1)
    def test_bad_multicast_parameters(self):
        with self.assertRaises(ValueError):mod.receive_multicast('127.0.0.1',100,1,1)
        with self.assertRaises(ValueError):mod.receive_multicast('239.1.1.1',0,1,1)

if __name__=='__main__':unittest.main()
