"""Synthetic fixture tests only. No FRR outage, no real user traces embedded."""
from __future__ import annotations
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from scripts.review_series import safe_archive, evaluate_series, sha, nearly_equal, main
from scripts.review_evidence import build_review


def build_fixture() -> dict[str,bytes]:
    # Four synthetic probe events per run, entirely fabricated for tests.
    content={}; rows=[]
    for idx in (1,2):
        run_id=f'fixture-{idx:02d}'
        stem=f'bgp-failover-udp-{run_id}'
        samples=[0.1+0.01*idx, 0.4, None, 0.7]
        csv='sequence,start_offset_ms,status,rtt_ms\n'
        for i, v in enumerate(samples):
            csv+=f'{i},{[100,6100,7000,23000][i]},{ "ok" if v is not None else "timeout"},{ v if v is not None else "null"}\n'
        import statistics
        ok=sorted(x for x in samples if x is not None)
        probe={'schema_version':1,'experiment':'app_echo_rtt','protocol':'udp',
               'host':'10.40.40.1','source_ip':'10.10.10.1','packet_bytes':64,'port':9000,
               'attempted':4,'sample_count':4,'successful_echoes':3,'timeouts':1,
               'errors':0,'unexpected_replies':0,'echo_failure_ratio':0.25,
               'started_at_utc':f'2026-01-01T12:{idx:02d}:00.000Z',
               'ended_at_utc':f'2026-01-01T12:{idx:02d}:24.000Z',
               'observation_duration_ms':24000,
               'rtt_ms':{'min':ok[0],'mean':statistics.mean(ok),'p50':ok[1],
                         'p95':ok[2],'p99':ok[2],'p999':ok[2],'max':ok[2]}}
        phases=[('server_ready',-1),('probe_command_started',-0.5),
                ('primary_stop_requested',6),('primary_stop_command_finished',6.4),
                ('primary_restore_requested',11.4),('primary_restore_command_finished',11.7),
                ('probe_finished',24.1)]
        import datetime as dt
        start=dt.datetime.fromisoformat(probe['started_at_utc'].replace('Z','+00:00'))
        ev={'schema_version':1,'mode':'failover','protocol':'udp','run_id':run_id,'status':'CAPTURED',
            'probe_source_ip':probe['source_ip'],'server_ip':probe['host'],
            'probe_exit_code':2,'attempted':4,'successful_echoes':3,'echo_timeouts':1,
            'events':[{'phase':p,'utc':(start+dt.timedelta(seconds=s)).isoformat()} for p,s in phases]}
        nested={"bgp-failover-udp.json":(json.dumps(probe)+'\n').encode(),
                "bgp-failover-udp.csv":csv.encode(),
                "bgp-failover-udp-events.json":(json.dumps(ev)+'\n').encode()}
        review,_=build_review(nested)
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,raw in nested.items():z.writestr(name,raw)
        bundle=b.getvalue();content[f'{run_id}.zip']=bundle
        for name,raw in nested.items():
            actual_name=f'{stem}' + ({'bgp-failover-udp.json':'.json',
                  'bgp-failover-udp.csv':'.csv','bgp-failover-udp-events.json':'-events.json'}[name])
            content[actual_name]=raw
        rows.append({'run_id':run_id,'bundle':f'{run_id}.zip',
           'bundle_sha256':sha(bundle),'attempts':4,'missing_echoes':1,'failure_ratio':0.25,
           'p99_rtt_ms':review['rtt_ms']['p99'],'raw_csv_sha256':sha(nested['bgp-failover-udp.csv']),
           'validation':'PASS'})
    comparison={'run_count':2,'runs_with_missing_echoes':2,'run_level_median_p99_ms':0.7,
        'runs':[{'file':row['bundle'],'evidence_csv_sha256':row['raw_csv_sha256'],
           'attempts':row['attempts'],'missing_echoes':1,'failure_ratio':0.25,
           'p99_rtt_ms':0.7,'p999_rtt_ms':0.7,
           'mean_rtt_ms':statistics.mean([0.1+(i+1)*.01,0.4,0.7])} for i,row in enumerate(rows)]}
    series={'schema_version':1,'series_id':'fixture','status':'PASS',
        'planned_runs':2,'runs':rows,'settings':{'protocol':'udp','seconds':24,'fault_at':6,
           'fault_seconds':5,'interval_us':20000,'timeout_ms':200},'comparison':comparison}
    content['series.json']=json.dumps(series).encode()
    content['series.md']=b'# SYNTHETIC TEST SERIES\n'
    return content


