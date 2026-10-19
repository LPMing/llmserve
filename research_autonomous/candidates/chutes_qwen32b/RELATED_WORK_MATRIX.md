# Closest work for a Qwen3-32B Chutes network hypothesis

Screened 2026-10-14. The candidate is not yet an algorithm: the first gate is
whether real exact-model arrivals can make P2D KV transfer visible after a
layerwise baseline on a declared 200-Gbps RTXPRO6000 topology. Chutes does not
release its physical P/D topology or actual GPU type per instance.

| Work | Existing mechanism and metric | Baseline that a new paper must keep | Remaining possible difference |
|---|---|---|---|
| [Chutes workload study](https://arxiv.org/html/2608.13573v1) | Reconstructs sessions and studies cache-first versus load-first routing; shows locality/load tradeoff from this same production trace | Cache-first, load-first and LRU with the paper's session assumptions | Physical P2D network effects are not modeled, but a new result requires measured network-critical Serving latency. |
| [NetKV](https://arxiv.org/html/2606.03910v1) | Scores each Decode by cache, queue, static topology, dynamic residual bandwidth and in-flight self-contention; measures TTFT/SLO | NetKV-like per-request network-aware Decode choice, plus tuned cache+load scorer | A simple network-aware receiver rule is covered. A distinct group or layer-wave scheduling decision needs incremental gain. |
| [HMA-Serve](https://arxiv.org/html/2606.29986) | Pipelines each layer's KV egress with later Prefill compute, including a Qwen3-32B 8K example; reports TTFT/TPOT | Layerwise overlap, not post-prefill bulk transfer | Different coflow arbitration could matter only if real simultaneous sources defeat overlap. |
| [SmartGen](https://arxiv.org/html/2607.28150) | Selectively sends essential KV, fetches remaining blocks on demand and speculatively; targets limited-bandwidth cloud links and TTST | Selective transfer and full-transfer controls when the mechanism changes bytes | Byte reduction alone or a slow-link example is covered. |
| [Kairos prefill deflection](https://arxiv.org/html/2607.02043) | Sends some Prefills to Decode GPUs, avoiding P2D transfer subject to TBT SLO | SLO-safe local-Prefill deflection under queue pressure | Eliminating transfer by moving Prefill is covered; a new network policy must beat this where applicable. |

The local Qwen3-32B TP2 profile gives 2.876 ms of block compute for a 2048-token
first chunk versus 0.336 ms of aggregate per-layer KV on one 200-Gbps cut.
This makes nine synchronized Prefill sources a **necessary pressure screen** for
that idealized one-cut wave. It does not assert nine sources share a real cut
or that a source can emit one wave each block interval under batching. The
benchmark example validates the colocation simulator within roughly 1% on
its own saturated RTXPRO6000 workload; it does not validate P/D transport on
Chutes hardware.

If the Prefill side reuses a cached prefix but the Decode side is cold, a
simple linear fresh-token approximation makes the full-KV wire time match
compute only above 88.3% Prefill cache hit. This conditional threshold also
assumes full-prefix retransmission. Actual Decode cache affinity, attention on
the long cached context and another target's spare capacity can erase the
exposure. Chutes reports cached-token *counts* but no reusable prefix IDs or
P/D roles, so it cannot establish a cold Decode from a high `ct` value alone.
