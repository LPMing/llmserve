# Steady-State PD KV–EP Contention Research

## Scope update (2026-10-08)

The user paused all Azure/BurstGPT/Mooncake real-trace experiments and redirected this phase to a controlled minimal 1P2D/EP16 shared-NIC/ToR gate. The in-flight Azure conversation-64 and BurstGPT-32 retries were stopped before completion; their manifests are marked `ABORTED_SCOPE_CHANGE`, and partial telemetry is excluded from results. This is not a negative result. Raw trace inputs remain untouched. The next step is topology/resource semantic audit, followed by controlled model-derived FlowSim discovery and bounded native ns-3 validation only if the mechanism passes.

Status: active characterization; no scheduler/policy design is being implemented.

## Current hypothesis

The candidate mechanism is not total request count by itself. It is natural coexistence of a mature Decode population producing recurrent MoE EP collectives with newly prefilling requests releasing layerwise P2D KV. The target is a phase-dependent contention knee that becomes visible at collective/request barriers, not merely a high link-queue sample or individual flow FCT.

Authoritative packet priority remains q0 reserved control (ACK/NACK/CNP/PFC), q1 policy-selected data, q3 ordinary data; q1/q3 use normal MMU/ECN/PFC treatment. Historical data that put user data in q0 are excluded. `CC_MODE=12` is only a frozen queue/ECN telemetry baseline, not DCQCN rate-feedback evidence.

## Azure16 diagnosis

See [`AZURE16_PHASE_OVERLAP_AUDIT.md`](AZURE16_PHASE_OVERLAP_AUDIT.md). The key finding is two-sided:

1. Cross-request steady-phase overlap is real: warm Decode EP overlaps another request's P2D for 24.910 ms; 29 directed links show flow-lifetime overlap; recurrent EP start period p50 is 98.664 us.
2. Barrier exposure is weak in FAIR: request KV handoff p99 rises only 0.00475% versus KV_ONLY; absolute EP CCT p99 rises 0.525% versus EP_ONLY.
3. This is not a high sustained population: time-weighted active Decode mean/max is 3.51/9 and active P2D mean/max is 1.12/10; the trace subset has only 198 output tokens.
4. Some sampled queue episodes span more than one EP period, but the queue log has no traffic-class attribution. Only 8.98% of critical/near-last EP peer rows meet the current KV path/time overlap criterion, and median collective straggler gap is 0.165 us.

The original integrated FlowSim ledger independently reports TTFT p99 132.644 ms and token-TBT p99 12.355 ms. These are serving baseline values, not the packet-replay counterfactual. Compact FlowSim re-analysis gives 5,280 collective records, 1,536 completed P2D flows, 330.748-us mean / 2.205-ms p99 KV-shard FCT, and 20.950-us mean / 45.644-us p99 EP CCT. The FlowSim timeline and definitions are in `results/steady_state/azure16/flowsim_integrated/`.

Current classification: `REAL_CROSS_REQUEST_OVERLAP + SAMPLED_QUEUE_EPISODES + WEAK_BARRIER_EXPOSURE`, not `NO_OVERLAP` and not yet an EP/KV barrier pass.

## Real-trace overlap mining

The pre-simulation candidate file is `workloads/real/slices/window_candidates.csv`, generated from arrival count, input-token pressure, and burstiness only—not measured latency. Examples:

- Azure conversation window 006210: 1,303 requests / 30 s, 43.4 RPS, 75.3k input tokens/s, burst ratio 4.08, max 177 arrivals in one second.
- Azure conversation window 007421: 2,643 / 30 s, 88.1 RPS, 141.8k input tokens/s, burst ratio 1.18.
- Azure code window 016812: 2,904 / 30 s, 96.8 RPS, 268.9k input tokens/s, burst ratio 1.20.
- BurstGPT window 148333: 536 / 30 s, 17.9 RPS, burst ratio 5.09, max 91 arrivals/s; its first 64 requests contain 7,703 input and 1,207 output tokens across a 3.0-s arrival span.
- Mooncake tool-agent candidates have higher input load (~67–80k input tokens/s) but lower request rate than Azure. Candidate path: `workloads/real/slices/mooncake_fast25/toolagent/`.

These are request-arrival selection statistics only. They are not claims about active Decode, P2D or EP overlap. A reproducible window must preserve original timestamps, order and token lengths.

## Controlled cohort construction

