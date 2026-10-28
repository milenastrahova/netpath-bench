"""Offline synthetic contract tests for the optional multi-outage orchestrator.

Fixtures below are fabricated FOR TESTING ONLY, not field observations.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import repeat_failover as repeat


class SyntheticRunner:
    def __init__(self, failure=None):
        self.calls=[]
        self.failure=failure
        self.trials=0

    def __call__(self, cmd, *, timeout):
        self.calls.append(cmd)
        if self.failure == 'trial' and 'bgp_routed_trial.py' in str(cmd[1]):
            raise RuntimeError('synthetic trial command failed')
        if self.failure == 'health_after' and 'labctl.py' in str(cmd[1]) and self.trials > 0:
            raise RuntimeError('synthetic BGP recovery check failed')
        if 'bgp_routed_trial.py' not in str(cmd[1]):
            return 'PASS'
        self.trials+=1
        ix=cmd.index('--run-id')
        run_id=cmd[ix+1]
        out=Path(cmd[cmd.index('--reports')+1])
        name=f'bgp-failover-udp-{run_id}'
        started='2026-01-01T12:00:00.000Z'
        payload={'protocol':'udp','host':'10.40.40.1','source_ip':'10.10.10.1',
                 'attempted':4,'sample_count':4,'successful_echoes':3,'timeouts':1,
                 'echo_failure_ratio':0.25,'observation_duration_ms':4000,
                 'started_at_utc':started,'ended_at_utc':'2026-01-01T12:00:04.000Z'}
        times=[('server_ready','2026-01-01T11:59:59.900Z'),
               ('probe_command_started','2026-01-01T11:59:59.950Z'),
               ('primary_stop_requested','2026-01-01T12:00:01.000Z'),
               ('primary_stop_command_finished','2026-01-01T12:00:01.200Z'),
               ('primary_restore_requested','2026-01-01T12:00:03.000Z'),
               ('primary_restore_command_finished','2026-01-01T12:00:03.200Z'),
               ('probe_finished','2026-01-01T12:00:04.100Z')]
        ev={'protocol':'udp','mode':'failover','status':'CAPTURED','probe_source_ip':'10.10.10.1',
            'server_ip':'10.40.40.1','attempted':4,'successful_echoes':3,'echo_timeouts':1,
            'probe_exit_code':2,'events':[{'phase':p,'utc':t} for p,t in times]}
        csv=f'sequence,start_offset_ms,status,rtt_ms\n0,500,ok,{1.0+self.trials*0.1}\n1,1500,timeout,null\n2,2500,ok,0.9\n3,3500,ok,1.0\n'
        (out/(name+'.json')).write_text(json.dumps(payload),encoding='utf-8')
        (out/(name+'.csv')).write_text(csv,encoding='utf-8')
        (out/(name+'-events.json')).write_text(json.dumps(ev),encoding='utf-8')
        return 'CAPTURED'


class RepeatedFailoverTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.compose=self.root/'compose.yaml';self.compose.write_text('name: isolated-lab\n')
        (self.root/'scripts').mkdir()
        (self.root/'scripts'/'labctl.py').write_text('pass\n')
        self.settings=dict(compose=self.compose,series_id='testA',runs=2,seconds=24,fault_at=6,
                           fault_seconds=5,interval_us=20000,timeout_ms=200,
                           reports_root=self.root/'reports',allow_primary_stop=True)

    def test_explicit_optin(self):
        with self.assertRaisesRegex(ValueError,'allow-primary-stop'):
            repeat.execute_series(**(self.settings|{'allow_primary_stop':False}),runner=SyntheticRunner())
        self.assertFalse((self.root/'reports').exists())

    def test_invalid_run_counts(self):
        for n in (0,1,6,100):
            with self.subTest(runs=n),self.assertRaises(ValueError):
                repeat.execute_series(**(self.settings|{'runs':n}),runner=SyntheticRunner())

    def test_reject_invalid_labels(self):
        for label in ('../evil','run space','','x'*40,'a/b'):
            with self.subTest(label=label),self.assertRaises(ValueError):
                repeat.validate_series_id(label)

    def test_requires_known_labctl(self):
        (self.root/'scripts'/'labctl.py').unlink()
        with self.assertRaisesRegex(ValueError,'labctl'):
            repeat.execute_series(**self.settings,runner=SyntheticRunner())

    def test_two_valid_trials_and_bundles(self):
        runner=SyntheticRunner()
        data=repeat.execute_series(**self.settings,runner=runner)
        self.assertEqual(data['status'],'PASS')
        self.assertEqual(len(data['runs']),2)
        self.assertEqual(data['comparison']['run_count'],2)
        self.assertEqual(data['comparison']['runs_with_missing_echoes'],2)
        self.assertNotEqual(data['runs'][0]['raw_csv_sha256'],data['runs'][1]['raw_csv_sha256'])
        series=self.root/'reports'/'series-testA'
        self.assertEqual(len(list(series.glob('*.zip'))),2)
        self.assertTrue((series/'series.md').exists())
        self.assertEqual(json.loads((series/'series.json').read_text())['status'],'PASS')
        self.assertEqual(sum('labctl.py' in str(cmd[1]) for cmd in runner.calls if len(cmd)>1),4)
        self.assertEqual(sum('bgp_routed_trial.py' in str(cmd[1]) for cmd in runner.calls if len(cmd)>1),2)
        self.assertEqual(sum(cmd[0]=='docker' for cmd in runner.calls),1)

    def test_fail_does_not_continue_and_attempts_restore(self):
        runner=SyntheticRunner(failure='trial')
        with self.assertRaisesRegex(RuntimeError,'synthetic trial command failed'):
            repeat.execute_series(**self.settings,runner=runner)
        series=self.root/'reports'/'series-testA'
        journal=json.loads((series/'series.json').read_text())
        self.assertEqual(journal['status'],'ERROR')
        self.assertEqual(len(journal['runs']),0)
        self.assertEqual(sum('bgp_routed_trial.py' in str(c[1]) for c in runner.calls if len(c)>1),1)
        self.assertEqual(sum(c[0]=='docker' for c in runner.calls),1)

    def test_failed_postcheck_disallows_bundling(self):
        runner=SyntheticRunner(failure='health_after')
        with self.assertRaisesRegex(RuntimeError,'synthetic BGP recovery'):
            repeat.execute_series(**self.settings,runner=runner)
        journal=json.loads((self.root/'reports'/'series-testA'/'series.json').read_text())
        self.assertEqual(journal['status'],'ERROR')
        self.assertEqual(len(journal['runs']),0)
        self.assertEqual(sum(c[0]=='docker' for c in runner.calls),1)

    def test_never_overwrite_series(self):
        repeat.execute_series(**self.settings,runner=SyntheticRunner())
        with self.assertRaises(FileExistsError):
            repeat.execute_series(**self.settings,runner=SyntheticRunner())

    def test_markdown_does_not_claim_wire_packet_loss(self):
        out=repeat.execute_series(**self.settings,runner=SyntheticRunner())
        doc=repeat.markdown_report(out)
        self.assertIn('not confirmed network packet loss',doc)
        self.assertIn('run-level',doc)


if __name__=='__main__': unittest.main()
