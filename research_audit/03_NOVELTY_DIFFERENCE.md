# 03 — Candidate novelty difference

## Candidate under examination

“Fine-grained Request/Barrier-Aware Network Scheduling for PD-disaggregated MoE Serving.” This is a hypothesis to audit, not a result.

## Decision comparison against Nuska

| Dimension | Nuska v2 | Candidate distinction needed | Evidence here |
|---|---|---|---|
| Request/inter-request urgency | RED orders requests/batches; overload feasibility/pruning | Show a legal state in which RED/LLF makes a different decision than a Decode barrier-aware method | No such run |
| Within-request stage urgency | RLI and defer/promote over layers | Show a recurring Decode iteration relation not reducible to a stage/barrier DAG | Not established |
| Collective/coflow | Collective communications are modeled as blocking stages | Show collective completion needs coordinated peer-set treatment beyond ordinary coflow scheduling | Current AG/RS group barrier is instrumented, but no oracle result |
| TTFT/TBT | Main objective/evaluation is TTFT; testbed output is one token | Demonstrate repeated Decode TBT critical path and a method-specific gain | Two-group EP4 FlowSim: TPOT/TBT +0.75–0.80%; no policy decision or gain |
| Finite hardware priorities | RMLQ/DSCP plus host queues and daemon/coordinator | Show implementable improvement under same finite queues and RDMA controls | Not tested |
| Batch aggregation | Inter-request policy is batch-aware | Preserve real collective aggregation; no synthetic per-request flow split | Current one Decode group produces aggregate group collective |

## Novelty gate result

**FAIL for the generic request/barrier priority claim; Decode-TBT specialization lacks motivation.** A new name, request IDs on flows, EDF/LLF, or coflow language does not create novelty. The bounded independent-group case is now implemented, but its integrated serving effect is below 1%. The following remaining conditions were not met:

1. a classical flow/LLF/coflow/Nuska-like decision differs from the candidate;
2. a legal oracle shows meaningful TBT/TTFT headroom;
3. a practical finite-priority implementation preserves ACK/CNP and fairness.

Until then, no scheduling algorithm should be implemented.
