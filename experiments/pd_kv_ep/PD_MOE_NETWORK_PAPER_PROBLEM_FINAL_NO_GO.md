# PD-disaggregated MoE network problem search: bounded final NO-GO

## Decision

`PD_MOE_NETWORK_PAPER_PROBLEM_FINAL_NO_GO`

In the tested legal configurations and real-trace windows, the search found
network effects but no candidate that simultaneously demonstrates at least
20% network-critical headroom and at least 10% integrated TTFT, TBT, or TPOT
headroom. This is a bounded negative conclusion for the evidence and simulator
semantics listed below; it is not a claim that every production deployment is
free of such problems.

No scheduler, routing, transport, or priority solution was implemented.

## Evidence summary

| Candidate | Strongest observation | Outcome |
|---|---|---|
| P1 KV-ready × Decode scheduling boundary | Natural boundary wait was at most 8.75% and 6.72% of TTFT. Prior largest wait was 6.568 ms / ~6.5% TTFT; adjacent point 1.418 ms / ~1.2%. Matched Azure policies left P2D-ready unchanged. | Below network and serving headroom gates. |
| P2 Decode admission/capacity knee | The previous P/D handoff bypassed `max_num_seqs`; the ordinary capacity gate is now represented. Unit tests pass. Tested natural windows had one active request per Decode scheduler against configured limit 128. | No natural capacity knee in tested windows. No artificial cap was introduced. |
| P3 POST_PREFILL dependency | D64 residual drain +19.51%, TTFT +4.62%; adjacent D32 residual drain +10.47%, TTFT +3.30%. | Below required network and serving thresholds. |
| P4 first-token iteration quantization | Scheduler-admit→first-token averaged 5.650 ms (6.68% of TTFT) in Conversation-16 and 5.140 ms (3.89%) in Code-32; matched policy changes were negligible. | No natural network-induced iteration-phase shift; serving interval below 10%. |
| P5 natural final KV shard | Final-shard residual drain +23.568%, while request handoff changed +0.0115%; final shard completed 2.367 ms before Prefill completion. | Network delay was absorbed by release slack before the request barrier. |
| P6 corrected EP64 CCT→TBT | Controlled aligned cohorts: EP CCT mean −44.25%, P99 −50.54%; token TBT mean −14.71%, P99 −21.72%; TPOT −17.26%. But natural Azure Conversation-16 and Code-32 matched pairs had all listed policy effects below 0.3%; KV-ready was identical. | Controlled mechanism bound only; no natural-trace motivation PASS. |
| P7 other natural dependency | No unclosed, concrete dependency signal remained; observed effects mapped to tested boundaries, release slack, or controlled-only contention. | Not opened; no evidence-led P7 candidate. |

The corrected EP64 controlled result is not discarded. It establishes that the
FlowSim model can express strong policy sensitivity when two cohorts are
explicitly aligned. It does not establish that the same effect occurs in the
tested real arrival traces or that it is a novel, naturally occurring
serving problem.

## Natural matched EP64 runs

Both runs used the corrected S16 / 128-GPU configuration: 8 Prefill and 8
Decode servers, 2×200-Gbps shared NIC capacity per server, a 200-Gbps 1:1 Clos,
Qwen3-30B-A3B-Instruct-2507, EP64, model/routing-derived communication,
`LAYERWISE`, actual P2D receivers, and A2A_P2P. Only the policy changed
between FAIR and EP_FIRST.

### Azure 2024 Conversation

- 16 consecutive requests from the saved 30-second window; original arrivals
  and token lengths retained; 16/16 valid.
- 2,353,299,456 model-derived KV bytes, 34,272 EP collectives, 1,514 TBT
  intervals.
- EP_FIRST vs FAIR: TTFT mean −0.0028%, TBT mean −0.00067%, TPOT mean
  −0.00005%, EP CCT mean −0.00058%; P99 EP CCT/TBT unchanged; P2D-ready
  distribution identical.

### Azure 2024 Code

- 32 consecutive requests from a separate saved 30-second window; original
  arrivals and token lengths retained; 32/32 valid.
- 9,400,123,392 model-derived KV bytes, 22,464 EP collectives, 564 TBT
  intervals.
- EP_FIRST vs FAIR: TTFT mean −0.0118%, P99 −0.0076%; TBT mean −0.0231%,
  P99 −0.2754%; TPOT mean −0.0090%; EP CCT mean −0.0371%, P99 unchanged;
  P2D-ready distribution identical.

These two different Azure request families provide replicated negative
evidence. They do not cover every trace or deployment.

## Critical-path artifacts and definitions

- `results/pd_moe_phase_search/REQUEST_CRITICAL_PATH_TRACE.csv` contains 96
  request/policy rows with request-level KV issue/completion events, P2D
  readiness, Decode handoff/admission, first token, and TTFT consistency.
- `results/pd_moe_phase_search/SERVING_CRITICAL_PATH_BREAKDOWN.csv` contains
  96 corresponding event-segment breakdowns. The segments close exactly to
  recorded TTFT. P2D flow activity overlaps the arrival-to-Prefill lifecycle
  and is not double-counted as a separate additive TTFT interval.
- `scripts/export_request_critical_path.py` recreates these two files from the
  source trace and retained event logs.
- `PD_MOE_PROBLEM_SEARCH.csv` is the candidate ledger.

FlowSim queue measurements in these results mean analytical fluid backlog,
not packet-buffer occupancy, ECN, PFC, packet drops, or DCQCN behavior.

## Capacity semantic correction and validation caveat

`DecodeScheduler.add_decode()` previously inserted every P/D-ready request
directly into `running`, bypassing `max_num_seqs`. The correction keeps the
request's original arrival intact, reserves the transferred KV blocks at
handoff, and queues only when the configured running-sequence limit is full.
It does not change the under-capacity fast path or introduce a new policy.

Three targeted tests pass:

- a full Decode sequence limit queues a ready handoff;
- the request remains queued while the limit is full and is admitted after a
  slot opens;
- under-capacity admission is unchanged and queued P/D handoffs are ordered by
  Decode-ready time.

A one-request real-trace FlowSim smoke run is valid and records the new
capacity fields: `0/128` running at P2D handoff, first-batch active count 1,
waiting queue 0, batch size 1, and `num_decode=1`. The targeted repository
clock validation (`pd`,
`pd_per_instance_config`, `moe_pd`) differs from recorded clocks in all three
scenarios. This workspace already had many unrelated modified simulator and
ASTRA files before this correction, so the drift cannot be attributed to this
change alone. Recorded baselines were not refreshed. This caveat is retained;
the new capacity semantics are supported by focused tests and a complete
single-request smoke run, not by a clean full-repository validation. Re-running
the `pd` clock case with the old under-capacity status-update order produces
the same 1,028,919,538 clocks, so this mismatch is not caused by the new
capacity branch in the unsaturated scenario.

## Why the search stops here

The available natural-trace evidence has neither the needed network oracle
headroom nor the required integrated serving improvement. The only large
serving delta is from a controlled synchronized cohort, which fails the
natural-workload gate. Increasing request counts, reducing `max_num_seqs`,
lowering bandwidth, synchronizing arrivals, or otherwise forcing a contention
knee would not repair that evidence gap; those steps would manufacture the
operating point the search was meant to discover.

Reopen the search only when new runtime-grounded evidence is available, such
as a naturally saturated Decode configuration, a production trace with a
barrier-critical P2D/EP window, or a deployment topology with documented
resource sharing that is not represented here.
