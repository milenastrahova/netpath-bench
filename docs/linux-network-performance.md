# Linux network performance diagnostics (read-only)

This optional module adds **real Linux namespace counter collection** to the user-space TCP/UDP RTT work. It does NOT tune or reconfigure Windows, Linux, Docker, `sysctl`, NIC queues or CPU affinity. It uses only Python's standard library.

## What the counters represent

- `/proc/net/dev`: RX/TX packets, bytes, interface errors and drops for the selected **Linux interface**.
- `/proc/net/softnet_stat`: aggregate processed, dropped and time_squeeze values across CPUs in the current Linux **network namespace** (not specifically the interface).
- `/proc/net/snmp` TCP RetransSegs: aggregate network namespace TCP retransmissions; unrelated connections can contribute.
- Two snapshots collected in the same running Linux network namespace can be compared. The difference is a counter **delta**, not automatically a consequence of the experiment.

## Run in WSL2 or a Linux container

Within a Linux terminal with Python 3.10+ and access to this repository:

```bash
ip -br link
python3 scripts/linux_net_diagnostics.py snapshot --interface eth0 --output reports/before.json
# Run your own authorized baseline benchmark, or do no work at all.
python3 scripts/linux_net_diagnostics.py snapshot --interface eth0 --output reports/after.json
python3 scripts/linux_net_diagnostics.py compare --before reports/before.json --after reports/after.json --output reports/counter-diff.json
```

The tool refuses to overwrite old evidence; use fresh filenames for each run. If you want to run it from Windows, use `wsl` or an existing Linux Docker container, not native PowerShell. It does not require elevation for ordinary `/proc` reads; environments can restrict them.

## Interpretation checklist

1. Confirm both files are from the same interface and the same running namespace and boot.
2. Note process/CPU load, Docker/WSL2 version, time interval, and whether traffic was present.
3. Inspect RX/TX **errors and dropped** deltas and namespace-wide softnet and TCP retransmission counters.
4. Compare application RTT/p99 from NetPath Bench separately. Counter deltas **do not measure RTT**, hardware one-way latency or proven on-wire packet loss.
5. Check multiple matched baseline and intervention runs; do not claim reduced latency or causality if data do not support it.

Real physical NIC optimization requires suitable NIC hardware, drivers, timestamping and control of host conditions. This project currently does not include PTP or hardware timestamping.

## Safety and validation

Read-only implementation; no shell commands or network scans. Unit tests cover invalid inputs, malformed proc files, counter resets and delta calculations. Run `python -m unittest discover -s tests -p 'test_*.py' -v`.
