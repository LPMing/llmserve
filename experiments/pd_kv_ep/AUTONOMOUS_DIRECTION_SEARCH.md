# Autonomous Packet-Level Direction Search

## Decision rule

Each candidate was required to pass a mechanism check, a matched control, a
mechanism-driven refinement and a neighboring-condition check before being
marked final-fail.  FlowSim residual backlog is not treated as packet queue,
and network-only replay is not treated as integrated TTFT/TBT.

## Ordered result

| direction | status | strongest evidence | decision |
|---|---|---|---|
| P1 cross-timescale ECN/DCQCN response | FINAL_FAIL for current frontend | ECN/CNP/rate response and flow FCT changed, but KV request barrier and EP CCT changed below 1% in long-KV 8/16 cases | fixed layerwise release and fresh QPs absorb transport response |
| P2 persistent-QP state inheritance | FINAL_FAIL for current backend | QP is created per replay flow and DCQCN state is not reused | adding persistence without runtime evidence would fabricate the mechanism |
| P3 finite generation-drain backpressure | FINAL_FAIL for current frontend | network/QP windowing exists, but no producer staging resource blocks Prefill | cannot infer TTFT from packet slowdown without a validated runtime buffer model |
| P4 hot-prefix provider egress barrier | PASS as packet/request-barrier motivation | two real Mooncake windows: 37.2–78.5% request remote-KV barrier headroom under same bytes and EP ledger | current strongest paper candidate; integrated serving validation remains required |
| P5 layerwise burst shaping | NOT RUN | stopped by first valid P4 candidate | do not search lower-priority directions before validating P4 |
| selective EP critical-flow protection | FINAL_FAIL refinement | TOP1/TOP5 had up to 39.9–57.7% worse EP P99 than EP_FIRST but 0% KV P99 headroom on the second/first window | static old-straggler protection causes new collective stragglers |

## Strongest candidate

The current publishable direction is:

> Hot-prefix remote-KV provider-egress concentration turns a max-over-required
> fetch handoff barrier into the serving-critical path of PD-disaggregated MoE
> inference, even when aggregate Clos utilization and Decode EP CCT remain
> nearly unchanged.

The mechanism is:

`real block reuse -> first-producer concentration -> provider NIC/QP
serialization -> completion skew -> last required remote KV block -> Decode
admission/TTFT barrier`.

This is stronger than an average-flow claim because the request completion is a
maximum over required blocks.  It is more specific than generic cache
replication only if the final paper keeps all of the following together:

1. real temporal hot-prefix fanout from Mooncake;
2. model-derived remote KV bytes and Qwen3 MoE EP traffic;
3. packet-level provider egress/QP serialization and queue telemetry;
4. request-level last-fetch barrier;
5. integrated TTFT/TBT/SLO validation;
6. replication warm-up and consistency cost.

## Why the selective-EP idea was not promoted

`EP_FIRST` is not simply protecting a few fixed critical flows.  A collective
barrier is endogenous: once a subset receives priority, the unprotected flows
can become the new barrier.  The offline oracle therefore gives no KV
bandwidth headroom.  This negative result prevents overclaiming a
critical-flow scheduler contribution from the current evidence.

## Required next phase for a CCF-B/A paper

The packet-level candidate is not yet a complete serving paper.  The next
phase should implement only the minimum validated extension needed for
integrated remote-KV replay:

1. carry block/provider identity from the Mooncake workload into the serving
   communication event;
2. let the integrated worker issue remote-KV fetches from a fixed provider map
   before Decode admission, without changing request scheduling;
3. compare first-producer placement with a deployable, pre-warmed balanced
   placement and account for replication bytes separately;
4. report TTFT P50/P95/P99, TBT/ITL P50/P95/P99, remote-fetch handoff and joint
   SLO on the same request set;
5. use native ns-3 only for one small representative packet validation after
   the integrated causal chain is established.

No final scheduler, placement algorithm, priority policy or transport change
is implemented by the current search.
