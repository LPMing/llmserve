# KV Movement vs. Decode EP: Consolidated Motivation Results

This document is the single summary of the completed motivation evidence. It
combines the former native motivation, matched-control, mechanism, FlowSim,
time-varying, and policy reports. Results are kept separate by simulator and
by evidence strength.

## Canonical small FlowSim motivation result

The current simple four-request result is the most compact reproducible
motivation experiment. It uses a 200-Gbps shared-spine topology, Qwen3-derived
communication, EP=2, and cross-request overlap only:

- three requests are pre-admitted Decode requests with repeated EP traffic;
- one later request performs P2D KV only during the Decode cohort;
- no request overlaps its own P2D handoff with its own Decode EP phase;
- `FAIR`, `EP_FIRST`, and `KV_FIRST` are data-plane policies, not scheduler
  delays.

The full source report and raw CSV/JSON are retained at
[`experiments/pd_kv_ep/results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md`](experiments/pd_kv_ep/results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md).

| case | policy | EP P99 CCT | EP change vs EP-only | KV FCT | KV change vs KV-only |
|---|---|---:|---:|---:|---:|
| large KV, 8,192 input tokens | FAIR | 0.127330 ms | +32.812% | 16.485118 ms | +2.344% |
| large KV, 8,192 input tokens | EP_FIRST | EP-only baseline | protected | 16.485118 ms | +2.344% |
| large KV, 8,192 input tokens | KV_FIRST | 12.895746 ms | +13,351% | KV-only baseline | protected |
| small KV, 128 input tokens | FAIR | 0.104877 ms | +9.393% | 0.280172 ms | +10.670% |
| small KV, 128 input tokens | EP_FIRST | EP-only baseline | protected | 0.280172 ms | +10.670% |
| small KV, 128 input tokens | KV_FIRST | 0.347531 ms | +262.495% | KV-only baseline | protected |

The large-KV point demonstrates the simple EP-protection case: EP suffers
substantially while the long bulk transfer changes little, so EP_FIRST is a
reasonable network policy for that state. The small-KV point shows why a policy
cannot be selected from EP CCT alone: KV_FIRST preserves KV but damages EP,
while EP_FIRST protects EP at a measurable KV cost. The reported queue maximum
is a residual fluid-queue metric from this FlowSim replay, not packet-level
ECN/PFC evidence.

The integrated FlowSim v5 rows also emit finite request-level TTFT, TPOT, and
token-TBT fields for the four-request sanity workload. They are metric-plumbing
and serving-integration evidence; the current run does not claim a normalized
paper SLO because it lacks an independently measured same-topology low-load
baseline.

## Layerwise P2D sensitivity

The same four-request FlowSim gate was replayed with the P2D realization
changed from one post-prefill cache chunk to one independent model-derived
transfer after every Qwen3 transformer layer. The full comparison, including
raw event ledgers, is retained at
[`experiments/pd_kv_ep/results/flowsim_layerwise_motivation_200g/layerwise/SIMPLE_MOTIVATION_REPORT.md`](experiments/pd_kv_ep/results/flowsim_layerwise_motivation_200g/layerwise/SIMPLE_MOTIVATION_REPORT.md).

| case | policy | P2D events for request 4 | EP CCT change vs EP-only | KV FCT change vs KV-only |
|---|---|---:|---:|---:|
| large KV, 8,192 input tokens | FAIR | 96 | +32.812% | 0.000% |
| large KV, 8,192 input tokens | EP_FIRST | 96 | 0.000% | 0.000% |
| large KV, 8,192 input tokens | KV_FIRST | 96 | +349.993% | 0.000% |
| small KV, 128 input tokens | FAIR | 96 | +5.469% | +0.283% |
| small KV, 128 input tokens | EP_FIRST | 96 | 0.000% | +0.486% |
| small KV, 128 input tokens | KV_FIRST | 96 | +5.469% | 0.000% |

This is a temporal-granularity sensitivity result, not a claim that the old
post-prefill percentages must remain invariant. Layerwise streaming preserves
the model-derived total bytes but spreads their injection over prefill. It
keeps the large-KV EP interference mechanism, while reducing the small-KV
EP-side effect in this particular four-request window. The policy choice must
therefore be re-evaluated after changing P2D granularity.

## Native model-driven matched result

The native Qwen3/ns-3 small study holds the Decode cohort and all model/request
parameters fixed, then shifts only the new P2D requests between an isolated
control and `MIXED`. A valid matched collective requires the same layer, decode
step, active request set, participants, payload, and flow count. The control
has zero exact P2D/EP overlap; `MIXED` has positive overlap on the same directed
link.

