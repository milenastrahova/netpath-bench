# Evidence workflow — NetPath Bench v0.3

The tool works **offline**. The primary input is a ZIP of three measured source files, with canonical names:

- `bgp-failover-udp.json` — client summary
- `bgp-failover-udp.csv` — one line per attempted echo
- `bgp-failover-udp-events.json` — Windows host orchestration timestamps

An older `bgp-failover-analysis.json` is optional and only cross-checked, never used instead of raw samples.

## Verify an already collected ZIP (no Docker needed)

```powershell
py -3 scripts\review_evidence.py --evidence-zip .\NetPath_Failover_Evidence.zip --output-dir .\reports\review-original
```

Output: `field-review.json` with validated counters, SHA-256 source hashes, per-phase results, every unsuccessful sequence, and 250ms aggregate windows; `field-review.md` with measured results and explicit limitations; `field-timeline.svg` with individual successful RTTs and event boundaries. The public project includes a *derived* field report and source hashes but not raw customer/user evidence.

## Collect a repeated, individually labelled failover run

Do not run two experiments at once. The next example **stops the existing lab's primary transit container**, and restores it in the normal path, with a best-effort `finally` recovery. Run only with an isolated BGP lab and explicit consent.

```powershell
py -3 scripts\bgp_routed_trial.py --compose "..\BGP_Routing_Laboratory_v0.2\compose.yaml" --mode failover --allow-primary-stop --seconds 24 --fault-at 6 --fault-seconds 5 --run-id run02
py -3 scripts\bundle_trial.py --run-id run02 --reports .\reports --output .\reports\run02.zip
py -3 scripts\review_evidence.py --evidence-zip .\reports\run02.zip --output-dir .\reports\review-run02
```

The `--run-id` naming prevents overwriting earlier raw evidence. To analyze two or more **different** runs:

```powershell
py -3 scripts\compare_runs.py .\run01.zip .\reports\run02.zip --output .\reports\run-comparison.json
```

The comparison **does not pool individual packet attempts** across runs; it reports the median of run-level p99 values and how many runs contained missing echoes. Two independent runs are a minimum accepted input, **not sufficient** to claim a stable effect.

### Experimental controls for better comparisons

- Keep request size, interval, timeout, laptop/host load, Docker version and run duration as constant as possible.
- Collect baseline and failover in interleaved order, using fresh run IDs.
- Revalidate FRR baseline before and after each trial.
- Record routes during the failover via a parallel collector if reliable phase alignment is required.
- Do not claim on-wire UDP loss, HFT latency, or precise BGP convergence from application echo RTTs alone.
