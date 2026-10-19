# 11 — Prior-work and novelty gate (bounded audit)

This is a focused novelty screen for P0/P1, not an exhaustive systematic review.
Publication status below is stated only as verified from the linked primary
source as of 2026-10-13.

| Work | Status / scope from primary source | Direct overlap with candidate | Consequence |
|---|---|---|---|
| [FAST: An Efficient Scheduler for All-to-All GPU Communication](https://www.usenix.org/conference/nsdi26/presentation/lei-yiran) | USENIX NSDI 2026. Its stated target is all-to-all(v) scheduling for MoE; addresses skew, two-tier fabrics, incast, and balances one-to-one scale-out transfers. | High for sparse A2A realization/scheduling and reducing scale-out communication pressure. | P0 cannot claim novelty merely from selecting/scheduling sparse all-to-all or balancing its transfers. A new result would need a distinct model-semantic/Serving-barrier crossover that FAST does not already cover. |
| [Coordinated Scheduling for MoE LLM Serving (Gimbal)](https://arxiv.org/abs/2606.15177) | arXiv preprint in the checked primary record; no formal venue asserted here. The abstract describes online source-DP-to-expert routing statistics and expert placement jointly considering expert load, source-aware communication, and migration stability. | Very high for P1's generic source-aware, communication-aware expert placement. | “Critical-cut-aware expert placement” alone is not a defensible novelty claim. Need a distinct cut/barrier objective, legal control, and gain beyond Gimbal—not present in this evidence set. |
| [ELDR: Expert-Locality-Aware Decode Routing for PD-Disaggregated MoE Serving](https://arxiv.org/abs/2607.00466) | arXiv preprint in the checked primary record; reports implementation on up to 40 GPUs and TPOT improvements over load-balancing baselines. | High for routing requests to Decode workers based on expert locality and decode performance in PD MoE. | P1 must distinguish expert placement/routing from request-to-Decode routing, and demonstrate more than locality-aware decode placement. No such evidence exists here. |
| [vLLM MoE kernel/all2all backend documentation](https://github.com/vllm-project/vllm/blob/main/docs/design/moe_kernel_features.md) | Official living implementation documentation lists multiple prepare/finalize backends, including naive and DeepEP high-throughput/low-latency variants, with distinct async/format properties. | Relevant to P0: implementation choice is already an explicit runtime/backend dimension, not a new idea by itself. | A simulator-only comparison of AG/RS versus point-to-point must identify a missing mechanism beyond existing backend choice and account for kernel startup/packing semantics. |
| [DeepEP](https://github.com/deepseek-ai/DeepEP) | Official project describes high-throughput and low-latency expert-parallel dispatch/combine kernels. | Relevant to sparse dispatch/combine feasibility and implementation overheads. | The dormant simulator P2P converter does not establish an implementable or novel communication backend. |

## Candidate-specific screen

### P0

Potentially distinct question: whether a Serving workload should use a dense
AG/RS realization or a sparse peer realization as a function of batch, route
matrix, and physical fabric, under equivalent model semantics. However:

- the present network-work formulas are only payload-level;
- the actual vLLM/backend selection already exposes multiple all2all
  implementations;
- FAST directly targets MoE all-to-all scheduling;
- this repository's sparse path is not integrated or validated;
- no Qwen run demonstrates a crossover.

**Novelty: NOT_ESTABLISHED; overlap risk HIGH.**

### P1

Potentially distinct question: a request/collective barrier's critical cut under
fixed rank/GPU/NIC placement, with explicit compute and migration constraints.
But Gimbal already places experts using source-aware communication/load data;
FAST handles all-to-all transfer scheduling; ELDR handles PD-MoE Decode-worker
locality. A paper would need a demonstrated decision that these methods cannot
make, rather than renaming source-aware placement as cut-aware placement.

**Novelty: NOT_ESTABLISHED; overlap risk VERY HIGH.**

## Required comparison if reopened

Before any paper claim, compare against the actual algorithms and controls, not
their names: vLLM AG/RS and available all2all backends; FAST's scheduling
objective; Gimbal source-aware placement with migration constraints; and ELDR
Decode-worker routing. Any surrogate must be labeled as such. No prior-work
baseline is marked “beaten” in this audit.
