"""Functional local-socket integration checks. These are not production-network benchmarks."""
import csv
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

binary = sys.argv[1]

def reserve_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

def invoke(*args, timeout=15):
    return subprocess.run([binary, *map(str, args)], capture_output=True, text=True, timeout=timeout)

port = reserve_port()
server = subprocess.Popen([binary, 'serve', '--port', str(port), '--bind', '127.0.0.1'],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    for attempt in range(100):
        if server.poll() is not None:
            raise RuntimeError("server exited before ready")
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.05):
                break
        except OSError:
            time.sleep(0.03)
    else:
        raise RuntimeError("server did not become ready")

    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        for mode in ('udp', 'tcp'):
            json_path = base / (mode + '.json')
            csv_path = base / (mode + '.csv')
            p = invoke(mode, '--host', '127.0.0.1', '--source-ip', '127.0.0.1',
                       '--port', port, '--count', 32, '--bytes', 64,
                       '--timeout-ms', 500, '--interval-us', 200,
                       '--json', json_path, '--csv', csv_path)
            assert p.returncode == 0, (mode, p.stderr, p.stdout)
            obj = json.loads(p.stdout)
            assert obj == json.loads(json_path.read_text()), mode
            assert obj['protocol'] == mode and obj['attempted'] == 32, obj
            assert obj['successful_echoes'] == obj['sample_count'] == 32, obj
            assert obj['source_ip'] == '127.0.0.1', obj
            assert obj['rtt_ms']['p99'] is not None, obj
            assert obj['started_at_utc'].endswith('Z') and obj['ended_at_utc'].endswith('Z'), obj
            with csv_path.open(newline='') as handle:
                rows = list(csv.DictReader(handle))
            assert len(rows) == 32 and all(r['status'] == 'ok' for r in rows), rows
            assert [int(r['sequence']) for r in rows] == list(range(32)), rows
            offsets = [float(r['start_offset_ms']) for r in rows]
            assert offsets == sorted(offsets), offsets
            assert all(float(r['rtt_ms']) > 0 for r in rows), rows
            print(f'PASS {mode}: 32 real loopback echoes; exact sequence/CSV/JSON checks')

        # Duration mode automatically raises the cap, exits after its requested interval.
        p = invoke('udp', '--host', '127.0.0.1', '--port', port,
                   '--duration-sec', 1, '--timeout-ms', 200, '--interval-us', 10000)
        assert p.returncode == 0, (p.stdout, p.stderr)
        obj = json.loads(p.stdout)
        assert 5 < obj['attempted'] < 1000 and obj['successful_echoes'] == obj['attempted'], obj
        assert obj['observation_duration_ms'] >= 900, obj
        print('PASS duration-limited UDP run with actual echoes')

        # Failed echo must record each attempt as an application-level failure (not claim wire loss).
        dead_port = reserve_port()
        p = invoke('udp', '--host', '127.0.0.1', '--port', dead_port, '--count', 3,
                   '--timeout-ms', 50, '--interval-us', 0,
                   '--csv', base/'lost.csv', '--json', base/'lost.json')
        assert p.returncode == 2, (p.stdout, p.stderr)
        obj = json.loads(p.stdout)
        assert obj['attempted'] == 3 and obj['successful_echoes'] == 0 and obj['timeouts'] == 3, obj
        with (base/'lost.csv').open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 3 and all(r['status'] == 'timeout' and r['rtt_ms'] == 'null' for r in rows), rows
        print('PASS UDP missing echoes represented as application timeouts')

        for args in [
            ('udp', '--port', 1),
            ('udp', '--source-ip', 'not-an-ip', '--port', port),
            ('serve', '--bind', 'not-an-ip', '--port', reserve_port()),
        ]:
            p = invoke(*args)
            assert p.returncode == 1 and ('ERROR:' in p.stderr), (args, p.stdout, p.stderr)
        print('PASS invalid parameters / IP addresses rejected')
finally:
    server.terminate()
    try:
        server.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        server.kill()
        server.communicate(timeout=3)
