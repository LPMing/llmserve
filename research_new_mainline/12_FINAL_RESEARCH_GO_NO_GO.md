# Final research decision

## Result

**`NO_GO_FOR_GENERIC_OWNER_STREAMING_MOTIVATION`** under the current audited source/profile and available evidence.

The decision is deliberately bounded. It rejects starting a Serving/FlowSim motivation run on the present inputs; it does not prove that all physical deployments lack exploitable owner-level overlap.

## Why

1. The abstract dependency model has a positive witness, but it is not Qwen-derived.
2. Standard integrated Serving emits AG/RS; the source-owner sparse route and physical mapping required to compute per-owner dispatch/return release times are not wired into graph generation.
3. The dormant P2P converter already has rank-local joins, so “remove a group-wide barrier” is inaccurate for that path. Its join may be too conservative by including outgoing sends, but buffer/transport semantics and per-owner route data are needed before labeling that wait avoidable.
4. Existing EP32 sidecars have out-of-domain owner compute shapes for the RTX PRO 6000 profile.
5. No profile-supported `H_optimistic` or conservative ≥5% token-interval/SLO headroom can be reported. A fabricated bound would violate the mission's gate.
6. Generic owner/task streaming is substantially overlapped by FinDEP, EPS-MoE, COMET (MLSys 2025), and recent tile-signaled MoE overlap work. COMET already resolves fine-grained token/tile dependencies and overlaps both dispatch→compute and compute→return communication. A network-cut-aware Decode-barrier distinction remains unproven.

## Evidence classification

- Standard AG/RS group barrier exists in the simulator graph: **confirmed**.
- Dormant A2A_P2P supports rank-local join progress: **confirmed from converter source**.
- P2P join is stricter than inbound readiness: **confirmed structurally**, but whether the extra outgoing-send dependency is physically removable depends on actual buffer lifetime/runtime semantics.
- A real Qwen owner-level serving gain: **not established**.
- TTFT/TBT/SLO benefit: **not run and not inferred**.
- Packet-level network validation: **not run**.
- Current broad simulator baseline: **partially validated**, not blanket certified.

## Exact reopening checklist

Reopen only when one self-consistent, hash-bound bundle contains:

1. Per-layer actual source→owner token/byte matrix and selected experts, with route provenance.
2. Physical EP rank→GPU→NIC map and directed paths/cuts.
3. Owner compute shapes inside RTX PRO 6000 MoE profile domain (or a new measured profile for the needed task size).
4. Real buffer/transport constraints showing which outgoing transfers may overlap owner compute and when combine output is consumable.
5. A conservative lower-bound calculation that predicts at least about 5% token-interval benefit or a predeclared SLO-relevant gain.

Only then should a minimal FlowSim correctness comparison be considered. Until then, do not implement a scheduler, alter the serving DAG, or call an abstract tick gap a Qwen performance result.

