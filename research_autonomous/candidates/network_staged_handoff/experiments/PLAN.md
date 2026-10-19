# Minimal causal repair and experiment plan

1. Keep the 1P1D/4P1D 2048/3 cold run as a no-backpressure control:
   measured P2D-ready must remain 184.907 ms with exact KV bytes.
2. Before memory-full replay, implement receiver capacity reservation before
   source retirement, source KV retention until acceptance, explicit blocked
   handoff state, wakeup on D block release, cancellation/retry and no double
   transfer. Test `max_num_seqs` wait independently from KV-memory wait.
3. Use 2P:1D and 2P:2D with 2048/600 requests and a finite, source-backed
   arrival burst. Keep 200-Gb/s rails, measured profile and same GPU count
   for each policy comparison. Record P occupancy, D occupancy, stall,
   per-flow path/bytes, P2D-ready, Decode admission, token 2 and completion.
4. Compare capacity-aware FIFO, output-aware SRPT/EDF (when lengths are
   legitimately known), DMRS-style memory admission, NetKV-like D choice,
   and a zero-network Oracle. A tuned 1P2D ratio is a separate provisioning
   control, not a fixed-resource policy gain. Stop if the incremental bound
   is below 10% or if the only positive case is sustained overload.
