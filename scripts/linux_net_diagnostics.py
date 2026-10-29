#!/usr/bin/env python3
"""Read-only Linux network counters; NOT physical NIC latency or proof of packet loss."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import time

RX = ('rx_bytes','rx_packets','rx_errors','rx_dropped','rx_fifo','rx_frame','rx_compressed','rx_multicast')
TX = ('tx_bytes','tx_packets','tx_errors','tx_dropped','tx_fifo','tx_collisions','tx_carrier','tx_compressed')
COUNTERS = RX + TX
IFACE = re.compile(r'^[a-zA-Z0-9_.:@-]{1,64}$')

def parse_net_dev(data, interface):
    for raw in data.splitlines():
        if ':' not in raw:
            continue
        iface, fields = raw.split(':', 1)
        if iface.strip() != interface:
            continue
        parts = fields.split()
        if len(parts) != 16:
            raise ValueError('Expected 16 /proc/net/dev counters')
        try:
            return dict(zip(COUNTERS, (int(v) for v in parts)))
        except ValueError as exc:
            raise ValueError('Non-integer /proc/net/dev counter') from exc
    raise ValueError(f'Interface not found in /proc/net/dev: {interface}')

def parse_softnet(data):
    totals = {'processed':0,'dropped':0,'time_squeeze':0}
    rows = 0
    for line in data.splitlines():
        parts=line.split()
        if not parts:
            continue
        if len(parts) < 3:
            raise ValueError('Invalid /proc/net/softnet_stat row')
        try:
            vals=[int(x, 16) for x in parts[:3]]
        except ValueError as exc:
            raise ValueError('Invalid hexadecimal softnet counter') from exc
        for key, val in zip(totals, vals):
            totals[key] += val
        rows += 1
    return {'cpu_rows':rows, **totals}

def parse_tcp_retrans(data):
    tcp = [x.split()[1:] for x in data.splitlines() if x.startswith('Tcp:')]
    for names, values in zip(tcp[::2], tcp[1::2]):
        if len(names) == len(values) and 'RetransSegs' in names:
            return int(values[names.index('RetransSegs')])
    return None

def snapshot(interface, proc_root=Path('/proc')):
    if not IFACE.fullmatch(interface) or interface in ('.','..'):
        raise ValueError('Invalid interface name')
    root=proc_root/'net'
    if not (root/'dev').exists():
        raise RuntimeError('Linux /proc/net/dev unavailable')
    dev=parse_net_dev((root/'dev').read_text(), interface)
    soft=root/'softnet_stat'
    snmp=root/'snmp'
    return {
        'schema_version':1, 'kind':'linux_network_counter_snapshot',
        'collected_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'monotonic_ns':time.monotonic_ns(), 'interface':interface,
        'interface_counters':dev,
        'softnet_global':parse_softnet(soft.read_text()) if soft.exists() else None,
        'tcp_retranssegs_global':parse_tcp_retrans(snmp.read_text()) if snmp.exists() else None,
        'limitations':[
            'Read-only counters cannot prove the cause of a network issue.',
            'Softnet and TCP counters aggregate a Linux network namespace, not a single interface.',
            'Docker/WSL2 virtual NIC counters are not physical NIC measurements.'
        ]
    }

def compare(before, after):
    if before.get('schema_version') != 1 or after.get('schema_version') != 1:
        raise ValueError('Unsupported snapshot schema')
    if before.get('kind') != 'linux_network_counter_snapshot' or after.get('kind') != 'linux_network_counter_snapshot':
        raise ValueError('Not Linux network snapshots')
    if before.get('interface') != after.get('interface'):
        raise ValueError('Different interfaces')
    a=before['interface_counters']
    b=after['interface_counters']
    if set(a) != set(COUNTERS) or set(b) != set(COUNTERS):
        raise ValueError('Incomplete interface counters')
    if any(type(v) is not int or v < 0 for v in list(a.values())+list(b.values())):
        raise ValueError('Invalid counter value')
    values={k:b[k]-a[k] for k in COUNTERS}
    if any(v < 0 for v in values.values()):
        raise ValueError('Counter reset or wrap; cannot infer deltas')
    start,end=before.get('monotonic_ns'),after.get('monotonic_ns')
    duration=(end-start)/1e9 if type(start) is int and type(end) is int and end>start else None
    softnet_delta=None
    s1,s2=before.get('softnet_global'),after.get('softnet_global')
    if s1 is not None and s2 is not None and s1['cpu_rows']==s2['cpu_rows']:
        diff={k:s2[k]-s1[k] for k in ('processed','dropped','time_squeeze')}
        if all(v>=0 for v in diff.values()):
            softnet_delta=diff
    tcp_delta=None
    t1,t2=before.get('tcp_retranssegs_global'),after.get('tcp_retranssegs_global')
    if type(t1) is int and type(t2) is int and t2>=t1:
        tcp_delta=t2-t1
    return {
        'schema_version':1,'kind':'linux_network_counter_comparison','interface':before['interface'],
        'elapsed_seconds':duration,'interface_deltas':values,
        'softnet_global_deltas':softnet_delta,'tcp_retranssegs_global_delta':tcp_delta,
        'rx_bytes_per_second':values['rx_bytes']/duration if duration else None,
        'tx_bytes_per_second':values['tx_bytes']/duration if duration else None,
        'interpretation':'Descriptive namespace counters; not one-way latency, proven wire packet loss, or optimization evidence.'
    }

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('snapshot')
    a.add_argument('--interface',required=True)
    a.add_argument('--output',required=True,type=Path)
    c=sub.add_parser('compare')
    c.add_argument('--before',required=True,type=Path)
    c.add_argument('--after',required=True,type=Path)
    c.add_argument('--output',required=True,type=Path)
    args=p.parse_args(argv)
    if args.command=='snapshot':
        result=snapshot(args.interface)
    else:
        result=compare(json.loads(args.before.read_text()),json.loads(args.after.read_text()))
    if args.output.exists():
        p.error('Refusing to overwrite existing evidence')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f'Saved {args.output} ({result["kind"]})')

if __name__=='__main__':
    main()