Not started. Only if real traces fail to cover steady Decode+P2D phase coexistence, form Cohort A and B from separate real rows. Preserve each cohort's intra-cohort spacing and model-derived communication. Cohort B may receive one global time shift, chosen from Cohort A's observed stable Decode interval before latency results are inspected. No synchronized arrivals or token/byte scaling.

## Telemetry definitions and limitations

- Decode-active: integrated scheduler admission through request completion.
- P2D-active: model-derived KV transfer intervals; request population is the union of its simultaneous layer/shard transfers.
- Warm Decode: after at least four emitted tokens; use request-level timestamps only as a stable-phase proxy unless token-to-EP-round provenance exists.
- EP periodicity: collective start/end and per-round CCT. `active_ep_flows` must not be inferred from one aggregate collective interval unless a compact event counter preserves member-flow starts/finishes.
- Prefill-active: do not use arrival-to-prefill-completion as compute-active. Existing Azure16 request ledger lacks a true Prefill compute-start timestamp.
- FlowSim telemetry: analytical fluid sharing/backlog, not physical packet queue/ECN/PFC.
- ns-3 telemetry: sampled physical MMU queue and packet counters. Current S8 replay is issue-schedule counterfactual; it does not feed network completions back into serving.

## Workload ledger

`STEADY_STATE_WORKLOADS.csv` records selected source windows and any allowed global cohort shift. The first rows capture authoritative Phase A and the currently selected natural-trace discovery case; incomplete runs are marked ABORTED and never contribute result metrics.

## Current strongest point

Azure16 FAIR network replay: EP collective CCT p99 +0.525%, request-level KV handoff p99 +0.00475% versus matched isolated controls. This is a negative/control point for barrier sensitivity despite real cross-request overlap. It does not satisfy the ≥20% motivation criterion.

## Phase-B integrated runs in progress

Historical progress snapshots follow. The two retries were subsequently
stopped on 2026-10-08 due to the scope change, and their manifests now say
`ABORTED_SCOPE_CHANGE`; no partial request/network telemetry from them is a
completed result. The historical “RUNNING” text below records what was known
at each snapshot, not the current process state.

### Update — 2026-10-08 10:39 UTC

The earlier BurstGPT run has since been stopped and marked `ABORTED_CODE_BUG`: preserved source row index 30 (`burstgpt:1155703`, arrival 2.0s) has 0 input/0 output tokens; `_schedule_waiting()` computed `num_new=0` and broke without removing it, leaving the FCFS head to block all later arrivals. Its batch284 telemetry is incomplete and excluded from results. The scheduler now retires this row as `EMPTY_ZERO_TOKEN_SOURCE_RECORD`, keeps it in the request CSV with TTFT/TPOT blank, and excludes it from serving percentiles; zero-prompt rows requesting generation fail loudly rather than hang. A direct regression check verifies that a valid row behind the empty row is admitted.

The corrected full 32-row BurstGPT replay is `steady_burstgpt_32_w148333_zero_fix1`; it preserves all row data and arrival times, including the empty record. Of the 32 source rows, 31 are metric-bearing model requests; the empty source record remains auditable but is not assigned fabricated latency. At the latest check it had started processing (collective batch 20), so no result is available yet. Azure conversation64 remains live and has progressed through collective batch418 (simulated time3.106s); its request CSV is not complete.

At the 10:40 UTC telemetry snapshot, both were still progressing: BurstGPT had reached EP round 28 (simulated time about102ms); Azure64 had reached EP round 429 (simulated time3.166s). Event files each had an in-progress final JSONL line, which was ignored; manifests remain `RUNNING` and no request CSV is complete.

At 10:45 UTC, Azure64 had advanced to EP round605 and BurstGPT to round46; both manifests were still `RUNNING`. The selected BurstGPT window has maximum source output length201 tokens; it has not reached completion, so partial events are not used for latency percentiles.

At 10:46 UTC, both remained active: Azure64 round619 and BurstGPT round53. Request CSVs are still absent; there are no serving metrics to report yet.

At 10:50 UTC, Azure64 had reached round646 and BurstGPT round72. Both remained `RUNNING`; their incremental ledgers are progress-only and are not being treated as completed distributions.

At 10:53 UTC, Azure64 had reached round661 and BurstGPT round89. Both remained live with request CSVs absent; only complete JSONL records were inspected.

