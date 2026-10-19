# 09 — Paper blueprint (conditional, not a validated paper plan)

**Status: NOT READY / candidate closed on current evidence.** The previously open two-group capability gate is now tested, but its serving effect is below 1% TPOT/TBT and it does not expose a meaningful optimization opportunity. Keep this as a record of what would be required only if a separate, independently justified mechanism reopens the direction.

## Conditional problem statement

If a valid multi-Decode-group experiment later shows that independently recurring EP collective barriers contend with other requests' KV/EP traffic and that known stage-aware/coflow baselines leave material TBT headroom, the candidate problem may be framed as scheduling network service for recurrent Decode barriers under request/batch aggregation and finite priority resources.

## Required evidence before title/contributions

1. Immutable source commit and fully reproducible correctness suite.
2. Valid topology with at least two independent collective groups, physical paths and shared directed resources.
3. Same workloads/bytes/releases compared under FAIR, classic flow scheduler, coflow/collective scheduler, and faithful Nuska-style surrogate where full reproduction is unavailable.
4. Offline oracle showing nontrivial serving-level upper bound.
5. Implementable finite-queue or host-side realization that captures meaningful fraction of oracle gain without starvation or ACK/CNP interference.
6. Packet-level validation and integrated serving feedback, with complete per-token TBT attribution.
7. A focused related-work audit and current CCF seventh-edition venue verification.

## Current contribution count

Zero validated paper contributions. Correctness repairs and negative characterization are useful project assets but are not themselves evidence of a new scheduling technique.
