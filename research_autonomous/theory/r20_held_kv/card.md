# Round 20: source-held KV and receiver capacity on an exact-model trace

## Claim being screened

An online admission policy could improve modeled request completion only
if Prefill-complete requests retain enough source KV to stop useful P
work, D credit is unavailable, and the newly chosen transfer/Decode
order is still critical after two-stage FIFO, network FIFO/SRPT, prefix
DELTA/LFU and cache-aware routing. This is a conjunction. A D-full event
alone, or an early-credit versus late-credit gap, does not establish it.

## Inputs and threshold

Use the local Qwen3-32B BF16 RTXPRO6000 TP2 profile and model config
(A), the pinned SwissAI exact-model arrival/length/bucket trace (A), a
declared 200-Gb/s per-rank cut (C) and an explicitly hypothetical
4P1D role placement (C). No SwissAI production P/D topology or D cache
residence is claimed. [`derive.py`](derive.py) computes the exact
per-rank KV pool at 0.9 utilization: 28,614 sixteen-token blocks,
457,824 tokens, after 30.513 GiB/rank model weights. KV is 262,144 B
per prompt token across both TP ranks, 131,072 B/rank. The raw KV bytes
are `S=Ntok*L*2*Hkv*Dh*b`; the per-rail floor is
`Tcut>=S/(TP*Beff)`. At 16,384 tokens one held request requires 1,025
blocks including the first Decode slot, and **27** such simultaneous
requests fit while the 28th exceeds one P pool. The 200-Gb/s
per-rank serialization floor is85.899 ms. At 2,048 tokens, the
measured Prefill compute is184.647 ms (excluding TP collectives),
versus10.737-ms one-source full-KV cut service; layerwise transport is
normally hidden. These are necessary screens, not an end-to-end gain.

The exact SwissAI `bucket_ids` support prior-completed prefix matching,
but they do not reveal P/D roles, physical NICs or realized D residency.
An ordered short window must pass all of: (1) held P blocks near28,614
while useful later P arrivals wait, (2) D credit waits, (3) transfer
bytes and rails are critical to P2D-ready and later Decode completion,
and (4) a same-resource legal Oracle beats the strongest simple
combination by at least10–15%. The next data-mining step uses real
timestamps and lengths without altering arrivals. If the necessary
threshold fails, stop before a TP2 simulator extension.

## Strong baselines, Oracle and novelty

Early layerwise credit and correct two-stage FIFO are both required.
[P/D-Serve](https://arxiv.org/abs/2408.08147) already retains a
Prefill prompt while transfer waits. [DMRS](https://arxiv.org/abs/2610.15579)
formalizes coupled P/D memory scheduling. [Nuska/MFS](https://arxiv.org/abs/2603.17456)
prioritizes dependent network stages for TTFT SLOs.
[NetKV](https://arxiv.org/abs/2606.03910) uses topology, congestion,
cache and load in D choice. [PrefixPlace](https://arxiv.org/abs/2608.01655)
uses profiled demand and heterogeneous prefix recompute/transfer costs.
The implementable comparator is their simple online composition where
the required state exists, plus FIFO/SRPT/EDF network order, DELTA and
single-flight. A future-known request order may serve only as a labeled
small Oracle; it is not an online gain. The proposed *possible*
difference is a joint source-hold/D-credit/network critical-path
decision after these comparators, not source retention itself.

No `Gain_upper=(Mstrong-Moracle)/Mstrong` value or algorithm gain is
currently asserted. The 4P1D placement is an assumption and the TP2
two-stage path is not yet supported; both are explicit falsifiers. This
candidate is `THEORY_SCREENED / NEED_DATA` until the raw trace passes
the necessary co-occurrence gate.
