# 04 — Preliminary related-work matrix and venue note

This is a targeted novelty screen, not a systematic survey of every 2012–2026 paper. Because the motivation/oracle gates have not passed, broad literature expansion is deferred rather than used to justify an unproven algorithm. Publication metadata below is linked to primary publisher, conference, or author sources where available.

| Work | Status / venue | Unit and objective | Relevance / direct conflict |
|---|---|---|---|
| [Nuska: Stage-Aware Communication Scheduling for Disaggregated LLM Serving](https://arxiv.org/html/2603.17456v2) (earlier MFS version) | arXiv v2, 2026-09-19; formal venue not verified here | Multi-stage request/batch flows; LLF approximation via Defer-and-Promote/RMLQ; TTFT-SLO | Direct overlap: stage dependencies, intra-/inter-request contention, batch urgency, finite DSCP queues. Decode TBT is not the stated main objective; evaluation uses one-token Decode. This is the main novelty blocker. |
| [Efficient Coflow Scheduling with Varys](https://conferences.sigcomm.org/sigcomm/2014/program.php) | ACM SIGCOMM 2014 | Clairvoyant coflow scheduling; coflow completion objective | Any “collective barrier needs group scheduling” claim overlaps with coflow abstraction and requires a new serving-specific decision difference. |
| [Efficient Coflow Scheduling Without Prior Knowledge (Aalo)](https://doi.org/10.1145/2785956.2787480) | ACM SIGCOMM 2015 | Non-clairvoyant coflows; D-CLAS, discrete priority queues and starvation avoidance | Blocks claims that coflows need prior exact size or that finite priority classes are novel. Handles dependencies/multi-wave workloads. |
| [pFabric: Minimal Near-Optimal Datacenter Transport](https://doi.org/10.1145/2486001.2486031) | ACM SIGCOMM 2013 | Per-flow packet priority, near-optimal FCT | Blocks a generic “flow-level priority on packets” contribution; serving-barrier association must add proven value beyond flow-size/deadline priority. |
| [Finishing Flows Quickly with Preemptive Scheduling (PDQ)](https://conferences.sigcomm.org/sigcomm/2012/paper/sigcomm/p127.pdf) | ACM SIGCOMM 2012 | Distributed preemptive flow scheduling, SJF/EDF-like objectives | Blocks generic preemptive EDF/SJF/deadline claims. |
| [Information-Agnostic Flow Scheduling for Commodity Data Centers (PIAS)](https://www.usenix.org/conference/nsdi15/technical-sessions/presentation/bai) | USENIX NSDI 2015 | Multi-level flow priorities approximating SJF without prior flow size | Relevant deployability baseline for a finite number of priority queues and commodity switches. |
| [Scheduling Coflows of Multi-stage Jobs to Minimize Total Weighted Job Completion Time](https://ieeexplore.ieee.org/document/8486340/) | IEEE INFOCOM 2018 | Dependency-graph/coflow scheduling; weighted job completion | Blocks a generic claim that scheduling dependent coflows or job DAG barriers is unexplored. |

## CCF venue classification snapshot

CCF officially released its seventh-edition recommendation list on 2026-03-31
and noted a 2026-04-09 correction. The list distinguishes conference
`Full paper`/`Regular paper` from short/demo/workshop formats and says it is a
recommendation rather than an evaluation substitute. No venue category is
asserted here: the current research result is NO-GO and there is no validated
paper contribution to match to a venue. If a new direction passes motivation
and novelty, the exact category, CFP year, and full-paper track must be
rechecked against the official list and venue call. See the [official 2026
CCF seventh-edition page](https://www.ccf.org.cn/Academic_Evaluation/By_category/).

## Screen conclusion

The nearest prior work is not a single “similar scheduler”; it is the combination of Nuska's stage-aware TTFT dependency reasoning, coflow collective barriers, and classic finite-priority flow schedulers. A Decode-recurrent TBT objective could be a meaningful evaluation gap, but adding Decode iterations as repeated stages may be a direct extension. A novelty claim requires a concrete minimal workload where that extension is insufficient, not merely that a prior paper's experiments used one output token.
