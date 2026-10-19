# 05 — Priority and oracle results

**Status: `NOT_RUN_BY_GATE`.** No FAIR/KV_FIRST/EP_FIRST cross-class sweep, EDF/SRPT/LLF, coflow/Nuska baseline, or offline priority oracle was run in this recovery phase.

Reason: the prerequisite serving-visible motivation gate has not passed. The controlled KV–KV point moves shard FCT but not last-shard completion or TTFT; the corrected KV–EP point has <1.1% EP CCT P99 change and no measurable TTFT/TBT cost; and the newly representable independent-group EP–EP case changes CCT by at most 6.39% while TPOT/TBT changes by less than 1%. Running a priority/oracle matrix now would optimize a metric whose end-to-end relevance has not been established.

The EP–EP capability run and matched A-only controls are documented in
[`12_EP_EP_GROUP_VALIDATION.md`](12_EP_EP_GROUP_VALIDATION.md). Its small
serving delta does not establish an oracle upper bound; this remains
`NOT_RUN_BY_GATE`, not a zero-gain oracle result.

No oracle bound is reported. A legal oracle would have to respect per-flow releases, full directed paths, endpoint/NIC caps, layer dependencies, request handoff barriers, collective peer sets, and compute overlap. A clairvoyant scheduler over an invented per-request split of the current aggregate EP messages would be invalid.