| P2D workload | model-derived KV bytes | matched EP P99 control -> mixed | ratio |
|---|---:|---:|---:|
| 1 x 512-token prompt | 50,331,648 | 6.545 -> 6.762 us | 1.033x |
| 1 x 2,048-token prompt | 201,326,592 | 6.545 -> 6.827 us | 1.043x |
| 2 x 2,048-token prompts | 402,653,184 | 6.545 -> 13.270 us | 2.028x |

The high point has two concurrent P2D populations, not merely a larger prompt.
The shared core link queue mean rises from 2.23 B in the control to 84,443.54 B
over matched EP windows. ECN, PFC, and drops are zero at this operating point.
This is a valid serialization/queue result, not a congestion-control result.

The older exact-routed A2A microbenchmark reports a 43.54% FAIR-to-EP_FIRST
P99 reduction (16.748 to 9.456 us). It remains a mechanism microbenchmark, not
a whole-run TTFT/TPOT gain.

## S64 real-trace network evidence and capacity correction

S64 bounded replay uses Qwen3 model-derived bytes, EP16, 200-Gbps endpoint
links, and selected windows rather than entire multi-million-request traces.
The early packet-level windows remain useful as historical native-ns-3
mechanism evidence, but the old FlowSim S64 policy table was generated before
parallel leaf--spine links were represented correctly and must not be used as
current KV-side evidence.

The corrected S16/S64 FlowSim topology keeps every identical parallel physical
link as one equivalent fluid bundle while retaining the endpoint access link.
For the valid S16 BurstGPT 64-request replay:

| policy/control | KV FCT P99 | EP CCT P99 | corrected comparison |
|---|---:|---:|---|
| KV_ONLY | 28.174421 ms | -- | KV baseline |
| FULL + FAIR | 28.174421 ms | 0.106508 ms | KV +0.00%; EP +7.97% |
| FULL + EP_FIRST | 28.174421 ms | 0.098644 ms | KV +0.00%; EP +0.00% |
| FULL + KV_FIRST | 28.174421 ms | 0.230031 ms | KV +0.00%; EP +133.19% |

The previously circulated S64/S16 high-pressure value
`EP_FIRST -> KV +24.68%` (and the related `32 Decode + 64 P2D -> +23.44%`
claim) came from the legacy sensitivity that collapsed a 3.2-Tbps
leaf--spine bundle to 200 Gbps. It is retained in the parallel-capacity audit
as a historical diagnostic, not as valid current motivation evidence. The
corrected model still supports the robust asymmetric result: KV_FIRST can
severely delay Decode EP, while EP_FIRST protects EP without a measured KV
penalty in the tested aggregate-capacity regime.

The small no-parallel topology and the early native ns-3 matched controls are
not affected by this particular parser correction. Network-only numbers must
still be kept separate from integrated serving TTFT/TPOT/TBT/SLO claims.

## Dynamic workload and attribution

The native time-varying workload contains an early Decode-rich phase, a burst
of new requests, and a later Decode-rich phase. It reaches 2.097152 Gbps P2D
demand, 1.515520 Gbps EP demand, five active Prefill requests, and five active
Decode requests. This establishes changing demand populations, not causal
latency attribution inside a multi-request prefill batch.

For causal analysis, use the following order:

1. select a trace window from serving-layer demand analysis;
2. replay identical events as FULL, KV-isolated, and EP-isolated controls;
3. require exact shared directed-link overlap in FULL;
4. compare collective CCT, KV completion, and serving metrics separately;
5. only then evaluate `FAIR`, `EP_FIRST`, and `KV_FIRST`.

## Conclusions and limits

- KV movement can materially degrade Decode EP CCT in a shared fabric.
- The largest bounded effect is cross-request P2D/EP overlap, not same-request
  overlap.
- Large KV can create an easy EP_FIRST case; small KV can expose a KV-side
  policy cost. The latter is the interesting candidate for adaptive control.
- Azure is an important negative: shared paths and overlap do not guarantee a
  large tail effect.
- No current document claims a universal 20% serving optimization, normalized
  SLO gain, or EP64 performance result.

The system definitions and telemetry rules are in
[`KV_EP_SYSTEM_AUDIT.md`](KV_EP_SYSTEM_AUDIT.md); trace and scale assumptions
are in [`TRACE_WORKLOADS.md`](TRACE_WORKLOADS.md) and
[`LARGE_SCALE_PLAN.md`](LARGE_SCALE_PLAN.md).
