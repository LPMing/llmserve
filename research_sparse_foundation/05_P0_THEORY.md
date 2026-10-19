# 05 — P0: sparse A2A versus AG/RS realization

## Question and decision boundary

P0 asks whether two *semantics-equivalent* MoE dispatch/combine realizations
have a model- and Serving-relevant cost crossover. A byte-volume difference
alone is not a performance crossover. The comparison must include startup,
collective synchronization, topology, contention, expert inputs, and the
subsequent 48-layer token critical path.

## Exact model constants available

From the checked-in Qwen3-30B-A3B config: 128 experts, top-k 8, hidden size
2,048, BF16 (2 bytes/element), 48 layers. Thus one hidden activation is
`b = 2048 × 2 = 4096 bytes`. Current trace code's AG dispatch uses
`b_AG,d = (2048 + 128) × 2 = 4352 bytes/token` and RS combine uses
`b_AG,c = 4096 bytes/token`.

## Payload-only lower-level model

For `N` tokens and EP degree `p`, let `M_ij` be the count of token-owner pairs
from source rank `i` to owner rank `j`, with `i != j`. Under the checked-out
converter's one-activation-per-destination-owner representation:

```text
B_sparse_dispatch = b × Σ(i≠j) M_ij
B_sparse_combine  = b × Σ(i≠j) M_ij
```

The current AG/RS trace represents a ring-style dense exchange. Its payload
work, before physical multi-hop path expansion, is approximately:

```text
B_AG_dispatch = N × (p−1) × 4352
B_RS_combine  = N × (p−1) × 4096
```

These equations omit routing metadata, alignment/padding, protocol headers,
launch/startup costs, compute overlap, physical path multiplicity, contention,
and differences in actual implementation. They are not collective completion
times. A network-work lower bound must instead use the actual per-directed-cut
work and capacity, for example `max_e(W_e / C_e)`, and the serving barrier must
follow the legal compute/communication DAG.

## Illustrative uniform-router expectation (not Qwen routing evidence)

To check scale only, assume each token selects 8 distinct experts uniformly
without replacement from 128, experts are evenly assigned (`128/p` each),
source ranks are uniform, and one activation is sent once to each selected
owner rank. Expected unique destination owners per token:

```text
U(p) = p × [1 − C(128 − 128/p, 8) / C(128, 8)]
E[remote owner ranks] = U(p) × (1 − 1/p)
```

The second line uses symmetry: the source rank is itself among the selected
owners with probability `U/p`. Payload-only ratio below compares sparse
dispatch+combine to the above AG+RS formula. It is an analytic random-routing
expectation, **not** a learned Qwen router observation, route sidecar, FlowSim
result, or performance prediction.

| EP `p` | Experts/rank | `E[unique owners]` | `E[remote owners]` | Sparse/AG-RS payload ratio |
|---:|---:|---:|---:|---:|
| 4 | 32 | 3.6290 | 2.7218 | 0.8798 |
| 8 | 16 | 5.3394 | 4.6719 | 0.6472 |
| 16 | 8 | 6.5965 | 6.1842 | 0.3998 |
| 32 | 4 | 7.3594 | 7.1294 | 0.2230 |
| 64 | 2 | 7.7795 | 7.6580 | 0.1179 |

This indicates a possible *payload-work* advantage for sparse dispatch at high
EP under the stated assumption. It does not imply a time crossover: dense
collectives may have lower per-message/setup costs, and sparse transfer may
create more distinct peer messages. At EP4 the payload gap is especially small.

## Missing terms that prevent a Qwen crossover conclusion

1. No checkpoint-derived token→expert outputs or real `M_ij` matrices.
2. The installed runtime's actual all2all implementation and byte packing are
   not bound to the current run artifact; the simulator's AG/RS path is an
   aggregate analytical realization.
3. No measured startup/launch/peer-message cost for either realization on the
   target RTXPRO6000 plus 2×200-Gbps NIC topology.
4. EP32/EP64 activated-expert compute queries are outside the measured profile
   grid, so the compute overlap and 48-layer critical path are not calibrated.
5. The sparse A2A graph path is not wired into ordinary `generate_graph()` and
   has no end-to-end correctness run.
6. The S16 logical/physical rank mapping does not pass audit.

## Theory gate

The abstract payload model has a meaningful scaling contrast, but the mission's
required **same-model-result, profile-supported, topology-specific execution
cost crossover** is not established. No P0 simulation is authorized. This is
not evidence that P0 has no crossover; the gate is blocked by model and runtime
provenance.
