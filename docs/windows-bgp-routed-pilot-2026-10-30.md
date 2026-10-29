# Four-AS routed UDP pilot — 30 October 2026 (local)

**Evidence status:** observed in an operator-supplied Windows PowerShell screenshot. The original client JSON/CSV and orchestrator event JSON remain on the operator's workstation and have **not yet been independently inspected** for this pilot. No detailed RTT numbers, hashes or convergence estimates are inferred from the screenshot.

## Experiment

A 15-second UDP echo pilot using the `netpath-bench-lab:1.0` image, with the C++ echo client in the Edge router network namespace (`10.10.10.1`) and the server in the Core router network namespace (`10.40.40.1`). Forwarding traverses the separately running four-AS FRRouting Docker lab, not NetPath Bench's own standalone bridge. **No fault was injected.**

```powershell
$lab = 'C:\Users\user\Downloads\bgp-routing-laboratory-main\bgp-routing-laboratory-main'
Set-Location 'C:\Users\user\Downloads\netpath-bench-main\netpath-bench-main'
py -3 scripts/bgp_routed_trial.py --compose "$lab\compose.yaml" --mode baseline --seconds 15 --run-id pilot261030003829
```

Prior to the pilot, `labctl.py check --timeout 120` passed the BGP sessions, route preferences and sourced ICMP on the four-router lab; the screenshot also shows that Docker image `netpath-bench-lab:1.0` was present.

## Observed terminal results

```text
PASS preflight: 4 BGP routers running and NetPath Bench Docker image present
CAPTURED 737 real UDP probes; 737 echoes, 0 timeouts
```

Three local files were saved in `reports/`:

- `bgp-baseline-udp-pilot261030003829.json`
- `bgp-baseline-udp-pilot261030003829.csv`
- `bgp-baseline-udp-pilot261030003829-events.json`

The `CAPTURED` status means the original probe completed and produced reports, **not** that all physical-network performance conditions were validated.

## What can be asserted

- The operator's locally running Windows/Docker configuration successfully completed an end-to-end UDP application echo pilot across the four-AS virtual routed topology.
- All **737/737** attempted application echoes succeeded within their configured timeout, with **0 observed timeouts** in this one short test.
- No conclusion can yet be made about p99 from this screenshot, about physical packet loss, about NIC wire timing, or about behavior during BGP failover.
- Source CSV/JSON verification and repeated independent baseline and fault runs are the next steps, described in [the reproducible experiment protocol](reproducible-bgp-study.md).

*Private, isolated education/research lab; no live exchange or production HFT connection.*
