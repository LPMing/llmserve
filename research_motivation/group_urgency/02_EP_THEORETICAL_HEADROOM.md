# H1 theoretical headroom: two independent Decode EP groups

## Decision

**G1 = FAIL for a material group-urgency motivation in the screened envelope.** The profile shows a nonzero ideal class-contention bound when two same-shaped groups are perfectly phase-aligned, but those groups have the same urgency. Once the group sizes or contexts differ enough to create distinct token intervals, the largest profile-release/cut-service screen is only 53.412 µs, 0.3161% of the slower target group's profile-derived token interval. This is an optimistic serialization-removal estimate, not a measured schedule or a strict global oracle. The homogeneous upper bound is at most 3.46% in the screened table and cannot establish that one group should be favored over the other.

Consequently the task's G2 frozen network oracle and G3 integrated experiment were not run. A contrived absolute deadline placed within tens of microseconds of an unvalidated predicted baseline could manufacture a single miss, but there is no external TBT SLO supporting such a threshold. That is not sufficient to pass the urgency gate.

## Work model and accounting

The profile-backed trace generator was called for Qwen3-30B-A3B-Instruct-2507 (48 layers, hidden size 2,048, 128 experts, top-k 8), BF16 weights/KV, TP2 per Decode member, local EP2 in each of two Decode members, EP4 per independent group. The implementation emits ALLGATHER dispatch and REDUCESCATTER combine, not sparse GateRouter A2A. Active Decode requests/group were 2, 4, 8, 16, 32, or 64; each member has half that active count. Context points were 256, 2,048 and 8,192 tokens, all within the RTX PRO 6000 attention profile's max sequence/context grid and max-num-seqs=256 / max-num-batched-tokens=2,048 envelope.

The effective bytes are **on one directed 200-Gbps cut**, not total all-peer payload and not a per-message `comm_size`:

- Dispatch: `per-participant AG bytes × 4 cross-server peer pairs per direction`.
- Combine: generated RS payload aggregated on one directed cut, verified against retained EP4 peer-flow paths.
- Opposite directions are independent full-duplex directed resources; bytes are not added across both directions to claim one link's capacity.
- Wire lower bound for a cut-work amount `b`: `b × 8 / 200e9` seconds.

The profile-compute lower bound replaces the two local expert-rank compute rows per layer by their concurrent maximum and sums the rest of the profile rows. An isolated-collective token-interval estimate adds the 96 isolated EP CCTs. The isolated EP CCT model is `10.2 µs + effective cut bytes / 200 Gbps`: the approximately 10.2-µs startup/path component is empirically calibrated from the retained EP4 controls (dispatch: 10.897−0.69632=10.20068 µs; combine: 10.528−0.32768=10.20032 µs). Extending this intercept to larger batches is an assumption, not a measured large-batch FlowSim CCT.

For two identical, exactly synchronized groups under FAIR, an ideal exclusive service policy can remove at most `b/C` per phase relative to equal sharing. With 48 layers and dispatch+combine, the all-phases-aligned ceiling is:

`ideal removable time = 48 × (b_dispatch + b_combine) × 8 / C`.

That ceiling is intentionally generous: it assumes all 96 phase pairs overlap on the cut, exact group-exclusive service, no additional path bottleneck, and no release drift after network feedback.

## Capacity and threshold table (context 2,048)

| Active requests/group | Dispatch bytes/cut/phase | Combine bytes/cut/phase | Ideal all-96-phase removal | Profile token interval estimate | Ideal fraction | Mean cut bytes/phase for 1% / 3% / 5% |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 17,408 B | 4,096 B | 41.288 µs | 5.367 ms | 0.77% | 13,976 / 41,928 / 69,879 B |
| 4 | 17,408 B | 8,192 B | 49.152 µs | 6.128 ms | 0.80% | 15,958 / 47,873 / 79,788 B |
| 8 | 17,408 B | 16,384 B | 64.881 µs | 6.282 ms | 1.03% | 16,361 / 49,082 / 81,803 B |
| 16 | 34,816 B | 32,768 B | 129.761 µs | 10.117 ms | 1.28% | 26,347 / 79,040 / 131,733 B |
| 32 | 69,632 B | 65,536 B | 259.523 µs | 15.567 ms | 1.67% | 40,539 / 121,616 / 202,694 B |
| 64 | 139,264 B | 131,072 B | 519.045 µs | 16.899 ms | 3.07% | 44,009 / 132,026 / 220,044 B |

