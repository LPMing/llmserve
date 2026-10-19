# 3P2D Fixed-Resource Mapping Audit

## Resource count

Both static deployments use the same five physical server slots and ten active TP2 ranks:

| Deployment | Prefill instances | Decode instances | TP2 instances | Active model ranks |
|---|---:|---:|---:|---:|
| 4P1D | 4 | 1 | 5 | 10 |
| 3P2D | 3 | 2 | 5 | 10 |

Every modeled scale-out rail link is 200 Gbps. The hardware abstraction describes each server as 8 GPUs and two shared 200-Gbps NICs; it does not mean every GPU gets an independent 200-Gbps link. The experiments keep five server positions and the same physical topology/rank-map resource set, repurpose one server from Prefill to Decode, and keep two active compute ranks per instance.

## 3P2D active rank placement

Logical TP rank pairs map as follows:

| Logical instance | Role | Logical TP ranks | Mapped physical endpoint IDs | Server slot |
|---|---|---|---|---|
| P0 | Prefill | 0–1 | 0, 4 | host 0 |
| P1 | Prefill | 4–5 | 8, 12 | host 1 |
| P2 | Prefill | 8–9 | 16, 20 | host 2 |
| D0 | Decode | 12–13 | 24, 28 | host 3 |
| D1 | Decode | 14–15 | 32, 36 | host 4 |

The values above are physical endpoint IDs consumed by the FlowSim rank mapper, not GPU ordinal numbers. The complete explicit logical-to-physical mapping, including compatibility/shadow ranks, is `3p2d_logical_to_physical.json`; generated config is `3p2d_tp2_flowsim.json`. P2D pairing is static: P0/P1 feed D0 and P2 feeds D1. The B experiment retains the same total five TP2 instances; no extra active GPU rank is added.

## Important modeling limits

1. This mapping validates equal active rank count and rail capacity, not GPU-level PCIe/NIC arbitration.
2. Only TP2 ranks per instance are active. The 8-GPU/server, 2-NIC sharing factor is not saturated with eight concurrent GPU senders.
3. Decode placement changes which physical receiver serves each session. Cache state is not magically migrated; actual session replay and cache lookup determine hits.
4. A 2P3D comparison is **not represented by the present graph**: each Prefill aggregate graph is paired with one static Decode receiver; it cannot split per-request flows across three Decode destinations. A config with an idle third Decode would be an invalid utilization comparison, so B2P3D is `NOT_RUN_UNREPRESENTABLE`, not a negative result.
5. Dynamic 4P1D→3P2D is not modeled. There is no legal role-switch/migration model for weights, GPU state, cache residency, in-flight work, or connections. It is not treated as zero-cost.

## Result interpretation

3P2D is a valid fixed-resource static comparison under the modeled active-rank/rail abstraction. It is not evidence for elastic role conversion, full multi-GPU shared-NIC behavior, or three-destination P2D routing.
