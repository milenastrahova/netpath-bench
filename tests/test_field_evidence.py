"""Synthetic fixtures only. These are not results of the user's field experiment."""
from __future__ import annotations
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('field_review',ROOT/'scripts'/'review_evidence.py')
review=importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
spec2=importlib.util.spec_from_file_location('batch_compare',ROOT/'scripts'/'compare_runs.py')
compare=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(compare)
spec3=importlib.util.spec_from_file_location('bundle_trial',ROOT/'scripts'/'bundle_trial.py')
bundle=importlib.util.module_from_spec(spec3)
spec3.loader.exec_module(bundle)

class FieldEvidenceTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.probe={'protocol':'udp','host':'10.40.40.1','source_ip':'10.10.10.1',
                    'attempted':4,'sample_count':4,'successful_echoes':3,'timeouts':1,
                    'echo_failure_ratio':0.25,'observation_duration_ms':4000,
                    'started_at_utc':'2026-10-28T12:00:00.000Z','ended_at_utc':'2026-10-28T12:00:04.000Z'}
        phases=[('server_ready','2026-10-28T11:59:59.900Z'),
                ('probe_command_started','2026-10-28T11:59:59.950Z'),
                ('primary_stop_requested','2026-10-28T12:00:01.000Z'),
                ('primary_stop_command_finished','2026-10-28T12:00:01.200Z'),
                ('primary_restore_requested','2026-10-28T12:00:03.000Z'),
                ('primary_restore_command_finished','2026-10-28T12:00:03.200Z'),
                ('probe_finished','2026-10-28T12:00:04.100Z')]
        self.events={'protocol':'udp','mode':'failover','status':'CAPTURED','probe_source_ip':'10.10.10.1',
                     'server_ip':'10.40.40.1','attempted':4,'successful_echoes':3,'echo_timeouts':1,
                     'probe_exit_code':2,
                     'events':[{'phase':p,'utc':t} for p,t in phases]}
        self.csv='sequence,start_offset_ms,status,rtt_ms\n0,500,ok,1.2\n1,1500,timeout,null\n2,2500,ok,0.9\n3,3500,ok,1.0\n'
    def make_zip(self,name='run.zip',probe=None,events=None,csv=None,extra=None):
        path=self.root/name
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('bgp-failover-udp.json',json.dumps(probe or self.probe))
            z.writestr('bgp-failover-udp.csv',csv or self.csv)
            z.writestr('bgp-failover-udp-events.json',json.dumps(events or self.events))
            if extra:z.writestr(extra,'{}')
        return path
    def test_valid_independent_review(self):
        files=review.read_evidence_zip(self.make_zip())
        out,rows=review.build_review(files)
        self.assertEqual(out['counts']['successful_echoes'],3)
        self.assertEqual(out['non_successful_probes'][0]['sequence'],1)
        self.assertEqual(out['non_successful_probes'][0]['approx_ms_after_stop_request'],500)
        self.assertEqual(out['phase_counts']['stop_to_restore_finished']['samples'],2)
        self.assertIn('<svg',review.svg_plot(out,rows))
        self.assertIn('not proof',review.markdown_report(out))
    def test_full_output_generation_and_refuse_overwrite(self):
        file=self.make_zip();out=self.root/'report'
        targets=review.make_artifacts(file,out)
        self.assertEqual(set(targets),{'json','svg','markdown'})
        self.assertTrue(all(p.is_file() for p in targets.values()))
        with self.assertRaisesRegex(ValueError,'already exist'):
            review.make_artifacts(file,out)
    def test_modified_count_rejected(self):
        bad=dict(self.probe,successful_echoes=4)
        with self.assertRaisesRegex(ValueError,'result count mismatch'):
            review.build_review(review.read_evidence_zip(self.make_zip(probe=bad)))
    def test_source_mismatch_rejected(self):
        bad=dict(self.events,server_ip='10.40.40.2')
        with self.assertRaisesRegex(ValueError,'source/destination'):
            review.build_review(review.read_evidence_zip(self.make_zip(events=bad)))
    def test_incomplete_events_rejected(self):
        bad=dict(self.events,events=self.events['events'][:-1])
        with self.assertRaisesRegex(ValueError,'phase timeline'):
            review.build_review(review.read_evidence_zip(self.make_zip(events=bad)))
    def test_tampered_sequence_rejected(self):
        with self.assertRaisesRegex(ValueError,'sample sequence'):
            review.build_review(review.read_evidence_zip(self.make_zip(csv=self.csv.replace('2,2500','22,2500'))))
    def test_duplicate_entries_rejected(self):
        import warnings
        p=self.make_zip()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(p,'a') as z:z.writestr('bgp-failover-udp.csv','bad')
        with self.assertRaisesRegex(ValueError,'duplicate ZIP'):
            review.read_evidence_zip(p)
    def test_unexpected_entry_rejected(self):
        with self.assertRaisesRegex(ValueError,'unexpected file'):
            review.read_evidence_zip(self.make_zip(extra='../../etc/passwd'))
    def test_bad_event_order_rejected(self):
        bad=json.loads(json.dumps(self.events));bad['events'][3]['utc']='2026-10-28T12:00:00Z'
        with self.assertRaisesRegex(ValueError,'out-of-order'):
            review.build_review(review.read_evidence_zip(self.make_zip(events=bad)))
    def test_reject_ratio_mismatch(self):
        bad=dict(self.probe,echo_failure_ratio=0)
        with self.assertRaisesRegex(ValueError,'failure ratio'):
            review.build_review(review.read_evidence_zip(self.make_zip(probe=bad)))
    def test_batch_reject_duplicate_evidence(self):
        p=self.make_zip('first.zip');q=self.make_zip('second.zip')
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            compare.compare([p,q])
    def test_batch_uses_run_level_medians(self):
        p=self.make_zip('first.zip')
        other=self.csv.replace('0,500,ok,1.2','0,500,ok,2.2')
        q=self.make_zip('second.zip',csv=other)
        result=compare.compare([p,q]);self.assertEqual(result['run_count'],2)
        self.assertEqual(result['runs_with_missing_echoes'],2)
        self.assertAlmostEqual(result['run_level_median_p99_ms'],1.7)
    def test_bundle_synthetic_named_run(self):
        src=self.root/'reports';src.mkdir()
        for ext,body in zip(('.json','.csv','-events.json'),(json.dumps(self.probe),self.csv,json.dumps(self.events))):
            (src/('bgp-failover-udp-run02'+ext)).write_text(body)
        z=bundle.bundle(src,'run02',self.root/'named.zip')
        self.assertEqual(len(review.read_evidence_zip(z)),3)
    def test_bundle_refuses_invalid_run(self):
        with self.assertRaisesRegex(ValueError,'Invalid run'):
            bundle.bundle(self.root,'../../bad',self.root/'bad.zip')

if __name__=='__main__':unittest.main()
