# Natural Workload Support

Status: `SYNTHETIC_ONLY_RESULT` for the new destination-prefix protocol and static P:D comparison.

This mission intentionally uses a four-session controlled fixture with identical 4096-token prefix sequences, explicit session dependencies, warm-up requests, and small output lengths. The fixture proves cache-index/reservation semantics and exposes a specific path-length opportunity. It does not establish how often production Mooncake, Azure, or BurstGPT requests have the same destination prefix, how often it remains resident at the Decode worker, or whether an online runtime can reserve it cheaply enough.

No real trace was replayed in this phase. No trace without token IDs/block hashes is interpreted as a cache hit. The cross-session 4080-token cache hit observed in 3P2D is a fixture consequence, not a natural workload frequency estimate.

Because neither the corrected TTFT threshold nor the full-session 15% threshold passed, trace-scale validation is not justified by the current evidence. Natural workload prevalence remains unknown rather than assumed positive or negative.
