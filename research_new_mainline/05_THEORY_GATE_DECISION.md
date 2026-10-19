# Theory gate decision

Date: 2026-10-12.

## Decision

**`THEORY_GATE_NOT_PASSED — DO NOT RUN NEW SERVING/FLOWSIM MOTIVATION EXPERIMENTS`.**

This is not a claim that MoE owner-level overlap can never help. The abstract exact scheduler proves it can help when dispatch, compute, and return critical owners differ. The current authoritative Qwen3 source/profile/route pipeline does not provide a calibrated, physically mapped `d_i,c_i,r_i` case from which a conservative ≥5% Decode-interval or SLO headroom can be established. The task's gate requires evidence, not an abstract witness.

The broad claim “remove a global MoE barrier and stream owner computation” is also not novel enough on its own: owner/task partitioning and compute/communication overlap are addressed by FinDEP and EPS-MoE; COMET (MLSys 2025) explicitly resolves fine-grained token/tile dependencies and overlaps dispatch→compute and compute→return communication; a 2026 ICPP paper covers tile-signaled partial return overlap. The candidate would need a narrower, evidence-backed difference around external directed network cuts and the final Decode token barrier before any algorithm work.

## Findings

1. **Standard DAG is AG/RS.** Current `_emit_moe_block()` emits AllGather dispatch and ReduceScatter combine; FlowSim finishes all collective nodes only when all peer flows finish. This path has a group-wide synchronization boundary.
2. **A2A_P2P has partial rank-local streaming already.** The dormant converter creates individual peer flows and a local join per rank, but joins outgoing and incoming transfers together. It does not wait for all rank joins to release each rank's compute. Its group-CCT completion is telemetry, not a node dependency.
3. **The integrated standard path does not pass the sparse route matrix.** `generate_graph()` never provides `ep_global_ranks`/`a2a_routing`, and current GateRouter does not return a pair matrix.
4. **Existing route sidecars do not fill the gap.** The sampled EP32 BALANCED sidecars have 2 tokens/2 activated experts per owner; the measured MoE profile starts at 8 activated experts. They cannot supply a valid profile-backed `c_i`.
5. **The exact numerical owner-streaming headroom is therefore uncomputable from current authoritative artifacts.** It is not legitimate to substitute a synthetic matrix or extrapolated profile and call the resulting percentage a Qwen prediction.
6. **The reference scheduler is internally consistent** on abstract positive/negative examples, but does not validate the project backend or serving metric.

## Source hashes

| File | SHA-256 |
|---|---|
| `serving/core/trace_generator.py` | `65e54faf30dbc51638aa5f7a0c3b554fe8248060a74576f7dbdb70dc95923aa5` |
| `serving/core/gate_function.py` | `75c5fb5914a07aa601486f644407676a3bf3c60faaacbd3b72179baaf5c4502e` |
| `serving/core/flowsim_worker.py` | `36435f5ac8f8e0a78b153f941f08816fde3683017cd7a39a9a3469c9afa77feb` |
| `serving/core/graph_generator.py` | `7ea96c919d9b6198e69a9bf27a12004cd6074711b1556e0233c4de30fcfcac23` |
| Chakra `llm_converter.py` | `e65d863eac39da5ffa2c76cf8300a8b3b54b2e5ddd8b270421d805329ccfb76f` |
| Qwen model config | `0736f3bafb95cc658776c92ab34f5f98f8169634a3a36b84892d71448a1f19d3` |
| RTX PRO 6000 profile meta | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| RTX PRO 6000 `tp1/moe.csv` | `aa6e29a17412a62234a6610d7a699f72e5938f09386374b635925c5db29045f6` |

## Required gate consequence

- No Qwen calibrated network-only experiment.
- No serving-integrated comparison.
- No policy/scheduler implementation.
- The only execution was the independent abstract reference calculator and existing focused unit tests.

Reopen this candidate only after a source/profile artifact bundle can provide: (a) actual per-layer source→owner token/byte matrix, (b) physical EP rank/NIC mapping and directed paths, (c) in-domain per-owner compute profile rows, and (d) matching rank-local dependency/buffer semantics. Then compute a conservative cut/GPU-aware lower bound **before** running FlowSim.

