# Integrated FlowSim validation: serving metrics and KV/EP contention

This document is the audit record for the integrated FlowSim runs.  It is
separate from the earlier network-only replay results: all serving metrics in
this document come from the scheduler's per-request CSV.

## 1. What is measured

For request `r`, the simulator records the following timestamps and metrics:

| Metric | Definition used in this study |
|---|---|
| TTFT | `decode_first_token_time_ns - arrival`; this is the time from request arrival to completion of the first generated token. |
| P2D-ready | `p2d_kv_ready_time_ns`; all required P2D KV shards have completed. |
| Decode admission | `decode_admit_time_ns`; the request can enter the Decode scheduler after the P2D barrier. |
| TPOT | Mean of the scheduler's per-token `TBT` list after the first generated token. It is not a network-flow completion time. |
| TBT | The complete per-token decode interval list emitted in the request CSV. The list has `output_tokens - 1` elements; no missing values are imputed. |
| Request TBT mean/max | Mean and maximum of that request's TBT list. |
| E2E latency | The request CSV `end_time - arrival` value. |

The analyzer rejects a run if request IDs are duplicated, timestamps are not
finite or monotonic, TTFT disagrees with the Decode first-token timestamp, or
the TBT list length is not `output_tokens - 1`.  This is important because a
network-only completion time cannot be substituted for TTFT, TPOT, or TBT.

The validation implementation is
[`analyze_flowsim_integrated.py`](scripts/analyze_flowsim_integrated.py).

## 2. Correctness issue fixed before collecting these results

The first integrated FlowSim implementation could leave a Decode rank asleep
after a P2D completion or a peer-rank group completion.  The P2D flow itself
was complete, but the scheduler did not immediately issue the first Decode
round; this produced artificial multi-second TTFT/TBT gaps.  Waking every rank
on every completion fixed the symptom but created an event storm and excessive
memory use.

The current implementation uses a bounded, state-change wake protocol:

1. P2D completion invalidates only the relevant Decode rank group.
2. A group-wide EP round wakes the peer ranks in that same physical group.
3. At most one pending wake is kept per rank, and stale wake generations are
   discarded.
4. Completed flow records are streamed to JSONL and released from the verbose
   in-memory table; only compact completion timestamps remain for late waiters.

The resulting 16-request 100 Gbit/s low-load baseline has TTFT 95.354 ms and
TPOT 4.771 ms for every request, with no artificial multi-second TBT gap.  The
CSV-level lifecycle audit is clean for all primary runs.

## 3. Primary 100 Gbit/s experimental pairing

The primary experiment uses the native Qwen3-30B-A3B model/profile and the
same model-derived request communication for every policy:

- 1 Prefill + 2 Decode serving layout
  (`small_one_prefill_two_decode_pd_moe_ep2_100g.json`);
- Decode EP degree 2 and exact model/routing-generated P2D and EP flows;
- 2-leaf shared-spine topology, 100 Gbit/s in the primary result;
- 16 requests, input length 2048, output length 128;
- high-load arrival gap 20 ms, plus a zero-gap burst sensitivity run;
- matched low-load baseline arrival gap 3000 ms;
- FlowSim fluid backend with `FAIR`, `EP_FIRST`, and `KV_FIRST`;
- ideal `KV_ISOLATED` and `EP_ISOLATED` runs are counterfactual upper bounds,
  not deployable priority policies.

The earlier 25 Gbit/s and 10 Gbit/s runs are retained as pressure-sensitivity
and debugging references, not as the main network-speed result.

## 4. Primary 100 Gbit/s result

The source files are:

- low-load baseline:
  `results/flowsim_integrated/flowsim_s1p2d_100g_n16_baseline_v1.requests.csv`
- high-load FAIR:
  `results/flowsim_integrated/flowsim_s1p2d_100g_n16_fair_v1.requests.csv`
- high-load EP_FIRST:
  `results/flowsim_integrated/flowsim_s1p2d_100g_n16_epfirst_v1.requests.csv`
- high-load KV_FIRST:
  `results/flowsim_integrated/flowsim_s1p2d_100g_n16_kvfirst_v1.requests.csv`
- zero-gap burst sensitivity report:
  `results/flowsim_integrated/s1p2d_100g_n16_burst_report_v1.{json,csv,md}`
