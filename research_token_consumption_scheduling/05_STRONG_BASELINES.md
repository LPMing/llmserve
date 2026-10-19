# Strong baseline comparison

## B0: Existing full-P2D request barrier

Integrated A0 FAIR is the baseline with full model-derived P2D bytes. Its sampler-ready event is `177.175 ms`, full P2D is ready at `182.646480 ms`, and token2 is completed at `197.041480 ms`. The sampler-anchored token2 proxy interval is `19.866480 ms`; the simulator's own recorded first-token-to-token2 interval is `14.395 ms`, because the simulator delays its first-token record until P2D graph completion.

## B1: Strong network-only upper bound

Giving a flow scheduler ideal access to the same physical capacity cannot finish all required rank-shard bytes before `182.408034 ms`, the optimistic single-cut work lower bound. Keeping the full request barrier, even an ideal ordering can therefore save at most `0.238446 ms` from A0's token2 time. This is a physical capacity upper bound, not an implemented policy result.

## A2: Existing integrated DELTA/prefix-suppression baseline

A2 reserves matching destination prefix blocks and transfers only the nine-token suffix: 884,736 B/request instead of 403,537,920 B/request. Its P2D finishes at `176.419675 ms`, before sampler readiness; token2 and token3 occur at `191.570 ms` and `205.965 ms`. Thus its sampler-anchored token intervals are already at the 14.395-ms compute floor in this fixture.

A2 changes total network bytes, so it is not a same-byte flow-scheduling control. It is still the strongest existing *serving* baseline for the candidate's claimed objective. The B2 oracle matches A2's token2/token3 timing while transmitting roughly 456 times as many KV bytes. There is no incremental serving latency gain over A2 to motivate a new network–Serving scheduler here.

## B2: Layerwise consumption oracle

B2 keeps all A0 bytes and uses layer readiness to begin Decode-layer compute before the full transfer completes. It reaches `191.570 ms` token2, a `5.471480 ms` sampler-anchored improvement over A0 and the same token timing as A2. B2 is only an independent, profile-derived oracle and has no measured integration/commit overhead. The enabling control—start Decode work once that layer's KV is available—is the core layer-streaming/async execution mechanism, not a new network priority policy.

Against the mission's conditional 15% sampler-proxy target of `16.886508 ms`, ideal B2's `14.395 ms` clears the numeric threshold versus A0. It yields **0 ms incremental token2 gain over A2**, and the actual client ITL remains unobserved.

## Baseline decision

1. Full barrier + network-only scheduling has negligible theoretical residual headroom in this exact case.
2. Layerwise consumption can expose a large *architectural* overlap opportunity, but it is not a new network scheduler and existing DELTA already reaches the same measured decode floor with fewer bytes.
3. A2's byte reduction and B2's layer-gated compute are different mechanisms and must not be combined into a false same-byte comparison.
4. No fairness, SLO, throughput, or P99 claims are supported by four controlled sessions.

