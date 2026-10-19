# Direction C — batch composition and EP cut geometry

## Necessary conditions

At least two legal batches with the same token set, same expert-compute work, same total communication work, and unchanged hardware must nevertheless induce different owner-rank traffic across an actual bottleneck cut. A cut-work delta matters only if it changes the last required collective flow; the collective delay must then survive compute overlap and show up in an integrated token/request metric.

One token's raw top-8 BF16 hidden payload is `8×2048×2 = 32,768 B`; for 64 tokens, 2 MiB. This is not a claim about wire bytes: local experts, router dispatch representation, combine traffic, aggregation, and the simulator's collective semantics all matter.

## Current capability boundary

`serving/core/gate_function.py` exposes BALANCED/RR/RAND/CUSTOM policies. BALANCED uses a closed-form per-rank count approximation; it does not preserve a source-backed token→expert-owner matrix that could be replayed unchanged under different legal batch memberships. The retained integrated EP4 experiment uses ALLGATHER/REDUCESCATTER rather than a sparse A2A peer matrix. Thus the required matched input cannot currently be generated without inventing token routes or changing semantics.

## Prior-work screen and decision

FAST directly schedules MoE All-to-All; Semantic Parallelism jointly schedules model/expert placement and requests/tokens; Gimbal coordinates serving and source-aware expert scheduling. A useful C result would need to define a mechanism beyond these, not simply sort batches by a traffic matrix. With no verified exact traffic matrix and no evidence that a novel remaining decision exists, the network-only generator and integrated experiment are gated off.

Decision: `C_NO_TRAFFIC_GEOMETRY_HEADROOM` within the current data path. No simulation result is claimed.
