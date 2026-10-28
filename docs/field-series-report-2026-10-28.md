# NetPath Bench — Independent Repeated BGP Failover Evidence Review

**Series:** `trial-set-01` · **Verification:** PASS · **Independent runs:** 2

| Run | Probes | Successful | Missing echo | Mean RTT (ms) | p99 (ms) | p99.9 (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `trial-set-01-01` | 1168 | 1167 | 1 | 0.248604 | 0.623379 | 0.926852 |
| `trial-set-01-02` | 1166 | 1165 | 1 | 0.285327 | 0.736688 | 1.089413 |

**Aggregate echo observations:** 2332 successful / 2334 attempts, 2 unsuccessful; observed unsuccessful ratio 0.0857%.

## Missed application echoes

- **trial-set-01-01** seq 296 (timeout): started ≈ **150.7 ms after** primary stop request in the approximate UTC alignment; exact network timing/causation is unproven.
- **trial-set-01-02** seq 295 (timeout): started ≈ **183.0 ms after** primary stop request in the approximate UTC alignment; exact network timing/causation is unproven.

## Scope and interpretation

- User-provided raw JSON/CSV/events and per-run ZIP bundles passed byte-level and semantic checks.
- An application echo timeout around the fault command is a reproducible observation in *these two tests*, not proof that BGP caused it.
- Do not call the 1/1168 and 1/1166 echo failures 'wire packet loss' or interpret request intervals as convergence time.
- p99/p99.9 percentiles are computed separately for successful echo replies for each run; pooled percentiles are intentionally absent.
- The published report retains only aggregate results and hashes, not user raw data.
- Further work: control (no-outage) runs, randomized fault timing, full directional captures, and clock methodology.

## Experiment provenance and acceptance

- Experiment was executed by the user on **Windows 11 with Docker Desktop**, with NetPath Bench and a four-router FRRouting lab.
- Two sequential 24-second runs were field-verified by the repeat-failover script; post-fault BGP recovery checks passed in both.
- Independent offline review: the entire user-supplied series ZIP, both per-run nested ZIP bundles and loose JSON/CSV/event files were checked for consistency and verified against stored SHA-256 hashes.
- **No wire-speed, market-data, HFT-grade latency, true network outage duration, receiver-side packet-loss percentage, or BGP convergence time was measured.**
- Two runs with the same method but without no-fault controls are insufficient for causal or general statistical conclusions.

## Further experiments before interpreting performance

1. Capture at least five no-fault controls and five fault trials with comparable traffic settings.
2. Randomize order and inject faults at different times to reduce scheduler/startup bias.
3. Add receiving-side sequence counters and capture/clock metadata, and distinguish delayed replies from missing acknowledgments.
4. Analyse each run separately. Do not pool p99 values across different runtime environments.
5. Capture route-state transitions alongside packet probes while keeping event-clock uncertainty explicit.
