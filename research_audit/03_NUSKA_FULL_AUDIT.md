# 03 — Nuska / MFS full-paper audit (v2)

**Primary source reviewed:** [arXiv HTML, version 2](https://arxiv.org/html/2603.17456v2), listed as arXiv:2603.17456v2 and dated 2026-09-19 in the source. At the time of this audit, this source establishes an arXiv preprint; a formal proceedings publication was not verified. MFS is the earlier name/version of this work, not a separate independent prior paper.

## What it actually solves

Nuska targets TTFT SLO attainment for disaggregated serving with multi-stage Prefill communication. The paper explicitly discusses both intra-request and inter-request contention. Its request workflow includes remote reusable-KV retrieval, model-parallel collective communication, and P2D handoff. It argues that network flows in dependent stages can overlap over shared bottlenecks.

The method is not merely a traffic-class priority rule:

- It formulates a multi-stage flow/coflow dependency problem and approximates LLF without requiring exact request remaining slack.
- For explicit-deadline last-stage P2D, it defers then promotes flows using a minimal-link-utilization condition and layer-granular updates.
- For implicit-deadline early stages, it defines Relative Layer Index (RLI), prioritizing communication that blocks the current layer over future lookahead traffic.
- For inter-request arbitration, it defines Robust Effective Deadline (RED), partitions tight and loose requests within a batch to avoid piggybacking, and applies overload feasibility/pruning to avoid spending bandwidth on doomed work.
- It uses a Reverse Multi-Level Queue, host-side queues/daemons/coordinator, task submit/permit/completion integration, and maps priorities to finite DSCP/network priority classes.
- It explicitly considers batch/request associations, shared collective stages, and finite priority classes; it does not assume an infinite physical queue count.

The paper states that its testbed Decode output is limited to one token because it does not affect TTFT. Its objective/evaluation therefore centers on TTFT, not repeated Decode TBT/TPOT. That is a potential scope distinction, not by itself a novelty claim.

## Direct overlap with this project

The following proposed claims are already preempted by the v2 paper and cannot be claimed as novel without a materially different mechanism and evidence:

1. “Existing work does not coordinate inter-request flows.” Nuska explicitly provides inter-request arbitration.
2. “Traffic classes are insufficient; assign priority per request.” Nuska orders requests/batches using RED and tracks stage dependencies.
3. “A KV flow can have slack and should be deferred until urgent.” Nuska's explicit-deadline P2D uses defer-and-promote; early KV reuse uses RLI.
4. “A collective should be treated as a barrier/coflow.” Nuska models stage collectives and notes their blocking relation to subsequent compute; coflow work predates it.
5. “A small number of switch queues makes fine priority difficult.” Finite queues, DSCP mappings, and host-level scheduling are part of Nuska's design.

## Plausible distinction that remains unproven

The only plausible scope distinction is the continuing sequence of Decode
token-iteration barriers and cross-group recurring EP collectives measured by
TBT. Nuska's stated objective is TTFT and its testbed uses one generated token.
But a repeated Decode collective can be modeled as another stage/barrier in a
DAG, and LLF/RED or coflow/collective scheduling could extend directly. This
project now represents two independent EP4 groups in one bounded layout and
measured shared-link dispatch CCT +6.39%, combine +1.58–3.11%, but only
TPOT/TBT +0.75–0.80%. No experiment shows a TBT-oriented decision diverging
from Nuska/LLF/coflow or enough headroom to justify implementing one.

Therefore recurrent Decode barriers remain an unproven evaluation scope, not
a paper contribution. The latest full arXiv v2 source was reviewed at
https://arxiv.org/html/2603.17456v2; as of this audit, a formal proceedings
publication was not verified.

## Gate verdict

**Novelty relative to Nuska: NOT PASSED.** The proposed general “request/barrier-aware network scheduling” overlaps strongly with Nuska's explicit multi-stage, inter-request, batch/request-aware design. Decode-recurrent TBT is a possible measurement distinction, but the new multi-group FlowSim case has <1% serving effect and no algorithmic decision divergence. Do not claim superiority over Nuska based on the current FlowSim/ns-3 data.
