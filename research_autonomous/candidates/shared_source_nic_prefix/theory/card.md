# Shared-source-NIC prefix placement

**Scenario/data.** The published 8×RTX4090/one-100-Gb/s-node ratio is B;
Llama-3.1-8B TP1 BF16 block times and 268,435,456-B/2048-token KV are A;
the synchronized eight distinct-prefix arrival is C. The KV is one full
TP1 shard/request, 8,388,608 B/layer. Eight requests present
2,147,483,648 B on the single source NIC, a 171.799-ms serialization
floor. Cold/hot per-block compute is 5.995/0.614 ms; the 8P cut service is
5.369 ms/layer. Thus the theoretical overlap ratio crosses 0.896→8.743.
At two hot producers the cut is already exposed; at eight it is saturated.

**Critical path and gate.** Round12/13 FlowSim shows hot all-D-miss P2D-ready
171.876 ms, modeled token 2 at 190.394 ms and completion208.912 ms after
arrival. The last flow is on the ready barrier. A fixed-byte network
scheduler's zero-overhead Oracle can at most reach the 171.799-ms byte
floor: `Gain_upper≈0.045%` on P2D-ready, below10%. The 20.969-ms D-resident
DELTA control is a conditional cache-state contrast, not achieved policy
gain. Strong baselines: cache-aware D choice, DELTA, single-flight,
LFU/PrefixPlace retention, topology-aware P selection. An online cache
placement or replication mechanism remains `NEED_DATA`: the eight
soon-to-repeat prefixes have no distinguishing prior demand signal in the
constructed stream, and the four public Qwen traces do not support the
eight-key short-output burst. A reproducible experiment and its failed
prediction tests are [Round12](../../../ROUND12_PREFIX_INVERSION.md),
[Round13](../../../ROUND13_NATURAL_CACHE_ASYMMETRY.md) and
[Round14](../../../ROUND14_PREFIX_BURST_SCREEN.md).

**Falsifier.** If a matched ordered trace supplies predictable D misses and
cache-aware placement still leaves ≥10% modeled Serving headroom after
LFU/PrefixPlace, reopen. Otherwise `NO_GO` for fixed-byte scheduling.
