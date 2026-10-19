# Theory-gated experiment

No integrated reshape run is justified for 2048/600 Qwen3-32B: the
optimistic two-TP1 Decode ceiling is only51.6% of the same-resource TP2
profiled rate and doubles one-source-rail KV serialization. A future
reopen would use two to eight P/D instances, a fixed physical GPU/NIC
budget, measured TP1/TP2/NVLink profiles, an ordered model-matched trace,
best static TP/P:D/topology baseline and explicit TP shard-to-rail ledger.
