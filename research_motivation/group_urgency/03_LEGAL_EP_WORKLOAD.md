# Legal EP workload selection

**No new workload was generated or run.** H1 did not pass G1: heterogeneous-group profile/timeline screening yielded at most 0.3161% optimistic per-token serialization headroom, while the larger 3.1–3.5% ideal value requires equal, synchronized groups with no urgency difference. This file records what would have been a legal bounded candidate and why it was rejected before simulation.

## Conditional candidate screened

The highest asymmetric bound in `02_EP_HETEROGENEOUS_GROUP_SCREEN.csv` is:

- Group A: 64 active Decode requests, context 2,048; 32 requests on each TP2 DP member.
- Group B: 8 active Decode requests, context 2,048; 4 requests on each TP2 DP member.
- Both: Qwen3-30B-A3B-Instruct-2507, EP4 total / local EP2 per member, TP2, two independent `dp_group`s, 48 layers, model/profile-derived ALLGATHER + REDUCESCATTER messages, two Decode servers, 200-Gbps shared directed cut.
- Profile envelope: max-num-seqs=256, max-num-batched-tokens=2,048, context grid includes 2,048. Each member's active decode-token count (32 or 4) is within the token budget.
- Memory preflight using current `MemoryModel`, TP2, EP4, 96-GiB RTX PRO 6000, BF16, 90% utilization: estimated per-GPU model weight 14.95 GiB and KV capacity 71.45 GiB. Group64/context8192 is 12 GiB KV/GPU at 32 sequences/GPU, so the screened maximum context also fits the simulator's upper-bound KV pool. This is a sizing check, not an initialized serving run; actual runtime peak allocations were not measured.

The modeled no-contention token intervals are 16.899 ms (A) and 6.282 ms (B). A common absolute SLO above 16.899 ms gives A no more than its distance to that threshold in slack; an arbitrary threshold selected within the 53.412-µs optimistic headroom could flip a single SLO outcome. No external TBT service contract justifies such a knife-edge threshold. The alternative context-only 256-vs-512 candidate has only 27.197 µs upper work and less than 0.19% relative headroom.

## Why no simulation recipe is emitted

No arrival/output workload, candidate SLO, FAIR/EP_FIRST/oracle run matrix, or new config was written. Creating them after inspecting a sub-1% theoretical bound would turn a deadline into a result-selection tool. The retained 4/8-request fixtures remain the only integrated EP–EP experiments. If this branch is reopened with an externally sourced absolute TBT SLO, first revisit the SLO gate; do not silently reuse a threshold tuned to this bound.

Status: `NOT_RUN_G1_FAIL`; no new network-only or serving result exists for the candidate above.
