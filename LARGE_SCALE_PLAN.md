# Large-Scale Plan, SLOs, and Replay Policy

This document consolidates topology, model/parallelism, placement, SLO,
testbed, and cost-planning notes. It describes what is measured versus what is
only a design artifact.

## Scale hierarchy

| scale | servers | physical GPUs/endpoints | P:D | leaves | Decode EP pools | status |
|---|---:|---:|---:|---:|---:|---|
| S4 gate | 4 | 32 | 2:2 | 1 | 1 | communication gate only |
| S8 gate | 8 | 64 | 4:4 | 1 | 1 | communication gate only |
| S64 | 64 | 512 | 32:32 | 8 | 16 | primary large-scale target |
| S256 | 256 | 2,048 | 128:128 | 32 | 64 | reachability/scaling gate |

Each server has eight GPUs, scale-out links are 200 Gbps, and the generated
Clos/fat-tree is 1:1 non-oversubscribed. S64 rank dimensions are `[2, 8, 16,
2]`; S256 dimensions are `[2, 8, 64, 2]`. The physical GPU/rank ledger keeps
GPU, server, unit, rack, leaf, P/D role, TP, EP, and DP identity. Intra-node
communication must remain on the native NVSwitch/NVLink dimension when the
backend supports it; scale-out Ethernet is for inter-server traffic.

The former 128-GPU design (2 x 32-GPU Prefill plus 64-GPU Decode) remains a
useful intermediate topology sketch, but it is not a measured result. No EP64
claim is made without a validated profile and collective participant mapping.

## Model and communication mode

The primary model is Qwen3-30B-A3B-Instruct-2507, BF16. Current trusted
profile coverage supports the small TP/EP configurations and EP16 replay used
in bounded S64 studies. `NATIVE_AG_RS` is retained for upstream semantics;
`A2A_P2P` is preferred for route-level large-scale discovery. EP degree must
match the profile and rank mapping; it must not be inflated for appearance.

## KV placement variants

Two supported placement questions are distinct:

1. KV cached on serving/Prefill workers;
2. KV cached on dedicated remote cache endpoints, one per leaf in the bounded
   placement variant.

The remote path preserves block identity, source, destination GPU, request ID,
and model-derived bytes. It is suitable for studying hot-prefix one-to-many,
many-to-one, incast, and Decode-ingress pressure. It does not replace P2D.

## SLO accounting

Every trace/model/topology/load point needs its own independently measured
low-load baseline. Thresholds are never borrowed across traces or changed
after observing a result.

| profile | TTFT | TPOT/TBT | joint output |
|---|---|---|---|
| MFS-style | 3x low-load TTFT | report separately as normalized sensitivity; do not attribute this rule to MFS without support | attainment |
| splitwise | P50/P90/P99 = 2x/3x/6x | P50/P90/P99 = 1.25x/1.5x/5x | per-metric attainment |
| DistServe-style | report same-trace normalized constraints | report same-trace normalized constraints | fraction meeting both; goodput at >=90% |

Each valid serving run saves TTFT, TPOT/ITL, TBT, E2E latency, throughput,
goodput, separate attainment, and joint attainment. Network-only replay is not
allowed to fill serving metrics or SLO fields.

## Replay and telemetry policy

- Run trace conversion and demand pre-analysis before packet simulation.
- Use S4/S8 only for code/path gates.
- Use S64/S256 for real-trace replay, with at most 25,000 requests per run.
- Keep discovery telemetry aggregate and compact; sample queue/link state at a
  coarse interval such as 1 s.
- Enable per-flow paths, exact overlap, queue, ECN/PFC, and drops only on
  selected candidate windows.
- Use 0.5x, 1.0x, 1.5x, and 2.0x inter-arrival scaling only after a low-load
  baseline and capacity check; preserve request order, tokens, and prefix
  relations.
- Run FULL, KV-isolated, and EP-isolated counterfactuals on the same trace
  slice before drawing causality.

The cost estimate is dominated by packet count, ASTRA graph/controller work,
A2A route expansion, and detailed telemetry. The completed native policy and
candidate windows are retained as bounded feasibility evidence; full Azure and
BurstGPT releases are not packet-level targets.

## Metrics required for a large-scale window

Network: KV bytes/request and completion P50/P95/P99, KV concurrency, EP bytes
and CCT P50/P95/P99, collective rate, mixed-link count, overlap fraction, link
utilization, queue P50/P95/P99/max, ECN, PFC, and drops.

Serving: TTFT, TPOT/ITL, TBT, E2E latency, queueing, throughput, goodput, and
joint SLO attainment.

The timeline must retain request/session ID and distinguish `P2D`,
`REMOTE_KV_FETCH`, `DISPATCH`, and `COMBINE`; “both classes in one time bin” is
not enough for a shared-link claim.

## Testbed-facing operating points

The current reproducible small points are:

- low: two active Decode requests plus one 512-token P2D request;
- moderate: the same Decode cohort plus one 2,048-token P2D request;
- KV-heavy: the same Decode cohort plus two simultaneous 2,048-token P2D
  requests;
- high-concurrency policy point: 64 trace-ordered BurstGPT requests with
  model-derived P2D and EP traffic.

For hardware replay, preserve input/output distributions, arrival spacing,
P/D placement, EP degree/top-k/routing, P2D shard bytes, collective frequency,
active Decode count, burst bandwidth, and queue/ECN/PFC counters. Network CCT
ratios from replay are not substitutes for client-visible TTFT/TPOT.

## Scale stop rules

S256 remains a gate unless it has complete event coverage and a clearly stated
telemetry model. If native packet cost prevents a valid run, report the maximum
validated scale and retain the result as a limitation. Do not replace it with
synthetic flow bytes, extreme oversubscription, forced paths, or fabricated SLO
values.
