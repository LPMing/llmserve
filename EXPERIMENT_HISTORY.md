# Experiment History, Cross-Simulator Reference, and Provenance

This is the compact audit trail for earlier experiments. It replaces the
separate ns-3 summary, cross-simulator comparison, completion audit, negative
results, and run-provenance notes.

## Original HPCC/ns-3 reference

The old repository `/home/dell/lpm/ns3-kv-ep/experiments/pd_kv_ep/` was read
only and was not modified. Its topology used Prefill hosts P0/P1, Decode hosts
D0--D3, a ToR switch, and 100-Gbps host links. KV was an artificial finite
bulk transfer, normally 1 GiB split into 16-MiB chunks. EP was an artificial
decode all-to-all workload with batch/hidden/top-k parameters. The valid
`*_ordered` candidates show roughly 10.1--13.2x EP-tail degradation under
shared RR arbitration and about 1.03--2.06x KV FCT growth; strict EP recovers
most EP tail latency.

Those values are network-only reference points, not targets for the semantic
LLMServingSim study. The old failed-sanity rows remain excluded because flow
rows were not globally ordered or a flow was incomplete.

## Qualitative cross-simulator result

| phenomenon | old HPCC/ns-3 | current LLMServingSim study | interpretation |
|---|---|---|---|
| KV -> EP interference | strong under constructed bottleneck | native small 2.028x matched EP P99; bounded default-packet S64 slices +20.108%/+25.455% | same direction, different workload and scale |
| priority sensitivity | strict EP protects bursty EP | EP_FIRST protects network EP but can slow KV completion | policy tradeoff survives; serving SLO remains to be closed |
| queue mechanism | packet queue/transport detail | native ns-3 shared directed links and Qbb queues | comparable serialization evidence; not every point has ECN/PFC activity |
| serving metrics | absent | integrated FlowSim and bounded native gates emit TTFT/TPOT/TBT fields | only serving runs can support serving conclusions |

## Validity rules

An accepted contention result must have native/model-derived communication,
same request/config content in the controls, matched collective metadata,
positive exact KV/EP overlap on a shared directed link, and complete event
coverage. A network-only replay cannot claim TTFT, TPOT, TBT, SLO, or a
whole-run scheduler gain.

The four-request FlowSim result is the canonical compact policy motivation. The
native Qwen3/ns-3 matched result is the canonical packet-level small mechanism
result. S64 windows are bounded network evidence unless the serving scheduler
also completed and emitted request metrics.

## Negative and incomplete evidence retained conceptually

- Azure conversation has exact overlap but only +1.39% EP P99 in its bounded
  discovery window; overlap alone is not sufficient.
- Full multi-million-request Azure/BurstGPT packet replay is out of scope.
- The complete Mooncake conversation analytical replay and several large native
  gates exceeded practical runtime/artifact budgets; they are not results.
- The large 9,000-byte-packet Mooncake/BurstGPT windows are discovery evidence;
  the two-request 1,000-byte closures are the stronger packet-fidelity result.
- A 20% number is not promoted to a serving optimization claim merely because a
  bounded network CCT crosses that threshold.
- EP64/128-GPU performance is not established.
- No dynamic scheduler has been implemented.

These negative results are retained to prevent selective reporting and to make
the next experiment auditable.

## Current provenance

Primary small native runs:

```text
auto-two_prefill_b1_512_a2-overlap / baseline
auto-two_prefill_b1_2048_a2-overlap / baseline
auto-two_prefill_b2_2048_a2-overlap / baseline
time_varying_native_v2
```

The reproducible command, output roles, and native policy window names remain
encoded in the experiment scripts and result manifests. The cleanup removes
duplicate prose only; it does not remove raw result CSV/JSON, trace data,
figures, or source instrumentation.

## Recommended reading order

1. [`KV_EP_SYSTEM_AUDIT.md`](KV_EP_SYSTEM_AUDIT.md) — semantics and backend.
2. [`TRACE_WORKLOADS.md`](TRACE_WORKLOADS.md) — trace and byte provenance.
3. [`MOTIVATION_RESULTS.md`](MOTIVATION_RESULTS.md) — current evidence.
4. [`LARGE_SCALE_PLAN.md`](LARGE_SCALE_PLAN.md) — scale/SLO/replay policy.
5. [`experiments/pd_kv_ep/results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md`](experiments/pd_kv_ep/results/flowsim_simple_motivation_200g/SIMPLE_MOTIVATION_REPORT.md) — final compact result.