def outer_zip(content):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for name,value in content.items():z.writestr(name,value)
    b.seek(0);return b


class SeriesAuditTests(unittest.TestCase):
    def test_synthetic_two_run_pass(self):
        data,_=evaluate_series(build_fixture())
        self.assertEqual(data['counts']['application_echo_attempts'],8)
        self.assertEqual(data['counts']['unsuccessful_echoes'],2)
        self.assertEqual(data['run_count'],2)

    def test_reject_invalid_bundle_hash(self):
        c=build_fixture();s=json.loads(c['series.json']);s['runs'][0]['bundle_sha256']='0'*64
        c['series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'bundle SHA'):
            evaluate_series(c)

    def test_reject_modified_loose_csv(self):
        c=build_fixture();k='bgp-failover-udp-fixture-01.csv';c[k]=c[k].replace(b'0,100',b'0,101')
        with self.assertRaisesRegex(ValueError,'loose/nested evidence'):
            evaluate_series(c)

    def test_reject_duplicate_run_id(self):
        c=build_fixture();s=json.loads(c['series.json']);s['runs'][1]['run_id']='fixture-01';c['series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'duplicate run ID'):evaluate_series(c)

    def test_reject_invalid_comparison(self):
        c=build_fixture();s=json.loads(c['series.json']);s['comparison']['run_level_median_p99_ms']=5;c['series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'comparison p99'):evaluate_series(c)

    def test_reject_incomplete_series(self):
        c=build_fixture();s=json.loads(c['series.json']);s['status']='ERROR';c['series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'incomplete'):evaluate_series(c)

    def test_reject_extra_file(self):
        c=build_fixture();c['bad.txt']=b'unexpected'
        with self.assertRaisesRegex(ValueError,'contents mismatch'):evaluate_series(c)

    def test_reject_zip_traversal(self):
        c=build_fixture();c['../danger.txt']=b'malice'
        with self.assertRaisesRegex(ValueError,'unsafe'):safe_archive(outer_zip(c))

    def test_reject_duplicate_zip_member(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            z.writestr('series.json','{}')
            with __import__('warnings').catch_warnings():
                __import__('warnings').simplefilter('ignore',UserWarning)
                z.writestr('series.json','{}')
        b.seek(0)
        with self.assertRaisesRegex(ValueError,'duplicate'):safe_archive(b)

    def test_reject_nested_bundle_corruption(self):
        c=build_fixture();k='fixture-01.zip';c[k]=c[k][:-5]+b'abcde'
        with self.assertRaisesRegex(ValueError,'bundle SHA'):evaluate_series(c)

    def test_refuse_overwrite_existing_report(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);raw=path/'source.zip';raw.write_bytes(outer_zip(build_fixture()).getvalue())
            out=path/'result';self.assertEqual(main(['--series-zip',str(raw),'--output-dir',str(out)]),0)
            self.assertEqual(main(['--series-zip',str(raw),'--output-dir',str(out)]),1)
            self.assertTrue((out/'series-review.md').exists())

    def test_float_mismatch_rejected(self):
        self.assertFalse(nearly_equal(float('nan'),1.0))
        self.assertFalse(nearly_equal(True,1.0))


if __name__=='__main__':unittest.main()