- integrated aggregate report:
  `results/flowsim_integrated/s1p2d_100g_n16_report_v1.{json,csv,md}`

All 16 request rows pass the lifecycle and TBT audit.

| Run | TTFT P99 (ms) | TPOT P99 (ms) | request TBT mean P99 (ms) | token TBT P99 (ms) | request TBT max P99 (ms) | joint SLO attainment |
|---|---:|---:|---:|---:|---:|---:|
| Low-load baseline | 95.354 | 4.771 | 4.808 | 4.827 | 4.827 | reference |
| FULL + FAIR | 1191.303 | 20.420 | 20.584 | 25.145 | 41.573 | 0/16 |
| FULL + EP_FIRST | 1197.537 | 20.336 | 20.540 | 25.145 | 48.327 | 0/16 |
| FULL + KV_FIRST | 1191.844 | 20.422 | 20.589 | 25.145 | 42.634 | 0/16 |

Relative to the matched low-load baseline, the FULL+FAIR run has:

- TTFT P99 = 12.494x, or +1149.4%;
- TPOT P99 = 4.280x, or +328.0%;
- token TBT P99 = 5.209x, or +420.9%.

This is a real serving-level degradation, not a flow-completion proxy.  It
establishes a high-load serving stress point.  At 100 Gbit/s, however, the
network attribution must be stated carefully: the measured KV/EP overlap is
small and the static policy gain is negligible:

- EP_FIRST changes TPOT P99 by -0.41% versus FAIR;
- EP_FIRST changes TTFT P99 by +0.52% versus FAIR;
- EP_FIRST changes request TBT maximum P99 by +16.25% versus FAIR;
- KV_FIRST changes TPOT P99 by +0.01% and TTFT P99 by +0.05% versus FAIR.

Therefore this 100 Gbit/s operating point does **not** justify claiming a
20% improvement from static EP_FIRST.  The large serving degradation is real,
but it is not yet a causal KV-versus-EP policy result; the request/control
path and compute pressure dominate this particular 2048-token workload.

## 5. Network audit for the same runs

For the 100 Gbit/s runs, FlowSim telemetry reports the same model-derived
bytes for each policy:

- KV movement: 3,221,225,472 bytes;
- Decode EP: 6,392,119,296 bytes;
- traffic is observed on two mixed directed links;
- completed flow records: 89,696--90,080 depending on policy;
- actual global KV/EP active-window overlap: 0.0057--0.0099.

The overlap is calculated from the union of actual flow start/end intervals,
and the mixed-link count is calculated per directed path.  It is not inferred
from the fact that both traffic classes exist.

The earlier 25 Gbit/s isolated controls remain useful attribution references,
but at 100 Gbit/s the measured policy differences are too small to claim a
meaningful static-priority benefit.  The zero-gap burst sensitivity has the
same qualitative result: TTFT becomes worse (FAIR P99 1491.488 ms), but
EP_FIRST still changes TPOT P99 by only about -0.41%.  This is a valid
negative result, not a reason to increase bytes artificially.

## 6. Historical 25 Gbit/s and 10 Gbit/s pressure sensitivity

The previous 25 Gbit/s report is retained at
`results/flowsim_integrated/s1p2d_25g_n16_report_v5.{json,csv,md}`.  It had
the same 1P2D/EP2 request setup, but is not the primary speed point:

| Run | TTFT P99 (ms) | TPOT P99 (ms) | token TBT P99 (ms) |
|---|---:|---:|---:|
| Low-load baseline | 144.067 | 5.165 | 5.225 |
| FULL + FAIR | 1974.479 | 21.886 | 28.182 |
| FULL + EP_FIRST | 1949.127 | 20.910 | 25.628 |
| FULL + KV_FIRST | 1958.660 | 22.091 | 29.333 |

At 25 Gbit/s, EP_FIRST reduced TPOT P99 by 4.46% versus FAIR.  This remains
a small-policy-gain stress reference, not a 20% optimization claim.

Source aggregate report:
`results/flowsim_integrated/s1p2d_10g_n8_report_v1.{json,csv,md}`.

