# Closest work for a fork-group KV placement hypothesis

Screened 2026-10-14 against full-text mechanisms. The candidate decision is
the online placement of *an observed parent request's concurrently executing
children* across Decode replicas, including shared-prefix dissemination and
the parent resume time. This is a hypothesis, not a demonstrated gap.

| Paper | Problem and workload | Decision variable | Network signal | Serving signal and objective | Mechanism and strong baseline | Reported gain | Candidate difference / overlap |
|---|---|---|---|---|---|---|---|
| [NetKV](https://arxiv.org/html/2606.03910v1) | Disaggregated P/D, Mooncake trace | One request's Decode instance | Static topology tier, residual bandwidth, in-flight self-contention | Prefix hit, Decode queue and cost; mean TTFT/SLO | Per-request greedy over cache/load/network; tuned cache+load scorer (CLA*) | Up to 17.6% mean TTFT over CLA*; full-text ablation says topology gives most of the gain | Group-level parent makespan is outside its per-request objective, but a candidate must beat sequential NetKV-like greedy. A network-aware endpoint scorer alone is already covered. |
| [TokenDance](https://arxiv.org/html/2604.03143v1) | Synchronized multi-agent All-Gather rounds | Group requests for collective reuse and shared/diff KV storage | No physical NIC/path decision | Prefill reuse, KV footprint and SLO agent capacity | One shared RoPE/difference pass for compatible requests, diff-aware KV storage; vLLM prefix caching and CacheBlend | Up to 2.7x active agents under SLO, 1.9x prefill speedup | Physical placement/replication and irregular child release could be distinct; merely sharing sibling KV is not new. |
| [ForkKV](https://arxiv.org/html/2604.06370v1) | Multi-LoRA agents with shared base and divergent adapter KV | DualRadixTree base/residual block allocation and CoW | Disaggregated memory, no inter-node placement policy in the checked mechanism | Memory footprint and throughput | Global base RadixTree plus agent-specific residual tree and SRAM reconstruction; multi-LoRA serving baselines | Up to 3.0x throughput in reported experiments | Branch prefix sharing alone overlaps directly; only network/path-aware group placement would differ. |
| [Agentix](https://www.usenix.org/conference/nsdi26/presentation/luo) | Agent programs with dependent LLM calls | Program-aware priority and preemption, including distributed DAG calls | No explicit P2D topology cost in the published scheduling objective | Program completion and critical path | ATLAS extends attained-service priority along the DAG critical path; request-centric vLLM baseline | 4–15x program throughput at equal latency in reported experiments | Parent critical path is already first-class; merely prioritizing stragglers is not new. Network-prefix interaction would need an independent gain. |
| [TOPAS](https://arxiv.org/abs/2608.25523) | Multi-agent workflows with shared KV capacity | Joint cache retention and request execution order | Prefix movement/preemption cost, no physical P2D path detail in the abstract | Task longest remaining path and JCT | Scores post-decision states for path progress and future prefix reuse; strongest per-workload scheduling baseline | Up to 39.8% mean JCT in synthetic DAGs and 9.8%/22.0% on MetaGPT workflows | Cache-aware DAG scheduling is close; network replica degree must add value beyond it. |

**Novelty gate.** No algorithm should be implemented until the released trace
shows a non-isolated cohort with (1) real concurrent siblings, (2) material
shared prefix, (3) evidence that shared-KV dissemination can affect parent
resume or a declared client metric, and (4) a profile-valid model mapping.
The group scheduler must then beat all-one, equal split, shortest queue,
cache-aware greedy, NetKV-like greedy and marginal-cost group greedy; offline
oracle is only a headroom diagnostic. NetKV's reported gain is *not* an
estimate of this candidate's gain.
