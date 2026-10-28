"""Synthetic safety and no-fault audit contract tests. NOT real field observations."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts import repeat_control as control
from scripts import control_evidence as audit
from scripts import compare_conditions as conditions


def fixture(run=1):
    probe={'protocol':'udp','host':'10.40.40.1','source_ip':'10.10.10.1',
           'attempted':3,'sample_count':3,'successful_echoes':3,'timeouts':0,'errors':0,
           'unexpected_replies':0,'started_at_utc':'2026-01-01T00:00:00.000Z',
           'ended_at_utc':'2026-01-01T00:00:03.000Z','observation_duration_ms':3000.0,
           'echo_failure_ratio':0.,'rtt_ms':{'mean':0.2,'p50':0.2,'p95':0.3,'p99':0.3,'p999':0.3,'max':0.3}}
    events={'status':'CAPTURED','mode':'baseline','protocol':'udp','probe_exit_code':0,
            'probe_source_ip':'10.10.10.1','server_ip':'10.40.40.1','attempted':3,
            'successful_echoes':3,'echo_timeouts':0,
            'events':[{'phase':ph,'utc':utc} for ph,utc in [
                ('server_ready','2025-12-31T23:59:59.900Z'),
                ('probe_command_started','2025-12-31T23:59:59.950Z'),
                ('probe_finished','2026-01-01T00:00:03.100Z')]]}
    vals=[0.1,0.2,0.3] if run==1 else [0.2,0.1,0.3]
    csv='sequence,start_offset_ms,status,rtt_ms\n'+''.join(f'{i},{i*1000},{"ok"},{v}\n' for i,v in enumerate(vals))
    return {audit.BASENAMES[0]:json.dumps(probe).encode(),audit.BASENAMES[1]:csv.encode(),audit.BASENAMES[2]:json.dumps(events).encode()}


class SyntheticRunner:
    def __init__(self,fail_on=None):self.calls=[];self.count=0;self.fail_on=fail_on
    def __call__(self,argv,*,timeout):
        self.calls.append(argv)
        if 'bgp_routed_trial.py' in str(argv[1]):
            self.count+=1
            if self.fail_on=='trial':raise RuntimeError('synthetic control trial failure')
            assert argv[argv.index('--mode')+1]=='baseline'
            assert '--allow-primary-stop' not in argv
            d=Path(argv[argv.index('--reports')+1]);id=argv[argv.index('--run-id')+1]
            for name,data in fixture(self.count).items():
                suffix=name[len('bgp-baseline-udp'):]
                (d/f'bgp-baseline-udp-{id}{suffix}').write_bytes(data)
        return 'PASS'


class Controls(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        compose=self.root/'compose.yaml';compose.write_text('name:lab\n')
        (self.root/'scripts').mkdir();(self.root/'scripts'/'labctl.py').write_text('pass')
        self.args=dict(compose=compose,series_id='control-set-A',runs=2,seconds=24,interval_us=20000,
                       timeout_ms=200,reports_root=self.root/'reports')

    def test_valid_control_evidence(self):
        out=audit.check_triplet(fixture());self.assertEqual(out['verification'],'PASS');self.assertEqual(out['successes'],3)

    def test_reject_failure_events(self):
        x=fixture();y=json.loads(x[audit.BASENAMES[2]]);y['events'].insert(2,{'phase':'primary_stop_requested','utc':'2026-01-01T00:00:01Z'})
        x[audit.BASENAMES[2]]=json.dumps(y).encode()
        with self.assertRaisesRegex(ValueError,'unexpected events'):audit.check_triplet(x)

    def test_reject_wrong_sample_counts(self):
        x=fixture();j=json.loads(x[audit.BASENAMES[0]]);j['attempted']=4;x[audit.BASENAMES[0]]=json.dumps(j).encode()
        with self.assertRaisesRegex(ValueError,'counts'):audit.check_triplet(x)

    def test_reject_bad_rtt_summary(self):
        x=fixture();j=json.loads(x[audit.BASENAMES[0]]);j['rtt_ms']['p99']=9;x[audit.BASENAMES[0]]=json.dumps(j).encode()
        with self.assertRaisesRegex(ValueError,'aggregate'):audit.check_triplet(x)

    def test_two_control_runs_do_not_stop_containers(self):
        r=SyntheticRunner();out=control.execute_controls(**self.args,runner=r)
        self.assertEqual(out['status'],'PASS');self.assertEqual(len(out['runs']),2)
        self.assertEqual(out['aggregate']['attempts'],6)
        self.assertEqual(len([v for v in r.calls if 'bgp_routed_trial.py' in str(v[1])]),2)
        self.assertFalse(any('docker' in a[0] or 'stop' in a for a in r.calls))
        for row in out['runs']:
            self.assertTrue((self.root/'reports'/'control-control-set-A'/row['archive']).is_file())

    def test_refuse_duplicate_control_folder(self):
        control.execute_controls(**self.args,runner=SyntheticRunner())
        with self.assertRaises(FileExistsError):control.execute_controls(**self.args,runner=SyntheticRunner())

    def test_failure_aborts_and_saves_journal(self):
        r=SyntheticRunner('trial')
        with self.assertRaisesRegex(RuntimeError,'synthetic control trial'):
            control.execute_controls(**self.args,runner=r)
        report=json.loads((self.root/'reports'/'control-control-set-A'/'control-series.json').read_text())
        self.assertEqual(report['status'],'ERROR');self.assertEqual(len(report['runs']),0)
        self.assertEqual(len([x for x in r.calls if 'bgp_routed_trial.py' in str(x[1])]),1)

    def test_reject_invalid_inputs(self):
        for run in (0,1,11):
            with self.assertRaises(ValueError):control.execute_controls(**(self.args|{'runs':run}),runner=SyntheticRunner())

    def test_descriptive_comparison(self):
        x=control.execute_controls(**self.args,runner=SyntheticRunner())
        f={'verification':'PASS','experiment':'independent_netpath_series_evidence_audit','settings':dict(x['settings']),
           'run_count':2,'counts':{'application_echo_attempts':8,'unsuccessful_echoes':2},'runs':[]}
        for i in range(2):f['runs'].append({'validation':'PASS','attempts':4,'successes':3,'unsuccessful':1,
              'evidence_sha256':{'bgp-failover-udp.csv':hashlib.sha256(f'failover-fixture-{i}'.encode()).hexdigest()},
              'rtt_ms':{'p99':0.6}})
        result=conditions.compare(x,f);self.assertEqual(result['verification'],'PASS')
        self.assertEqual(result['causal_claim'],'NOT_ESTABLISHED')
        self.assertEqual(result['control']['unsuccessful_echoes'],0)
        f['settings']['seconds']=30
        with self.assertRaisesRegex(ValueError,'settings mismatch'):
            conditions.compare(x,f)

    def test_no_false_claims(self):
        self.assertIn('NOT',conditions.markdown({'control':{'runs':2,'attempts':1,'unsuccessful_echoes':0,'observed_echo_failure_ratio':0.,'run_level_median_p99_ms':0.1},
                                              'failover':{'runs':2,'attempts':1,'unsuccessful_echoes':1,'observed_echo_failure_ratio':1.,'run_level_median_p99_ms':0.2},
                                              'limitations':['One run is not enough']}))

if __name__=='__main__': unittest.main()
