# Network and Serving Baselines

## Compared configurations

| Comparison | What changes | What it establishes |
|---|---|---|
| A0 vs A1 QUERY | Destination cache query is enabled, payload remains full | Query-only path changes neither FlowSim bytes nor serving event timestamps |
| A0 vs A2 DELTA | Destination prefix is reserved and repeated prefix payload is omitted | Model-derived P2D bytes fall 99.7808%; handoff can complete by sampler readiness |
| A0 vs A2 sampler events | Same compute workload, full vs delta transfer | Sampler-ready proxy is 27.068 ms in both; no TTFT benefit is supported |
| B0 4P1D vs B1 3P2D | Static Prefill/Decode instance split under fixed active-rank budget | Mean full-session completion improves 4.56%; worst session regresses 7.26% |
| B1 3P2D full vs B2 3P2D DELTA | Same static placement, full vs delta prefix payload | All measured serving/session times are identical in this workload |

All network measurements above are FlowSim fluid service/backlog, not packet behavior. Bytes are model-derived. The model's TP2 rank mapping and physical rail capacity are held as described in `05_3P2D_RESOURCE_MAPPING.md`.

## Strong single-side baseline and incremental result

The strongest measured full-session mean among the tested fixed configurations is B1/B2 3P2D at 201.797 ms versus 211.436 ms for 4P1D, a 4.56% mean gain. It does not meet the 15% target and worsens the slowest session. Adding DELTA prefix handoff to 3P2D changes bytes, but gives exactly 0% additional measured session-latency improvement in B2 relative to B1.

In 4P1D, cache-delta changes mean full-session completion by 2.59%; it is not evidence that a joint network/Serving controller beats the best single-side baseline. No complete cache-aware placement or network-feedback policy was evaluated.

## Not run and why

- No network-only pacing/scheduling baseline: A's corrected event analysis found no valid TTFT benefit, and B2's bytes changed without changing serving timestamps. There is no positive incremental opportunity to justify a wider controller comparison.
- No network-signal feedback (ACK goodput, QP rate, ECN, queue): Gate C did not establish joint incremental headroom; Gate D is therefore not entered.
- No dynamic role switching: placement migration/resource/cache transition costs are unsupported.
- No 2P3D: the current one-static-receiver-per-Prefill aggregate graph cannot represent three Decode destinations correctly.
- No ns-3: no qualifying serving-level pass; the existing packet replay is not an integrated serving callback.

## SLO and tail metrics

No SLO thresholds were predeclared for this controlled four-session workload. Mean and per-session completion are reported; P95/P99 are intentionally omitted. Network FCT is not presented as TTFT, and the logged `TTFT` field is not treated as client-visible TTFT where it equals graph/P2D completion after sampler execution.
