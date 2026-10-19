# Current candidate pool: evidence closure (2026-10-15)

**Historical Round-17 checkpoint.** This document records the old
ten-candidate evidence pool under the earlier combined motivation and
headroom criterion. Round 18 subsequently validated a controlled P/D
KV-residency inversion under the user's separate `MOTIVATION_VALIDATED`
gate. See `MOTIVATION_REPORT.md` and `MOTIVATION_GATES.md`. The older
negative experiments and missing-data findings below remain intact;
the final sentence here describes the Round-17 state only.

No `MOTIVATION_VALIDATED` claim is supported by the ten candidates screened
against the available exact-model profiles, declared physical topologies and
committed or pinned traces. This closes the **current evidence pool**, not
all possible LLM serving/network research questions. A `NEED_DATA` row is
an explicit unresolved dependency, never a positive performance result.

| Candidate | Strong-baseline or Oracle gate | Current result |
|---|---|---|
| Network-staged P/D handoff | Cold Qwen3-32B layerwise transfer; capacity-aware admission and P:D ratio in a memory-full case | Cold1–4P last flow is hidden by compute; 30-request normal-pool correctness stress has all last flows5.1–5.8 ms before ready. Simultaneous uniform overload supplies no policy headroom claim. |
| Shared-source-NIC prefix placement | Cache-aware D choice, DELTA, single-flight and ideal prior-prefix retention | Fixed-byte cut service is within0.045% of serialization floor. Ideal prior reuse is only7.59–7.90% of aggregate prompt tokens in the committed ShareGPT traces; no strong-baseline incremental policy case is established. |
| P2D versus Decode EP | FAIR, EP_FIRST, KV_FIRST, no-later-wave control | In the24-request matched cut, P2D/EP overlap exists but P2D-ready is invariant; generous old-cohort completion interference Oracle is0.279%. |
| PP-stage coflow | Layerwise transfer with topology-aware placement | 4P1D last flow is1.157 ms before ready; zero-network schedule gain on the gate. |
| Symmetric fork replication | One D, equal four D, marginal-cost group choice | Same-resource strong-baseline envelope leaves at most3.45%; real heterogeneous fork needs matching tokenization/profile and an observed join. |
| Heterogeneous P/D TP | Same-GPU-budget TP2 Decode | Even an optimistic two-TP1 Decode pair offers at most51.6% of one TP2's measured decode rate in the declared shape. |
| Serial Decode skew rebatching | Existing mixed batch, length-aware splitting and vLLM skew-aware kernel | Every249 capacity-feasible profiled shape slows under serial split; best is29.6% slower. Zero-skew kernel is only an unrealizable Oracle. |
| Agentic lower-tier prefetch | On-demand/SYMPHONY-style prefetch | All765 prompt sidecars lack141 IDs; no observed lower-tier miss or timed CXL service. Conditional read floor is not a Serving gain. |
| FreeInference irregular fork | One/equal/marginal-cost placement with explicit parent join | Observed groups use other provider models/tokenizer; no verified exact-model fork DAG or join metric. |
| Chutes Qwen3-32B arrivals | NetKV-like cache/load/topology routing, layerwise transfer, local Prefill deflection | Physical P/D roles/NIC topology and reusable prefix IDs are unavailable; network critical path cannot be established. |

The simulator audit and raw checks are in `SIMULATOR_CAPABILITY_AUDIT.md` and
`RESEARCH_LOG.md`. The opt-in D capacity-credit repair makes a normal-pool
P/D stress run byte- and event-consistent; it has zero-time control-plane
operations and is not a calibrated hardware backpressure model. The
agentic hash repair conservatively disables prefix matching when prompt
IDs are incomplete. Neither repair creates a ≥10% motivation.

A future reopening requires one of: (1) exact-model, token-identifiable,
ordered P/D traces with physical NIC topology and stable offered load;
(2) observed Decode KV misses with measured lower-tier load service;
(3) exact-model long-context fork traces with explicit join semantics.
Then the same strong baselines and client/Serving metric boundaries must
be rerun before a paper mechanism is designed. No motivation experiment
has been frozen and no `MOTIVATION_REPORT.md` has been generated.
