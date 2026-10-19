# Network capacity lower bound

## Fixed facts

The required calculation uses the four full-transfer requests, TP2, and one 200-Gbps receiver rail per TP rank. The workload, bytes, request times, or link rate are not altered.

Per request and TP rank, KV is `201,768,960 B`. Thus, per receiver rail:

```text
W_rail = 4 × 201,768,960 = 807,075,840 bytes
C      = 200 Gbit/s = 25,000,000,000 bytes/s
T_min  = W_rail / C = 0.0322830336 s = 32.2830336 ms
```

The first P2D KV release is at `150.125 ms`; sampler readiness is `177.175 ms`. The available service window before sampler is `27.050 ms`, so even a continuously work-conserving rail can serve at most:

```text
25,000,000,000 × 0.027050 = 676,250,000 bytes
807,075,840 - 676,250,000 = 130,825,840 bytes still outstanding
```

Therefore all four requests' complete KV cannot be ready by sampler time. The optimistic all-KV-ready lower bound is:

```text
150.125 ms + 32.2830336 ms = 182.4080336 ms
```

The integrated FlowSim last required KV completion is `182.646480 ms`, only `0.2384464 ms` above that one-cut serialization lower bound. This difference is an upper bound on what any same-byte network-only flow ordering could recover at the full-request barrier in this fixture; it is not a promise that an ordering can attain it.

## Barrier consequences

The profile-derived next-token Decode graph takes 14.395 ms. Under a full-KV barrier:

```text
observed A0 token2 = 182.646480 + 14.395 = 197.041480 ms
optimistic full-KV token2 = 182.4080336 + 14.395 = 196.8030336 ms
maximum network-only gain = 0.2384464 ms
```

Relative to A0's sampler-anchored 19.866480-ms first interval, that is at most 1.2002%. Relative to a 14.395-ms compute interval, it is 1.6565%. It is below the mission's 15% gate by a wide margin. This rules out a large same-byte gain from reordering flows while retaining the request-level all-KV barrier for this fixture.

## Assumptions and limitation

This is a necessary lower bound for one rail that must carry the stated work at 200 Gbps. It ignores propagation, packet/protocol overhead, competing unmodeled traffic, and any access-link constraints, making it optimistic. It does not incorrectly put the full two-rank request volume on one rank's rail: each rail carries four 201,768,960-byte rank shards.

The separate per-layer oracle changes *when the consumer is allowed to proceed*, not the physical capacity. That is analyzed in `03_LAYER_CONSUMPTION_DAG.md`; it is not a better network-only schedule.

