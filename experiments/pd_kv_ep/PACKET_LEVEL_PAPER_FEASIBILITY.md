# Packet-Level Paper Feasibility: Hot-Prefix Provider-Egress Barrier

## 1. Problem statement

Real Mooncake block reuse can concentrate remote KV fetches at the first
producer/provider. The provider endpoint's packet/QP serialization then becomes
a request-level KV handoff barrier, even when aggregate leaf-spine capacity and
Decode EP collective CCT are nearly unchanged.

## 2. Why this is a useful packet-level candidate

The current FlowSim/serving replay can represent remote KV bytes and provider
identity, but native ns-3 adds physical packet paths, QP serialization, ECN,
PFC and per-link queue telemetry. The motivating phenomenon is not an average
KV flow slowdown: it is a max-over-required-fetches request barrier caused by
provider egress concentration.

## 3. Minimal motivating example

S16 / 8P8D / EP64 / Qwen3-30B-A3B / TP2 / 200Gbps / 4-KB packets / LAYERWISE,
with eight real Mooncake Tool/Agent requests. The same request ledger, model-
derived bytes, GateRouter EP matrix and EP issue times are replayed under:

- FIRST_PRODUCER: all matched hot blocks use their first trace-local producer;
- BALANCED_REPLICA_ORACLE: the same blocks are assumed already replicated and
  selected across providers, without adding replication traffic.

The oracle is a characterization bound, not a proposed implementation.

## 4. Strongest results

- Real low-output window: request remote-KV barrier mean 7.6049 -> 1.6328 ms
  (-78.5%), P99 7.6052 -> 2.0977 ms (-72.4%).
- Real hot-burst window: mean 6.0596 -> 3.8077 ms (-37.2%), P50 4.3741 ->
  2.0680 ms (-52.7%), P99 4.3743 -> 2.0809 ms (-52.5%).
- Low-output EP CCT P99 changes only 0.129628 -> 0.129793 ms (+0.13%).

The request metric is the max remote-KV completion per request; it is not a
sum of flow FCTs and is not called TTFT.

## 5. Packet-level causal timeline

`hot-prefix block reuse -> first-producer provider fan-out -> provider NIC/QP
serialization -> packet completion skew -> last remote KV fetch -> request
handoff barrier`.

The low-output window has seven remote fetches through two providers versus
fourteen providers in the oracle. Aggregate remote bytes remain 352 MiB and
EP events are identical. Native telemetry records paths, queue, ECN and PFC;
FlowSim fluid backlog is not used as packet evidence.

## 6. Request/barrier impact

This candidate passes the current packet/request-barrier motivation gate with
multiple real trace windows and >20% headroom. It does not yet claim integrated
TTFT/TBT because the native replay is network-only.

## 7. Required integrated validation

The next experiment must run the same legal cache placement in the integrated
serving path and report TTFT P50/P95/P99, remote KV handoff, TPOT/TBT and SLO.
It must include replica warm-up/replication bytes or a steady-state deployment
assumption, and compare against a deployable source-selection baseline.

## 8. Potential control knob (not implemented)

Cache placement/replication with provider-egress and request-barrier awareness.
No scheduler, routing algorithm, priority policy or transport mechanism is
implemented in this phase.

## 9. Positioning and review risk

The contribution cannot be claimed as generic "topology-aware placement".
The paper must establish the joint PD/MoE setting, real hot-prefix temporal
fanout, max-over-fetches handoff barrier, and packet-level provider egress
mechanism. The main risk is that a reviewer views the oracle as ordinary cache
replication; replication cost and integrated serving validation are mandatory.

## 10. Reproduction artifacts

Compact metrics: `results/p4_packet_provider/p4_summary.json`.
Builder control: `scripts/build_model_derived_replay.py` with
`--remote-provider-policy FIRST_PRODUCER` or
`BALANCED_REPLICA_ORACLE`. Temporary native packet outputs are listed in the
summary JSON; no full packet text trace is required.

## 11. Current decision

`P4_PASS_HOT_PREFIX_PROVIDER_EGRESS_BARRIER`.
P5 is intentionally stopped by the autonomous PASS rule. This is a strong
packet/request-barrier motivation candidate, pending integrated TTFT/TBT
validation; no serving metric is fabricated.
