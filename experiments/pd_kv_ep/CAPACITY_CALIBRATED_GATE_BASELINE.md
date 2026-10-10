# Frozen baseline for the capacity-calibrated Decode-concurrency gate

Status: frozen; no old operating point was rerun for this phase.

The prior `MINIMAL_IDEAL_KV_EP_FINAL_FAIL` remains authoritative for its tested
population envelope. The exact previous conclusion is:

> Previous conclusion remains valid for its tested D/K envelope.

The archived gate used the same 1P2D / EP16 / single-ToR topology, Qwen3-30B-
A3B-Instruct-2507, BF16 model-derived KV, GateRouter-derived A2A_P2P, ACTUAL
P2D receivers, `LAYERWISE`, and FAIR. Its population points were D2K1,
D4K1, D8K1, D8K2, D8K4, D16K4, and D16K8. They are not repeated here.

At the strongest old point, D16K8, the reported matched network results were:

| Metric | Isolated | FULL/FAIR | Change |
|---|---:|---:|---:|
| EP CCT P99 | 25.644 us | 26.954 us | +5.11% |
| KV residual-drain P99 | 681.289 us | 706.196 us | +3.66% |
| KV-ready time | 368.624 ms | 368.624 ms | unchanged |
| Decode TBT P99 | 6.214912 ms | 6.244387 ms | +0.47% |

The old gate observed simultaneous P2D/EP activity on a directed 200-Gbps
ToR ingress. Fluid residual-positive episodes were transient relative to the
roughly 6.24-ms Decode collective recurrence. This was an integrated FlowSim
result, not packet-level ns-3 evidence; its `queue_bytes` was not a switch
queue. Full provenance and limitations remain in
[`MINIMAL_IDEAL_KV_EP_FINAL_FAIL.md`](MINIMAL_IDEAL_KV_EP_FINAL_FAIL.md),
[`MINIMAL_IDEAL_KV_EP_RESEARCH.md`](MINIMAL_IDEAL_KV_EP_RESEARCH.md), and
[`results/minimal_ideal_kv_ep/MINIMAL_IDEAL_KV_EP_EXPERIMENTS.csv`](results/minimal_ideal_kv_ep/MINIMAL_IDEAL_KV_EP_EXPERIMENTS.csv).

This new phase asks a different bounded question: whether the old experiment
stopped below the configured active-Decode capacity. It does not invalidate
or rewrite the old result. Only new D>=32, K=1/2 runs belong in the separate
`results/capacity_calibrated_kv_ep/` tree.
