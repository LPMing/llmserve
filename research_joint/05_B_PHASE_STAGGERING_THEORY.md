# Direction B — Decode EP phase staggering

## Question and legal control

Can a serving-side, one-time first-admission phase offset between two **independent** Decode EP groups reduce recurring collective contention on a fixed shared cut, enough to improve total token/request latency? The control changes only when group `ep_b` is first eligible for its first Decode batch. It does not desynchronize ranks inside a group, change request arrival, alter P2D ready times, modify bytes/routing, or impose a delay every token.

## Topology and traffic semantics

Qwen3-30B-A3B, 48 layers, two independent EP4 groups; each EP4 is two TP2 members on D0/D1. Both groups use the same directed D0–ToR–D1 cut. Each request is input128/output32, and four requests belong to each group. All requests arrive at zero for controlled characterization. P2D is LAYERWISE. Network is integrated FlowSim, FAIR, 200-Gbps physical directed links. The current collective implementation is BALANCED-routing ALLGATHER dispatch plus REDUCESCATTER combine; this is not exact sparse GateRouter A2A.

## Pre-run estimate and exact controlled comparison

Prior isolated-vs-full EP4 observations give dispatch CCT `10.897→11.593 µs` (+0.696 µs) and combine `10.528→10.856 µs` (+0.328 µs) for four requests/group. When every layer repeats the same pattern, the nominal added EP service per Decode iteration is:

`48 × (0.696 + 0.328) µs = 49.152 µs`

Against the measured isolated 6.1084-ms token interval this is ~0.80%. This is an upper interpretation for a fully repeated per-layer delta, not a general estimate for other groups or routing.

The tested one-time phase shift is 20 µs. It is larger than the measured isolated dispatch/combination service windows and is evaluated against actual integrated events; no assumption is made that a visually selected 20-µs value automatically separates later layers.

The old EP64 equal-work bound (all 96 phases per token, same shape, one cut, exclusive removal) is 519.045 µs/token, ~3.07% of a 16.899-ms profile iteration. It is an idealized ceiling and should not be presented as attainable or as evidence for EP64 in the new run.

## Predicted causal chain

`initial group offset` → `collective interval de-overlap on common directed links` → `each collective returns to isolated CCT` → `48-layer dispatch/combine work per Decode iteration shrinks` → `TBT/ITL and makespan improve`, less the one-time phase hold. `TTFT` should not move if Prefill already created the first token; the first Decode delay is exposed in second-token time.

The phase offset must persist across the recurring per-token groups. If later barriers re-converge, or if one group is simply delayed by as much as the other gains, aggregate objective has no improvement. The measured run confirms de-overlap for this fixture but only a small aggregate gain.

## Stop interpretation

The experiment validates a bounded mechanism, not a new contribution. Generic collective orchestration/staggering already exists in Symphony and Harmonics. This fixture has no natural asynchronous arrival evidence, no sparse A2A peer matrix, no external SLO, no repeat-seed uncertainty, and <1% serving headroom. No EP64 scale-up or offset sweep is justified.