| Run | TTFT P99 (ms) | TPOT P99 (ms) | token TBT P99 (ms) | joint SLO attainment |
|---|---:|---:|---:|---:|
| Low-load baseline | 241.553 | 5.989 | 6.045 | reference |
| FULL + FAIR | 1832.203 | 16.992 | 20.845 | 0/8 |
| FULL + EP_FIRST | 1767.248 | 15.159 | 19.580 | 1/8 |
| FULL + KV_FIRST | 1771.968 | 17.528 | 22.513 | 0/8 |

At 10 Gbit/s, EP_FIRST reduces TPOT P99 by 10.79% versus FAIR, still below
20%, and its request-level maximum TBT is slightly worse than FAIR.  This is
consistent with a state-dependent tradeoff, not evidence that EP_FIRST is
universally optimal.  Because the baseline has only eight requests, these
SLO numbers are diagnostic and must not be used as final paper claims.

## 7. SLO definitions and statistical status

The analyzer stores three normalized profiles:

1. `SLO_PROFILE_MFS`: TTFT threshold = 3x the matched low-load baseline P50.
   TPOT is not attributed to the MFS paper unless an explicit TPOT factor is
   supplied.
2. `SLO_PROFILE_SPLITWISE`: baseline-normalized TTFT factors 2x/3x/6x at
   P50/P90/P99 and TPOT/TBT factors 1.25x/1.5x/5x.
3. `SLO_PROFILE_DIST_SERVE`: joint TTFT <= 3x baseline P50 and TPOT <= 1.5x
   baseline P50; target attainment is 90%.

The analyzer marks a report `invalid_for_paper` when the reference baseline is
not low-load or has fewer than 10 requests.  This does not make a run
invalid as a correctness test; it prevents an eight-request result from being
presented as a stable P99/SLO estimate.

The primary 16-request run is a valid integrated serving result, but its P99
is still an order-statistic over a small sample.  A CCF-A submission would
need at least multiple independent seeds and substantially larger matched
windows, with confidence intervals or bootstrap intervals, before using the
exact P99 values as the final headline numbers.  The present report is the
correctness and motivation gate, not a claim that the final evaluation is
complete.

## 8. FlowSim observability boundary

FlowSim is a flow-level fluid model.  It can report:

- per-flow bytes, start/end, class, request, collective, source/destination,
  and directed path;
- residual fluid in active flows;
- flow-level completion and class overlap;
- integrated TTFT, TPOT, TBT, E2E latency, queueing delay, throughput, and
  normalized SLO attainment through the serving frontend.

It cannot honestly report packet-switch quantities that it does not simulate:

- packet queue occupancy or packet queue P50/P99;
- packet count and serialization at MTU granularity;
- ECN marking, PFC pause, packet drops, or retransmission behavior.

`queue_bytes` in FlowSim is residual fluid, not a switch packet queue.  The
analysis therefore sets packet queue/ECN/PFC/drop availability to false rather
than relabeling a fluid residual as a hardware telemetry measurement.  If the
paper requires those metrics, the same serving trace and matched window must
be replayed in HTSim/ns-3 or a packet-capable backend.

## 9. Current research conclusion

The integrated implementation now supports a defensible end-to-end chain:

`request arrival -> prefill -> model-derived P2D KV -> Decode admission ->
group-wide EP -> first token and token intervals -> TTFT/TPOT/TBT/SLO`.

The current data supports the following statement:

> Under the tested high-concurrency 1P2D workload, shared model-derived KV
> movement and Decode EP traffic produce large serving-level tail degradation.
> At 100 Gbit/s, however, the selected 2048-token workload has very little
> measured KV/EP overlap and static EP_FIRST provides no meaningful recovery;
> the 25 Gbit/s point shows only a modest policy effect.  EP_FIRST's
> sufficiency is therefore not established, but neither is a 20% policy gain.

It does **not** yet support the stronger statement that a static policy gives
or needs a 20% improvement.  The next publishable experiment should vary
arrival load and KV/EP composition, keep the same request IDs and model
configuration for FULL/isolated counterfactuals, and repeat the selected
windows across seeds.  A likely legitimate design space is adaptive KV
admission/concurrency or time-varying KV/EP bandwidth sharing, but no such
benefit is claimed until the repeated integrated measurements demonstrate it.
