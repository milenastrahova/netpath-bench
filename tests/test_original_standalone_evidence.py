"""Verify the known experiment constants and reject altered sample data."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import json
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('evidence_verifier',ROOT/'scripts'/'verify_standalone_evidence.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class OriginalEvidenceTests(unittest.TestCase):
    def test_expected_fingerprints_are_sha256_length(self):
        self.assertEqual(len(mod.SOURCES),4)
        self.assertTrue(all(len(v)==64 and all(c in '0123456789abcdef' for c in v)
                            for v in mod.SOURCES.values()))
    def test_nearest_rank_percentiles(self):
        self.assertEqual(mod.rank(list(range(1,501)),.99),495)
        self.assertEqual(mod.rank(list(range(1,501)),.999),500)
    def test_analyzed_csv_has_explicit_sequence_checks(self):
        self.assertEqual(mod.FIELDS,('sequence','start_offset_ms','status','rtt_ms'))
    def test_bad_zip_fails_closed(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            p=Path(d)/'evidence.zip'
            p.write_bytes(b'invalid')
            with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'):
                mod.verify_zip(p)
    def test_tampered_values_fail_recomputed_metrics(self):
        sample=('sequence,start_offset_ms,status,rtt_ms\n'
                +''.join(f'{i},{i*1.1:.6f},ok,{0.1 if i<499 else 0.2:.6f}\n'
                          for i in range(500))).encode()
        report={'schema_version':1,'experiment':'app_echo_rtt','protocol':'udp',
                'host':'server','port':9000,'packet_bytes':64,
                'attempted':500,'sample_count':500,'successful_echoes':500,
                'timeouts':0,'errors':0,'unexpected_replies':0,
                'echo_failure_ratio':0,'observation_duration_ms':552,
                'started_at_utc':'2026-10-29T21:00:00.000Z',
                'ended_at_utc':'2026-10-29T21:00:00.552Z',
                'rtt_ms':{'min':0.1,'mean':0.1002,'p50':0.1,'p95':0.1,
                          'p99':0.1,'p999':0.2,'max':0.2},
                'consecutive_abs_rtt_difference_ms':{'mean':0.1/499,'p99':0}}
        # The reported average adjacent difference is intentionally wrong:
        # the value rounds correctly to 0.000200, but the p99 ranks 0.
        self.assertEqual(mod.check_pair('udp',json.dumps(report).encode(),sample)['samples'],500)
        report['rtt_ms']['p99']=0.2
        with self.assertRaisesRegex(ValueError,'p99 CSV/JSON mismatch'):
            mod.check_pair('udp',json.dumps(report).encode(),sample)
    def test_missing_sequence_rejected(self):
        sample=('sequence,start_offset_ms,status,rtt_ms\n'
                +''.join(f'{i if i!=30 else 31},{i*1.1:.6f},ok,0.100000\n' for i in range(500))).encode()
        report={'schema_version':1,'experiment':'app_echo_rtt','protocol':'tcp',
                'host':'server','port':9000,'packet_bytes':64,'attempted':500,
                'sample_count':500,'successful_echoes':500,'timeouts':0,'errors':0,
                'unexpected_replies':0,'echo_failure_ratio':0}
        with self.assertRaisesRegex(ValueError,'noncontiguous sequence'):
            mod.check_pair('tcp',json.dumps(report).encode(),sample)
if __name__=='__main__':
    unittest.main()
