import importlib.util
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / 'scripts' / 'linux_net_diagnostics.py'
spec = importlib.util.spec_from_file_location('linux_net_diagnostics',FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
NETDEV = 'Inter-| Receive | Transmit\neth0: 100 10 1 2 0 0 0 0 200 20 0 3 0 0 0 0\n'

class TestLinuxNetDiagnostics(unittest.TestCase):
    def test_counter_parse(self):
        d=mod.parse_net_dev(NETDEV,'eth0')
        self.assertEqual((d['rx_dropped'],d['tx_dropped']), (2,3))
    def test_missing_interface(self):
        with self.assertRaises(ValueError): mod.parse_net_dev(NETDEV,'bad0')
    def test_invalid_row(self):
        with self.assertRaises(ValueError): mod.parse_net_dev('eth0: 1 2','eth0')
    def test_softnet_hex(self):
        self.assertEqual(mod.parse_softnet('0000000a 00000002 00000001\n0000000c 00000003 00000004\n')['dropped'],5)
    def test_tcp_retrans(self):
        self.assertEqual(mod.parse_tcp_retrans('Tcp: RetransSegs InSegs\nTcp: 7 20\n'),7)
    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'net'
            root.mkdir()
            (root/'dev').write_text(NETDEV)
            (root/'softnet_stat').write_text('0000000a 00000002 00000001\n')
            (root/'snmp').write_text('Tcp: RetransSegs\nTcp: 3\n')
            result=mod.snapshot('eth0',Path(d))
            self.assertEqual(result['interface_counters']['rx_bytes'],100)
            self.assertEqual(result['tcp_retranssegs_global'],3)
    def test_bad_interface(self):
        with self.assertRaises(ValueError):mod.snapshot('../../etc/passwd')
    def test_compare(self):
        a={'schema_version':1,'kind':'linux_network_counter_snapshot','interface':'eth0','monotonic_ns':1000000000,
           'interface_counters':mod.parse_net_dev(NETDEV,'eth0'),
           'softnet_global':{'cpu_rows':1,'processed':10,'dropped':2,'time_squeeze':1},
           'tcp_retranssegs_global':2}
        b={**a,'monotonic_ns':2000000000,'interface_counters':{k:v+5 for k,v in a['interface_counters'].items()},
           'softnet_global':{'cpu_rows':1,'processed':20,'dropped':2,'time_squeeze':2},'tcp_retranssegs_global':3}
        result=mod.compare(a,b)
        self.assertEqual(result['rx_bytes_per_second'],5)
        self.assertEqual(result['softnet_global_deltas']['dropped'],0)
        b['interface_counters']['rx_bytes']=0
        with self.assertRaises(ValueError):mod.compare(a,b)
    def test_different_interface(self):
        a={'schema_version':1,'kind':'linux_network_counter_snapshot','interface':'eth0'}
        with self.assertRaises(ValueError):mod.compare(a,{**a,'interface':'lo'})

if __name__=='__main__':
    unittest.main()