At 10:57 UTC, Azure64 was at round694 (simulated3.939s) and BurstGPT at round140 (simulated0.564s); both were still active and incomplete.

At 10:59 UTC, Azure64 had reached round713; BurstGPT round169 at simulated1.49s, still before the preserved empty record's 2.0s arrival. Both remained incomplete.

At 11:02 UTC, Azure64 was at round733 (simulated4.17s) and BurstGPT at round200 (simulated0.686s); both manifests remained `RUNNING`, and the BurstGPT run had not yet reached the source row's 2.0s arrival.

- `steady_azure_conversation_64_w6210_retry1`: natural-order first 64 requests from Azure conversation window 006210; integrated FlowSim, FAIR, LAYERWISE, ACTUAL receiver, Qwen3-30B-A3B, S8/4P4D/EP32/200G. At 2026-10-08 10:39 UTC it remained `RUNNING`; collective telemetry had advanced through Decode batch418 at simulated 3.106s. No serving result is reported until its 64-request CSV is complete.
- `steady_burstgpt_32_w148333`: natural-order first 32 requests from BurstGPT window 148333 under the same model/cluster/network setup. At 2026-10-08 10:31 UTC it remained `RUNNING`, but the latest integrated graph was still batch284 and neither collective nor KV telemetry had advanced for about 103 minutes. The session had not returned an error or exit code. All 32 batch284 rank graphs parse; their tail contains later EP communication and sampler/store nodes, and an isolated empty-network execution completed in about 2.7 s. All 2,973 P2D flow events in the on-disk stream are matched through completion; the source trace's zero-token request is retained. This excludes malformed graph files and an unfinished P2D transfer in the visible telemetry, but does not identify cumulative-state cost or a Decode executor/control-plane wait. The run remains monitored and excluded from performance conclusions.
- Diagnostic only: batch284 contains 32 parseable rank graphs; ranks 32/33 include later collective IDs 2840004782/2840004803 and a final sampler/store tail. Submitting all 32 graphs to the same `AsyncGraphExecutor` with an empty network state completed in about 2.7 s. The frozen BurstGPT telemetry has 2,973 P2D flows each generated/requested/started/completed; its 31 request IDs correspond to 31 nonempty requests because source row 30 is explicitly retained with 0 input and 0 output tokens. Its last observed KV completion is at simulated 2.0425 s, while the last collective completion is at 2.1527 s. Together with the uncompleted later collective IDs in batch284, this points away from an unfinished reported KV transfer and toward the cumulative execution of the remaining Decode graph, but does not establish a deadlock or network cause. No request ledger exists yet; this is not a serving/network result.
- Current on-disk Azure telemetry snapshot has 6,527 P2D flows each requested/started/completed and 6,528 generated; the last visible generated event is request 63's final-layer shard (`303:p2d:30:62:47:2713600:521`) at simulated 1.3193 s. Do not interpret this temporary disk-snapshot discrepancy as an unmatched shard: `_register_flow` writes `KV_GENERATED` immediately before `network.submit`, whose release callback synchronously writes `KV_REQUESTED`, and the JSONL stream is buffered until later writes/run-end flush. The matching send and receive nodes both exist in `instance15_batch3` (rank30 node521 and rank62 node522). Final run flush and the completed request barrier will decide completeness; currently there is no evidence of a P2D pairing bug.
- Current manifests are still `RUNNING`; there are no complete request CSVs. Therefore no Azure64/BurstGPT32 TTFT, TBT, KV handoff, or CCT metrics are claimed from these partial ledgers.

## Next experiment

Superseded by the controlled minimal 1P2D/EP16 GO/NO-GO gate in
[`MINIMAL_IDEAL_KV_EP_RESEARCH.md`](MINIMAL_IDEAL_KV_EP_RESEARCH.md). Real-trace
experiments are paused; the source traces are retained and no additional trace
window search is authorized in this phase.

## Decision

`PAUSED_REAL_TRACE_EXPERIMENTS__MINIMAL_IDEAL_GATE_ACTIVE`

Reason: Phase A found real cross-request overlap but weak barrier exposure
(EP CCT P99 +0.525%; request KV handoff P99 +0.00475% in its replay controls).
The 64-request Azure and 32-request BurstGPT retries were stopped before
completion and are excluded. This phase now asks only whether the mechanism
survives in the legal minimal 1P2D configuration; no trace result is used to
manufacture a positive case.
