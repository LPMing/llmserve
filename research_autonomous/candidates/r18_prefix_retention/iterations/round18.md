# Round 18: controlled residency inversion and online decision screen

The negative 24-filler run retained both 1,984-token D prefixes. The
28-filler run crossed the normal 3,400-block pool and evicted both; each
target then sent 268,435,456 B despite its P-side prefix hit. Two ordinary
refresh requests before target arrival restored D residency and the
8,388,608-B delta handoff. All three runs passed flow, path, block,
event-order and completion checks. The frozen measured result is in
`../../../MOTIVATION_REPORT.md`.

The separate `theory/online_baseline_screen.py` replays completed prompt
blocks in the same 3,400-block pool. It is an **analytic cache decision
screen**, not a Serving timing measurement. With one prior access for
each of the two warm keys and each filler, online LRU, LFU and simple
cost-weighted LFU all miss both targets. A future-knowing Oracle retains
both. When a second historical warm access is added before fillers,
plain LFU and cost-weighted LFU retain both, while LRU misses. In this
equal-B/token model the cost weight cannot distinguish keys except by
frequency. The fixture therefore demonstrates a real phenomenon but
does not establish a lawful online signal or an incremental win over
simple LFU. `PAPER_HEADROOM_VALIDATED` remains false.

Next discriminator: a time-ordered workload with repeated prefix keys
and varied marginal retransmission costs, where LFU plus a simple
cost-aware tie-break and cache-aware Decode routing make a different
decision from a legal joint policy. Freeze the request stream and
resource budget before policy comparisons. If a simple composition
matches the legal Oracle, mark this optimization line `NO_GO` while
retaining the motivation result.
