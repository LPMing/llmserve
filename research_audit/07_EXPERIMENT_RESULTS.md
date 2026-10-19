# 07 — Consolidated bounded experiment results

See [`02_MOTIVATION_RESULTS.csv`](02_MOTIVATION_RESULTS.csv) for machine-readable metrics and [`01_REPRODUCIBILITY.md`](01_REPRODUCIBILITY.md) for earlier exact setup/commands. Main observations:

1. Model-derived KV traffic has 96 layer×TP shards under Qwen3 L48/TP2. Competing KV flows change shard FCT, including a +25.35% P99 change for a 128-token request paired with a long request, but its last-shard completion and TTFT are unchanged in the tested cases.
2. D4 Decode EP and a late P2D request can overlap on directed links. With the post-fix scheduler, FAIR vs KV-isolated changes EP CCT P99 from 16.099 to 16.273 µs (+1.08%); request TTFT/KV-ready are identical and Decode TPOT differs by <0.01%.
3. A complete packet-level ns-3 dispatch+combine replay shows about 7.1–7.2% network-only EP CCT inflation and +0.16% P2D message mean FCT; no packet completion is fed back to serving.
4. A Decode future-arrival wakeup bug caused a false long TBT in earlier data and has been fixed. Pre-fix TBT figures are withdrawn.
5. The grouped topology extension now supports the tested two-independent-EP4-group shape. Matched A-only controls show cross-group dispatch CCT +6.39%, combine +1.58–3.11%, TTFT unchanged, and TPOT/TBT +0.75–0.80%. This is a bounded EP–EP capability PASS but a serving-motivation NO-GO.

In the EP–EP case, the 0.860/1.024-µs dispatch+combine increase per layer,
multiplied across 48 layers, equals the measured 41.280/49.152-µs increase in
per-token TBT. The network delay is therefore attributable to the Decode
barrier; its fraction of total token latency is simply small.

No TTFT/TBT SLO attainment, no multi-seed estimate, no practical priority implementation, and no large real-trace experiment are claimed. EP–EP collectives are deterministic: within each tested phase all 1,488 round CCTs are identical, so their P99 equals the mean but is not a stochastic tail estimate. Small request counts likewise do not support population percentiles. The EP–EP topology, exact controls, and run recipe are in [`12_EP_EP_GROUP_VALIDATION.md`](12_EP_EP_GROUP_VALIDATION.md).
