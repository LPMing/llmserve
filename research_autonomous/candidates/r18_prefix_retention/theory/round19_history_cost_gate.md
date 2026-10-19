# Round 19 A gate: online history and heterogeneous retransmission sizes

This is a controlled **strong-baseline falsifier**, not a proposed new
policy. It uses the frozen Round-18 2P1D Llama-3.1-8B RTX4090 topology,
normal3,400-block D pool, distinct target prefixes and100-Gb/s shared
source cut. The online signal is a second *completed* ordinary request
for each warm1,984-token prefix before filler churn. No future target
identity is revealed to the cache. Fillers alternate2,048 and3,072
tokens, so their full-KV retransmission costs differ by50% while all
token IDs are exact and distinct. They each appear once.

Two warm prefixes occupy248 completed prompt blocks. Fourteen2,048-
token fillers occupy1,792 blocks and fourteen3,072-token fillers
occupy2,688 blocks, totaling4,728>3,400 in D. P0 sees only the
2,048-token fillers: `124+14×128=1,916` blocks. P1 sees only the
3,072-token fillers: `124+14×192=2,812` blocks. Both P pools retain
their warm prefixes under ordinary capacity. D LRU evicts older warm
blocks. Block LFU sees each warm block touched twice and filler blocks
once, so it should keep both warm prefixes without pinning or changing
capacity. The target pair arrives at5.5 s with64-token suffixes and
3 output tokens, after all historical and filler work must have ended.

Each target's full P2D transfer is268,435,456 B and its DELTA transfer
is8,388,608 B. The pair's source-cut floors are42.950 and1.342 ms.
This is only a conditional cache-state difference; if LFU retains both
prefixes, the ideal D-hit Oracle has **zero additional target-byte
headroom** over a simple online baseline. A cost-aware policy using
observed access count and KV bytes per retained block also ranks warm
blocks above one-use fillers here. With one D, cache-aware Decode
routing has no alternative endpoint. Different target prefixes remove
same-prefix single-flight as a remedy; DELTA is enabled in both arms.

Falsifiers: if LRU retains the two warm D prefixes, if LFU evicts them,
if P misses, if earlier work overlaps target arrival, if any transfer
byte count deviates from model math, or if the last flow is not in the
ready→admit→token2→completion chain, diagnose before interpreting
latency. Stronger PrefixPlace-like cost placement explicitly uses
profiled demand and heterogeneous compute/transfer costs
([paper](https://arxiv.org/abs/2608.01655)); NetKV-like routing uses
network/cache/load state ([paper](https://arxiv.org/abs/2606.03910)).
This single-D fixture cannot establish a failure of either published
mechanism. A broader A paper case would need source-backed co-arrival
and an incremental same-resource gap over those comparators.
