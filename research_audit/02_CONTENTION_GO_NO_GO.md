# 02 — Contention motivation gate

## Decision: `NO_GO_FOR_FINE_GRAINED_SCHEDULING_MOTIVATION`

The tested FlowSim path can produce real model-derived cross-request overlap on directed links, so the basic shared-resource mechanism is representable. The current data do not establish a material serving-level scheduling opportunity:

- KV–KV shard FCT changes, including +25.35% P99 for a short request under a much longer co-request, but request-level last-shard completion, KV-ready and TTFT remain unchanged.
- KV–EP has actual same-directed-link temporal overlap in the post-fix integrated case, but EP CCT P99 rises only +1.08%; TTFT/KV-ready are unchanged and TPOT delta is <0.01%.
- EP–EP is now representable for the tested rectangular group-major layout. Two independent EP4 groups share directed 200-Gbps links and produce repeatable in-run CCT changes (+6.39% dispatch, +1.58–3.11% combine), but only +0.75–0.80% TPOT/TBT and no TTFT change. This is a capability/mechanism PASS but not useful serving headroom at the tested points.
- ns-3 shows about 7% CCT change only in fixed-time packet replay; there is no serving scheduler feedback, so this is not an endpoint-performance result.

## Three-phenomenon distinction

1. **Network interaction:** observed in FlowSim and native ns-3 packet replay. EP–EP now also has a bounded integrated topology demonstration.
2. **Serving-barrier impact:** not materially established. KV–KV leaves handoff/TTFT unchanged; KV–EP has <0.01% TPOT change; EP–EP changes TPOT/TBT by under 1% and leaves TTFT unchanged.
3. **Optimization opportunity:** not tested and not justified by the current serving-level headroom. No oracle or algorithm comparison is reported.

## Scope of conclusion

This is not a claim that all production deployments are free of such contention. It means that in the tested Qwen3-30B-A3B profile-backed controlled operating points, selected with 200-Gbps links and valid cross-request group/path overlap, the network interaction is weakly exposed to serving barriers. The two-group EP4 case closes the previously open representability check but does not reveal a material scheduling opportunity. Continuing to increase load without a new, grounded mechanism would violate the project's stop discipline.

## Gate transition

Baseline remains `PARTIALLY_VALIDATED`, not full PASS. The bounded evidence is exploratory characterization. The topology capability check passed for one rectangular group-major layout, but the serving motivation gate did not. Close this fine-grained request/collective scheduling paper line for the tested envelope: do not proceed to Case D, priority/oracle baselines, a scheduler, larger traces, or packet-level EP–EP replay. Reopen only if a separately justified real deployment configuration changes the theoretical exposed-barrier upper bound—not merely to search for a larger slowdown.
