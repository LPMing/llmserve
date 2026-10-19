# Round 19: a legal history signal makes plain LFU sufficient

The frozen Round-18 D-hit/D-miss motivation remains unchanged. This
round tests **policy headroom**, not that state gap. Before targets,
two distinct 1,984-token warm prefixes each receive two completed normal
requests. Twenty-eight unique fillers alternate 2,048 and 3,072 tokens.
Their 4,480 blocks plus 248 warm blocks exceed the normal 3,400-block D
pool; P0 and P1 individually use at most 1,916 and 2,812 blocks. Two
different target keys arrive at 5.5 s after earlier work ends. The
source cut, D pool, DELTA and all workload rows are identical for LRU
and LFU. The source-backed frequency signal is visible before eviction.

The preregistered prediction was LRU full misses, LFU warm-prefix hits.
Both 34-request runs passed exact per-request byte/path/rail/credit and
event audits. LRU target D hits are 0/0, transfers 268,435,456 B each,
and modeled completion elapsed is 79.028875 ms each. LFU target hits
are 1,968/1,968 tokens, transfers 10,485,760 B each, and completion
elapsed is 56.971 ms each. LFU preserves 123 of 124 completed warm
blocks per key: the last block does not receive the second counted block
access in this simulator's exact warm-request path. Thus the theory's
literal 1,984-hit prediction was too strong. The remaining 2,097,152 B
per target versus ideal 1,984-hit DELTA finishes by 19.350 ms, before
Prefill ends at 20.969 ms; the ideal D-hit branch has no further modeled
target-completion gain. This is a **22.058-ms simple LFU gain over LRU**,
not a proposed new mechanism gain.

Cost-aware retention has no independent discriminator in this fixture:
historical frequency already separates both warm keys from all fillers,
so even a perfect marginal-byte decision cannot improve target completion
over LFU. One D removes a routing choice; distinct targets remove
same-key single-flight. DELTA is on in both arms. A PrefixPlace-like
demand/cost policy and NetKV-like cache-aware routing are relevant
published stronger comparators; this single-D fixture cannot show their
failure. The one-access frozen case's future-knowing Oracle was never an
implementable online policy.

Decision: `NO_GO` for extra A paper headroom in these ordered fixtures.
The D-state motivation remains `MOTIVATION_VALIDATED`. A future A case
needs source-backed online history **and** a residual same-resource gap
after LFU, cost-aware placement, cache-aware routing, DELTA and
single-flight; no such gain is claimed here.
