# Round 13: natural D eviction and a source-cut lower bound

## Decision

**NATURAL_ASYMMETRY_VALIDATED; NETWORK_SCHEDULING_NO_GO.** A normal
24-GB RTX4090 KV pool with 0.9 utilization can evict a reusable Decode
prefix while the eight Prefill GPUs retain their own prefix. This makes the
Round-12 P-hit/D-miss state causally possible without manually clearing D
cache or choosing a cold D while a warm D is idle. But when all eight
target prefixes are distinct and both D workers miss, the fixed full-KV
source cut is already served within 0.045% of its physical serialization
floor. Reordering transfers cannot deliver a 10% gain. A paper would need
an independently validated way to preserve or preposition D prefixes,
alter bytes, or avoid the source cut; no such online mechanism is established.

## Why the cache asymmetry is natural in this fixture

The [runner](experiments/prefix_inversion/churn.py) uses the same measured
Llama-3.1-8B RTX4090 TP1 profile and the documented 8-GPU/one-100-Gb/s
source-node ratio. Eight P instances share one 100-Gb/s uplink. Four are
paired to D0 and four to D1; the two D GPUs are on separate 100-Gb/s
nodes. Each D has 3,400 KV blocks of 16 tokens under the unchanged normal
`npu_memory_utilization=0.9` setting. There is no artificial capacity cap.

Eight distinct 1,984-token prefixes are first processed and cached, one
per P. Then eight waves of eight **distinct random 2,048-token requests**
arrive at 300-ms intervals. Each P sees eight fillers; each D sees 32.
Even disregarding warm-prefix blocks, 32×128 full prompt blocks exceed the
3,400-block D pool. One P sees approximately 124 warm-prefix blocks plus
8×128 filler blocks, well below 3,400. The target cohort of eight requests
arrives at 2.7 s. The last filler completes by 2.630 s, so target queueing
or concurrent filler traffic cannot explain target latency. The no-churn
control uses identical target arrival, topology and model. A second pair
of same-prefix cases is retained as a diagnostic; the decisive cases give
each P a **different first token** in its reusable prefix, so no two targets
share a full 16-token prefix block.

## Audited results

The [analysis](experiments/prefix_inversion/analyze_churn.py) asserts all
target P hits, both D pre-transfer query states, distinct prefix content,
completion of prior requests, no D sequence-capacity wait, exact P2D bytes,
flow paths across the source NIC, and P2D flow → ready → admission →
token-2 ordering. Its [summary](experiments/prefix_inversion/churn_summary.json)
includes per-request metrics, input/output hashes and current source hashes.

| Condition | P cache hit | Pre-transfer D query | P2D bytes / target | P2D-ready | Modeled token 2 | Completion |
|---|---:|---|---:|---:|---:|---:|
| No churn, 8 distinct prefixes | 1,984 tokens each | 4 HIT on D0, 4 HIT on D1 | 8,388,608 B | 20.969 ms | 39.487 ms | 58.005 ms |
| 8 filler waves, 8 distinct prefixes | 1,984 tokens each | 4 MISS on D0, 4 MISS on D1 | 268,435,456 B | 171.876 ms | 190.394 ms | 208.912 ms |

Times are elapsed from the common 2.7-s target arrival. No target waits for
Decode sequence capacity. All 256 target layer flows traverse the `10→13`
100-Gb/s source uplink. D0 and D1 each receive four target requests. The
target full-KV total is 2,147,483,648 B, so its ideal 100-Gb/s source
serialization takes 171.799 ms. The measured P2D-ready is 171.876 ms,
just 0.077 ms or 0.045% above that byte-only floor. Its last required
flow ends exactly at the request-ready barrier. Destination cache lookup
after transfer also reports zero hit for all eight distinct-prefix targets.
The original same-prefix case had later D hits during the cohort, making
concurrent single-flight transfer a strong baseline for that variant; the
distinct-prefix case removes that confound.

The conditional 150.907-ms difference (87.8% of the miss ready time) is
the cost of losing D residency, not an achieved placement-policy gain.
Each D would need to protect roughly four 1,984-token prefixes, about
1.04 GB of KV, while admitting other prompts. Existing cache planners
could make that choice if future demand is known or predictable. Here the
eight reused prefixes and 64 filler prompts have each appeared only once
before the target. No online signal in the simulated request stream
distinguishes which ones will recur. Treating future target IDs as an
Oracle would violate the research gate.

## Literature and next gate

[SGLang's Decode radix/HiCache delta](https://github.com/sgl-project/sglang/issues/43699)
and an explicitly described
[single-flight P→D prompt admission](https://github.com/sgl-project/sglang/issues/24544)
rule out claiming either primitive as new.
[NetKV](https://arxiv.org/abs/2606.03910) already selects a D using cache,
load and network state. [PrefixPlace](https://arxiv.org/abs/2608.01655)
already optimizes memory-constrained KV prefix placement with
source-dependent transfer costs; [CacheRoute](https://arxiv.org/abs/2608.19677)
plans prefix affinity. Any solution needs to beat a composite of these
ideas, not an LRU-only D-miss case. The current fixture proves a real
conditional bottleneck but cannot distinguish an innovative online
retention rule from known cache-admission policy or an Oracle.

Before building another scheduler, the next discriminating work is a
**demand-predictability/strong-baseline screen**: find model-appropriate
repeated-prefix cohorts with arrival order and enough KV churn to measure
whether a simple LFU/recency/prefix-affinity policy would preserve the D
copy. If such a policy captures the large gap, reject this paper angle.
If it fails for a clearly characterized burst or churn regime, formulate
the incremental source-cut-aware value and compare with PrefixPlace plus
NetKV and shipped delta/single-flight semantics. The archived SwissAI
file need not be mined before this narrower question is posed.
