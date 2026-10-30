#!/usr/bin/env python3
"""Capture only test-generated UDP loopback traffic in an isolated Linux container.

Requires tcpdump and CAP_NET_RAW inside Docker; no host-interface access.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from socket_buffer_study import write_study
from audit_socket_study import audit
from packet_trace_review import review
from correlate_pcap_echo import correlate

def stop_capture(proc):
    if proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    if proc.stderr: proc.stderr.close()

def start_capture(output, port):
    args=['tcpdump','-i','lo','-p','-U','-s','0','-w',str(output),f'udp and port {port}']
    proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE,text=True,bufsize=1)
    selector=selectors.DefaultSelector()
    selector.register(proc.stderr,selectors.EVENT_READ)
    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if proc.poll() is not None:
                raise RuntimeError('tcpdump exited before capture started: '+proc.stderr.read(1000))
            if selector.select(timeout=0.2):
                line=proc.stderr.readline()
                if 'listening on lo' in line: return proc
                if 'permission denied' in line.lower() or 'error' in line.lower():
                    raise RuntimeError('tcpdump: '+line.strip())
        raise RuntimeError('tcpdump startup not confirmed; aborting instead of recording partial evidence')
    except BaseException:
        stop_capture(proc)
        raise
    finally: selector.close()

def execute(output_root, repetitions, count, port):
    if sys.platform!='linux': raise RuntimeError('Linux container required')
    if not shutil.which('tcpdump'): raise RuntimeError('tcpdump missing; build Dockerfile.pcap first')
    if not (1<=repetitions<=5 and 12<=count<=500 and 1024<=port<=65535):
        raise ValueError('Capture settings exceed safety limits')
    run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    folder=output_root/('pcap-study-'+run_id)
    folder.mkdir(parents=True,exist_ok=False)
    capture=folder/'udp-loopback.pcap'
    study_dir=folder/'socket-study'
    # Docker --network none may leave lo administratively DOWN. This alters only the container namespace.\n    subprocess.run(['ip', 'link', 'set', 'dev', 'lo', 'up'], check=True)\n    print('Starting scoped tcpdump on Docker lo UDP port',port,flush=True)
    proc=start_capture(capture,port)
    try:
        write_study(study_dir,repetitions,count,interval_ms=1.,timeout_ms=200,
                    warmup=10,server_port=port)
    finally:
        stop_capture(proc)
    if not capture.exists() or capture.stat().st_size<=24:
        raise RuntimeError('PCAP capture is missing or empty')
    if capture.stat().st_size>15*1024*1024:
        raise RuntimeError('Capture exceeds 15MiB safety limit')
    app_audit=audit(study_dir/'summary.json')
    pcap_report=review(capture)
    correlation=correlate(study_dir/'summary.json',capture,port)
    (folder/'packet-analysis.json').write_text(json.dumps(pcap_report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    (folder/'correlation.json').write_text(json.dumps(correlation,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    manifest={
        'schema_version':1,'kind':'isolated_linux_loopback_udp_packet_capture',
        'capture_interface':'lo','capture_port':port,
        'environment':'Docker isolated network namespace --network none',
        'app_audit':app_audit,'correlation_status':correlation['status'],
        'pcap_packets':pcap_report['decoded_tcp_udp_packets'],
        'file_sha256':{str(f.relative_to(folder)):hashlib.sha256(f.read_bytes()).hexdigest()
                       for f in sorted(folder.rglob('*')) if f.is_file()},
        'limitations':['Self-generated container loopback only; not Windows or physical NIC traffic',
                       'PCAP capture timestamps are not wire one-way latency',
                       'Application and packet capture evidence must be evaluated separately']
    }
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    zip_path=output_root/(folder.name+'.zip')
    with zipfile.ZipFile(zip_path,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob('*')):
            if f.is_file(): z.write(f,arcname=str(f.relative_to(folder)))
    print('APPLICATION AUDIT:',app_audit['status'],app_audit['replies'],'/',app_audit['attempts'],flush=True)
    print('PCAP CORRELATION:',correlation['status'],'observed frames:',correlation['observed_udp_echo_frames'],flush=True)
    print('EVIDENCE ZIP:',zip_path,flush=True)
    if correlation['status']!='PASS':
        raise RuntimeError('Capture review flagged missing/duplicate/unexpected packets; inspect correlation.json')
    return manifest

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-root',type=Path,default=Path('reports'))
    p.add_argument('--repetitions',type=int,default=2)
    p.add_argument('--count',type=int,default=120)
    p.add_argument('--port',type=int,default=19371)
    a=p.parse_args(argv)
    execute(a.output_root,a.repetitions,a.count,a.port)

if __name__=='__main__': main()