The full matrix across contexts is in [`02_EP_BATCH_CAPACITY_TABLE.csv`](02_EP_BATCH_CAPACITY_TABLE.csv). For group64, the ideal all-phase ceiling is 519.045 µs at all three contexts, while the predicted token denominator varies: 15.020 ms at context256 (3.46%), 16.899 ms at context2048 (3.07%), and 23.817 ms at context8192 (2.18%). At 6 ms, 1/3/5% correspond to 60/180/300 µs; that 6-ms reference is historical only and is not substituted for the larger batch's predicted token interval.

## Urgency heterogeneity and overlap correction

The full directed cross-screen contains 132 different pairs of group active-count/context points (`8/16/32/64 × 256/2048/8192`, directed A→B). For each point, the no-contention profile release timeline includes the empirically anchored isolated CCT after each collective barrier. It then finds A/B phase pairs whose **wire-serialization intervals** on the common directed cut intersect. For every A phase with any B service intersection, the bound charges A its entire `b/C` serialization as removable; this ignores partial-overlap fraction and does not recompute later releases. It is therefore an optimistic screening bound, not an actual FAIR-vs-oracle simulation.

The largest target-A value is the 64-request/context2048 group against an 8-request/context2048 group: 10 of 96 phases intersect, and charging each affected A phase its full serialization gives 53.412 µs, 0.3161% of A's 16.899-ms profile token interval. The reverse target gets only 6.676 µs (0.1063%). These different active batch sizes can create different baseline token times, but do not create enough service headroom to justify a robust SLO claim.

For the closest context-only contrast at group64, contexts256 vs512, only 5 of 96 phases have wire-service interval overlap in the isolated release proxy. The corresponding upper removable work is 27.197 µs (0.1811% and 0.1780% of the two group baselines). For larger context gaps (256 vs8192 or 2048 vs8192), the upper values are also below 0.16%; compute-time differences de-align most barriers. Complete rows, including barrier-active interval overlap and release deltas, are in [`02_EP_CONTEXT_PHASE_OVERLAP.csv`](02_EP_CONTEXT_PHASE_OVERLAP.csv).

The decisive contrast is:

1. **Same contexts and same batch sizes:** all phases align, so the 3.1–3.5% group64 theoretical ceiling is possible—but the groups have the same modeled completion work and no reason to prefer A over B.
2. **Different contexts/batch sizes:** the model can assign different baseline urgency, but phase geometry reduces the removable work to at most 0.316% in the screened matrix. Any SLO reversal would require a pre-existing absolute threshold within at most about 53 µs of the predicted baseline; no such service contract was provided.

## Theoretical gate result

- The previous measured 41.280–49.152 µs/token EP–EP loss is reproduced analytically as the 48-layer sum of measured per-phase CCT increments. This validates attribution for those small homogeneous runs; it is not a prediction for larger batches.
- Group64 has more absolute collective bytes, but the compute+isolated-network token interval grows with the batch. Even the synchronized all-phase ideal ceiling remains below 5%, and it does not encode a distinct A/B urgency.
- Profile-derived heterogeneous cases have sub-1% optimistic overlap headroom, with the maximum at 0.3161%.
- No predeclared external TBT SLO exists; SLO misses/attainment are therefore not computable.

**`EP_GROUP_URGENCY_HEADROOM_TOO_SMALL` for the tested 200-Gbps, Qwen3 AG/RS, EP4-per-group profile envelope.** This is a bounded FlowSim/profile conclusion, not a universal statement about every deployment or collective implementation. Since H1 does not pass G1, do not run H1's network oracle or integrated priority cases. The complete raw calculation tables and script are `02_EP_BATCH_CAPACITY_TABLE.csv`, `02_EP_CONTEXT_PHASE_OVERLAP.csv`, `02_EP_HETEROGENEOUS_GROUP_SCREEN.csv`, and `compute_ep_batch_capacity.py`.
