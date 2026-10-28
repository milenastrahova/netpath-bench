"""Offline check of JSON/CSV consistency, phase matching and invalid evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]/'scripts'/'analyze_trial.py'
spec=importlib.util.spec_from_file_location('analysis',MODULE)
analysis=importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.js=self.base/'a.json';self.csv=self.base/'a.csv';self.ev=self.base/'a-events.json'
        self.js.write_text(json.dumps({'sample_count':3,'attempted':3,'successful_echoes':2,
                                       'started_at_utc':'2026-10-28T12:00:00.000Z', 'protocol':'udp'}))
        self.csv.write_text('sequence,start_offset_ms,status,rtt_ms\n'
                            '0,0.000000,ok,1.000000\n1,2000.000000,timeout,null\n'
                            '2,6000.000000,ok,5.000000\n')
        self.ev.write_text(json.dumps({'status':'CAPTURED','mode':'failover','events':[
           {'phase':'primary_stop_requested','utc':'2026-10-28T12:00:01.000Z'},
           {'phase':'primary_restore_command_finished','utc':'2026-10-28T12:00:04.000Z'}]}))

    def test_valid_phase_windows(self):
        result=analysis.analyze(self.js,self.csv,self.ev)
        self.assertEqual(result['phase_correlation'],'APPROXIMATE_UTC_ONLY')
        self.assertEqual(result['phases']['before_stop_request']['samples'],1)
        self.assertEqual(result['phases']['stop_to_restore_command_finished']['missing_or_invalid_echoes'],1)
        self.assertEqual(result['phases']['after_restore_command_finished']['samples'],1)
        self.assertEqual(result['phases']['complete']['rtt_ms']['p99'],5.0)

    def test_count_mismatch_fails(self):
        data=json.loads(self.js.read_text());data['attempted']=4;self.js.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'counts mismatch'):
            analysis.analyze(self.js,self.csv)

    def test_unordered_csv_rejected(self):
        self.csv.write_text('sequence,start_offset_ms,status,rtt_ms\n0,2,ok,1\n1,1,timeout,null\n')
        with self.assertRaisesRegex(ValueError,'unsorted'):
            analysis.read_csv(self.csv)

    def test_bad_rtt_rejected(self):
        self.csv.write_text('sequence,start_offset_ms,status,rtt_ms\n0,2,timeout,4\n')
        with self.assertRaisesRegex(ValueError,'RTT/status'):
            analysis.read_csv(self.csv)

    def test_bad_event_clock_rejected(self):
        j=json.loads(self.ev.read_text());j['events'][1]['utc']='2026-10-28T11:59:59Z'
        self.ev.write_text(json.dumps(j))
        with self.assertRaisesRegex(ValueError,'invalid orchestration'):
            analysis.analyze(self.js,self.csv,self.ev)

    def test_baseline_summary(self):
        result=analysis.analyze(self.js,self.csv)
        self.assertEqual(result['phase_correlation'],'NOT_REQUESTED')
        self.assertAlmostEqual(result['phases']['complete']['application_echo_failure_ratio'],1/3,places=6)

if __name__=='__main__':unittest.main()
