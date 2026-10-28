"""All conditions in these fixtures are synthetic; no live router actions."""
from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
import statistics
import tempfile
import unittest
import zipfile
from scripts.control_evidence import BASENAMES, check_triplet
from scripts.audit_conditions import verified_control,audit_archives,main,svg_chart
from scripts.review_series import sha
from tests.test_controls import fixture
from tests.test_series_audit import build_fixture,outer_zip


def baseline_fixture() -> dict[str,bytes]:
    out={};rows=[]
    for idx in (1,2):
        rid=f'control-{idx:02d}'
        inner=fixture(idx)
        probe=json.loads(inner[BASENAMES[0]])
        probe.update(port=9000,packet_bytes=64,observation_duration_ms=24000)
        event=json.loads(inner[BASENAMES[2]])
        event['run_id']=rid
        inner[BASENAMES[0]]=json.dumps(probe).encode()
        inner[BASENAMES[2]]=json.dumps(event).encode()
        check=check_triplet(inner)
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for n,v in inner.items():z.writestr(n,v)
        binary=b.getvalue()
        out[f'{rid}.zip']=binary
        for n,suffix in zip(BASENAMES,('.json','.csv','-events.json')):
            out[f'bgp-baseline-udp-{rid}{suffix}']=inner[n]
        rows.append(check|{'run_id':rid,'archive':f'{rid}.zip','bundle_sha256':sha(binary)})
    series={'schema_version':1,'condition':'NO_FAULT_CONTROL','status':'PASS','series_id':'fixture-control',
            'settings':{'protocol':'udp','seconds':24,'interval_us':20000,'timeout_ms':200},
            'planned_runs':2,'runs':rows,'aggregate':{'runs':2,'attempts':6,'unsuccessful':0,
            'run_level_median_p99_ms':statistics.median(r['rtt_ms']['p99'] for r in rows)}}
    out['control-series.json']=json.dumps(series).encode()
    out['control-series.md']=b'SYNTHETIC CONTROL SERIES'
    return out

class ConditionsAuditTests(unittest.TestCase):
    def test_control_verification_uses_original_data(self):
        x=verified_control(baseline_fixture())
        self.assertEqual(x['status'],'PASS')
        self.assertEqual(x['aggregate']['attempts'],6)

    def test_fails_modified_nested_hash(self):
        x=baseline_fixture();s=json.loads(x['control-series.json']);s['runs'][0]['bundle_sha256']='0'*64
        x['control-series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'bundle hash'):verified_control(x)

    def test_fails_modified_csv_loose(self):
        x=baseline_fixture();k='bgp-baseline-udp-control-01.csv';x[k]=x[k].replace(b'0,0',b'0,1',1)
        with self.assertRaisesRegex(ValueError,'Nested/loose'):verified_control(x)

    def test_fails_extra_file(self):
        x=baseline_fixture();x['note.txt']=b'unexpected'
        with self.assertRaisesRegex(ValueError,'extra files'):verified_control(x)

    def test_fails_duplicate_id(self):
        x=baseline_fixture();s=json.loads(x['control-series.json']);s['runs'][1]['run_id']=s['runs'][0]['run_id'];x['control-series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'duplicate'):verified_control(x)

    def test_fails_invalid_settings(self):
        x=baseline_fixture();s=json.loads(x['control-series.json']);s['settings']['seconds']=False;x['control-series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'setting'):verified_control(x)

    def test_rejects_wrong_control_aggregate(self):
        x=baseline_fixture();s=json.loads(x['control-series.json']);s['aggregate']['attempts']=8;x['control-series.json']=json.dumps(s).encode()
        with self.assertRaisesRegex(ValueError,'aggregate'):verified_control(x)

    def test_end_to_end_synthetic_reports_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);c=p/'control.zip';f=p/'failover.zip';out=p/'output'
            c.write_bytes(outer_zip(baseline_fixture()).getvalue());f.write_bytes(outer_zip(build_fixture()).getvalue())
            self.assertEqual(main(['--control-zip',str(c),'--failover-zip',str(f),'--output-dir',str(out)]),0)
            x=json.loads((out/'condition-comparison.json').read_text())
            self.assertEqual(x['causal_claim'],'NOT_ESTABLISHED')
            self.assertEqual(x['control']['unsuccessful_echoes'],0)
            self.assertEqual(x['failover']['unsuccessful_echoes'],2)
            self.assertIn('<svg',(out/'condition-comparison.svg').read_text())
            self.assertEqual(main(['--control-zip',str(c),'--failover-zip',str(f),'--output-dir',str(out)]),1)

    def test_reject_mismatched_series_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);c=p/'control.zip';f=p/'failover.zip';out=p/'output'
            c.write_bytes(outer_zip(baseline_fixture()).getvalue())
            x=build_fixture();d=json.loads(x['series.json']);d['settings']['interval_us']=10000;x['series.json']=json.dumps(d).encode()
            f.write_bytes(outer_zip(x).getvalue())
            self.assertEqual(main(['--control-zip',str(c),'--failover-zip',str(f),'--output-dir',str(out)]),1)
            self.assertFalse(out.exists())

    def test_reject_identical_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'same.zip';p.write_bytes(b'zip')
            with self.assertRaisesRegex(ValueError,'different files'):audit_archives(p,p)

if __name__=='__main__':unittest.main()
