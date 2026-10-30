# Isolated UDP packet capture: PCAP-to-application evidence

**Scope:** self-generated UDP echo traffic captured only on Linux Docker loopback `lo`. No real exchange, external network, host-interface capture, NIC tuning or Windows networking changes.

## Run from Windows 11 PowerShell

First update the local checkout after this change reaches `main`:

```powershell
git switch main
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-Pcap-Evidence.ps1
```

The launcher first builds a local Linux container from `Dockerfile.pcap` (Python 3.12 Alpine + tcpdump); downloading images/packages may require an Internet connection at build time. **The experiment container itself runs with `--network none --cap-drop ALL --cap-add NET_RAW --cap-add DAC_OVERRIDE`.** It cannot reach external networks, and the only capture is from `lo`, UDP port 19371.

Two baseline and two larger-buffer trials issue 120 measured UDP echo requests each, plus ten warmup requests per trial. The scripts produce a new non-overwriting evidence folder `reports/pcap-study-<UTC>-<random>/` and a ZIP of that folder. The existing repository `.gitignore` excludes `reports/`.

## Generated evidence

| File | Purpose |
|---|---|
| `socket-study/summary.json` | Trial conditions, effective buffers, session IDs, client port and application RTT percentiles |
| `socket-study/*.csv` | Per-request application outcomes with SHA-256 hashes in summary |
| `udp-loopback.pcap` | Classic PCAP captured by tcpdump in the isolated Linux network namespace |
| `packet-analysis.json` | Decoded UDP/TCP flow counts, sequence observations and capture-timestamp interarrival metrics |
| `correlation.json` | Cross-checks PCAP session/port/sequence request–reply observations against the audited application CSVs |
| `manifest.json` | SHA-256 hashes of source evidence files |

**Meaning of `APPLICATION AUDIT: PASS`:** CSV hashes, counts and RTT percentiles are internally consistent. It does not establish better performance.

**Meaning of `PCAP CORRELATION: PASS`:** all expected warmup and measured requests and replies were observed exactly once in the capture, with no unexpected NPS1 packets. A `REVIEW` status indicates missing, duplicate or unrecognized packets; **missing capture observations are not proof of physical packet loss**. If this happens, inspect JSON before drawing conclusions.

PCAP timestamps are neither calibrated physical NIC timestamps nor one-way wire delays. TCP/UDP laboratory traffic is not a production market-data feed. Capturing traffic can alter user-space timing, so comparisons against previous no-capture RTT experiments are not controlled.

## Test locally without a packet capture

```bash
python -m unittest discover -s tests -p 'test_pcap_capture_pipeline.py' -v
```

Five offline tests cover complete capture, missing PCAP reply with successful application delivery, wrong port, tampered CSV, and unexpected session. CI also builds the Docker image and performs a bounded real loopback PCAP capture.

## Next step

Upload the resulting evidence ZIP privately for independent review. Do not commit raw PCAPs from networks you do not own: they can contain sensitive information.
