# Native P2D-KV vs. Decode-EP Experiments

This directory contains request-driven experiments for the question:

> Does native P2D KV traffic interfere with active Decode-side MoE EP
> communication on a shared detailed-network path?

The primary result uses Qwen3 model semantics, native ASTRA-Sim/ns-3 flows,
and a matched arrival-offset control. It never accepts a user-specified KV or
EP flow size.

## Layout

| Path | Purpose |
|---|---|
| `configs/` | native P/D+MoE cluster configs, ns-3 topologies, 128-GPU metadata generator |
| `workloads/` | request JSONL inputs; `autonomous/` contains paired controls |
| `results/` | raw/derived native artifacts; no partial artifact is used as a result unless marked valid |
| `figures/` | timelines and compact paper-facing figures |
| `autonomous_search.py` | writes native matched workloads, runs controls, matches CCTs, updates table |
| `analyze_shared_link_mechanism.py` | reports every exact shared directed link |
| `traffic_timeline.py` | aggregates native time-varying demand |
| `audit_trace.py` | basic trace/timeline audit |
| `plot_motivation.py` | regenerates M1--M4 from completed artifacts |

## Evidence rule

1. Hold model, topology, requests, routing, and payload generation fixed.
2. Shift only B P2D request arrival between isolated control and `MIXED`.
3. Match A-only Decode collectives by semantic metadata and payload.
4. Require zero exact P2D/EP overlap for the control and positive overlap on
   the same directed physical link in `MIXED`.
5. Measure EP CCT as the collective's last communication completion minus
   its start.

## Reproduce a small native point

```bash
python3 experiments/pd_kv_ep/autonomous_search.py \
  --label two_prefill_b2_2048_a2_replay --iteration 1 \
  --a-input 64 --a-output 64 --a-count 2 \
  --b-input 2048 --b-output 1 --b-count 2 \
  --overlap-arrival-ns 10000000 --baseline-arrival-ns 500000000 \
  --cluster-config experiments/pd_kv_ep/configs/small_two_prefill_pd_moe_ep.json
```

Then regenerate all-link evidence and paper-facing figures:

```bash
python3 experiments/pd_kv_ep/analyze_shared_link_mechanism.py
python3 experiments/pd_kv_ep/plot_motivation.py
```

## Completed result scope

The valid completed points are `two_prefill_b1_512_a2`,
`two_prefill_b1_2048_a2`, and `two_prefill_b2_2048_a2`. The high point has
matched EP P99 CCT slowdown 2.028x. EP=4/A4 artifacts are retained for
debugging/provenance but are not plotted as performance results.

See the repository-level [motivation results](../../MOTIVATION_RESULTS.md) and
[system audit](../../KV_EP_SYSTEM_AUDIT.md) for source semantics, mechanism
evidence, limitations, scale design, and testbed mapping. The final compact
FlowSim result is
[`results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md`](results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md).
