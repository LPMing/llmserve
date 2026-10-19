# Related-work and novelty audit (focused, 2026-10-12)

This is a focused audit of the nearest work for the current two motivation
directions, not a comprehensive systematic review of every scheduling paper.
Publication status below is limited to what the linked primary/official
records establish.

| Work | Status / venue | Overlap with this experiment | Consequence for novelty |
|---|---|---|---|
| [Nuska: Stage-Aware Communication Scheduling for Disaggregated LLM Serving](https://arxiv.org/abs/2603.17456v2) (same arXiv lineage previously titled MFS) | arXiv v2, revised 2026-09-19; no venue listed on arXiv at audit time | Explicitly covers reusable-KV retrieval, model-parallel collective communication and P2D transfer; intra-request and inter-request contention; LLF-like Defer-and-Promote/RMLQ; layer-granular promotion; host-side task queues mapped to DSCP priorities. Its stated objective is TTFT SLO, and its detailed formulation is prefill-layer MsFlows. | Directly preempts generic “stage/request-aware KV-vs-collective scheduling,” flow laxity, defer/promote, and finite switch priority as novelty. A Decode-recurrent TBT/EP extension might differ, but this experiment does not demonstrate a scheduling win beyond static EP_FIRST, and its EP workload is not exact GateRouter A2A. |
| [STORM: Enabling Traffic Scheduling for RDMA](https://doi.org/10.1145/3789240.3829117) | ACM SIGCOMM 2026 proceedings; DOI and proceedings listing verified | NIC-level scheduling across RDMA workload types using request size and per-QP backlog; prioritizes near-completion requests or requests blocking dependent work, using a small number of wire priorities. | Strongly overlaps generic flow-/dependency-aware RDMA priority and finite-priority mapping. A new proposal cannot claim novelty for “use QP backlog/remaining work to prioritize dependent flows” alone. Our current FlowSim does not model this NIC scheduler. |
| [FuseLink: Enabling Efficient GPU Communication over Multiple NICs](https://www.usenix.org/conference/osdi25/presentation/ren) | OSDI 2025, published | Targets server multi-NIC GPU communication and static GPU-NIC binding hotspots; dynamically relays traffic across NICs, with measured LLM first-token and MoE gains. | Direct prior art for multi-GPU/multi-NIC utilization and load-aware rail use. The present static four-GPU-per-rail fixture is a resource-sharing characterization, not a novel multi-NIC placement/scheduling mechanism. |
| [RailWave: Adaptive Spatial and Temporal Scheduling for Expert-Parallel Communication](https://arxiv.org/abs/2610.03415) | arXiv preprint posted 2026-10-02; no publication venue verified | MoE EP all-to-all communication uses rail balancing and a reusable temporal sender permutation to address rail imbalance/incast. The shown workload is training-derived. | Makes generic “shape EP traffic across rails/time” crowded. The present serving request barriers differ, but no such new mechanism has been proven here. |
| [SwiftRDMA: Exposing RDMA NIC Resources for Software-Defined Scheduling](https://doi.org/10.1145/3735358.3735359) | APNet 2025 proceedings paper / software-defined scheduling vision | Frames RDMA shared hardware resources as a software scheduling problem and connects signals/actions to application objectives. | Prior art for the broad “RDMA resources should be scheduled jointly with application goals” premise; not by itself evidence that it implements this serving-specific barrier policy. |
| [pFabric: Minimal Near-Optimal Datacenter Transport](https://doi.org/10.1145/2486001.2486031) | ACM SIGCOMM 2013 | Flow-level priorities, packet priority scheduling/dropping, and flow completion objectives. | Per-flow priority alone is not new. It also highlights the gap between fluid simulation and packet-level enforcement. |
| [Efficient Coflow Scheduling with Varys](https://istc-cc.cmu.edu/publications/papers/2014/varys-sigcomm14_abs.shtml) | ACM SIGCOMM 2014 | Application-level groups of parallel flows scheduled by a shared completion objective. | Collective/request barrier grouping is related to the established coflow abstraction. Calling a set of EP peer flows a “barrier group” is not sufficient novelty. A new contribution would need a demonstrated difference from coflow/dependency-aware scheduling under Decode's repeated token barriers. |
| [PDQ: Finishing Flows Quickly with Preemptive Scheduling](https://conferences.sigcomm.org/sigcomm/2012/paper/sigcomm/p127.pdf) | ACM SIGCOMM 2012 | Distributed, preemptive flow scheduling that approximates disciplines such as SJF/EDF and supports deadlines/multipath. | Flow preemption, deadline/size-based ordering and distributed priority are established. A serving-specific claim must show why request/token barrier dependencies need a materially different decision. |
| [PIAS: Information-Agnostic Flow Scheduling for Commodity Data Centers](https://www.usenix.org/conference/nsdi15/technical-sessions/presentation/bai) | USENIX NSDI 2015 | Switch MLFQ priorities demote flows as bytes are sent, approximating SJF without prior size knowledge on commodity priority queues. | Small-flow favoritism, finite switch queues and deployable flow priority mapping are not novel by themselves. PIAS optimizes FCT, not the serving barriers in this experiment. |
| [QCLIMB: Flow Scheduling with Imprecise Knowledge](https://www.usenix.org/conference/nsdi24/presentation/li-wenxin) | USENIX NSDI 2024 | Uses imprecise flow-size information to schedule DCN flows between information-agnostic PIAS and exact-size pFabric. | Recent prior art for imperfect flow-work estimates. A proposed remaining-work/urgency signal must compare against this family, not only FAIR. |
| [FLASH: Fast All-to-All Communication in GPU Clusters](https://arxiv.org/abs/2505.09764) | arXiv preprint (2025); no formal venue verified in the primary record reviewed | Schedules GPU-cluster All-to-All to keep the inter-server bottleneck busy and use faster intra-server shuffling to mitigate skew/stragglers. | Directly overlaps collective transfer/straggler scheduling, but not cross-request KV/EP arbitration or serving TBT. Current FlowSim uses AG/RS, not this paper's scheduled A2A realization. VarioPath uses the label “FAST” for a baseline; do not assume that label refers to this same version without source-level confirmation. |
| [VarioPath: Topology-Aware All-to-All Communication Scheduling for PCIe GPU Clusters](https://arxiv.org/abs/2609.34340) | arXiv preprint posted 2026-09-28; no venue verified | Topology/demand-aware A2A planning for PCIe GPU clusters, including resource/path contention and workload-aware scheduling. | Makes generic topology-aware EP/A2A scheduling crowded. A distinct serving-barrier interaction needs an explicit matched comparison; no such result exists here. |
| [CommBench: Micro-Benchmarking Hierarchical Networks with Multi-GPU, Multi-NIC Nodes](https://doi.org/10.1145/3650200.3656591) | ACM ICS 2024 | Benchmarks communication libraries and hierarchical GPU/multi-NIC node/network behavior. | Relevant for validating shared-NIC and rail assumptions on hardware, but it is measurement/benchmark work rather than serving-aware scheduling. A future packet/testbed claim should calibrate the hierarchy against measured behavior. |
| [NCCL PXN documentation](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/env.html#nccl_p2p_pxn_level) | NVIDIA NCCL implementation documentation (not a paper) | Allows communication to use a non-local NIC through an intermediate GPU and can aggregate node traffic onto a NIC. | Deployed path/rail behavior can change which GPU traffic shares a NIC. It is not request-urgency or serving-barrier arbitration; the current abstract GPU→NIC map does not validate PXN. |
| [Libra: Efficient LLM Serving with Fine-Grained Request Scheduling](https://www.usenix.org/conference/nsdi26/presentation/ruan-libra) | USENIX NSDI 2026 | Request partitioning and token-boundary microrequests, global split selection, local SLO-aware batch scheduling and chunked KV movement. | Direct serving-side scheduling/KV chunking prior art. It does not establish packet-level network priority, but raises the bar for claims based only on request splitting or SLO-aware request scheduling. |

## Specific novelty questions

1. **Same-class KV urgency:** controlled same-cut KV–KV runs exist. A 128-token
   victim's shard-FCT P99 rose +25.35% against a 2048/8192-token background,
   but its last-shard completion, KV-ready time and TTFT did not move. The
   prompt-size skew is only a candidate urgency difference: this experiment
   did not record calibrated per-request slack/deadlines. A useful
   serving-level scheduling opportunity was not demonstrated. In the separate
   B ledger, all candidate KV flows also finish before the Prefill callback,
   yielding a zero TTFT-gain bound for request-targeted KV priority in that
   frozen workload; this is not an executed replay. Nuska already
   differentiates request/stage urgency for TTFT, while STORM uses NIC-visible
   request size/backlog/dependency signals.
2. **Same-class EP collective urgency:** two legal EP4 groups did compete on
   a shared directed cut in a prior controlled run; integrated TBT rose only
   +0.75–0.80%. No same-class urgency oracle was run. Group scheduling also
   has close coflow/PDQ analogues, so these small effects are not novelty
   evidence.
3. **Decode/TBT distinction:** the current test does show recurrent Decode
   collective delay feeding token ITL in FlowSim, while Nuska's reviewed
   formulation targets TTFT and prefill multi-stage communication. This is a
   possible workload/metric distinction, not yet a technical contribution.
4. **Multi-NIC scope:** FuseLink is direct prior art for multiple GPU ranks
   and NIC rails. This experiment does not implement or outperform it.
5. **Hardware realization:** FlowSim strict class allocation cannot support
   claims about RDMA QP order or physical switch queue priority. STORM,
   pFabric, PIAS and PDQ make both the prior-art and packet-realization burden
   explicit.

## Novelty decision

**Novelty gate: NOT PASSED for a new fine-grained network scheduler.** The
current results validate a controlled class-level resource-sharing effect,
but EP_FIRST nearly captures the observed serving benefit. No same-class
urgency oracle, deployable queue mapping, exact EP routing, or packet-level
validation demonstrates a nontrivial technical delta from the closest prior
work.

The arXiv v2 record identifies the latest Nuska revision/title/date and
describes P2D/collective multi-stage scope; the full HTML was reviewed. It
does not list a conference venue as of this audit. Do not refer to MFS and
Nuska as separate papers.

## Coverage boundary

This is a bounded nearest-work audit, not an exhaustive novelty search. The
primary records linked above establish formal venue/status for Nuska's arXiv
version, STORM, FuseLink, SwiftRDMA, pFabric, Varys, PDQ, PIAS, QCLIMB,
CommBench and Libra. FLASH and VarioPath are treated as arXiv preprints where
the primary records reviewed did not establish a proceedings venue. NCCL PXN
is an implementation feature, not an academic publication. The ambiguous
“FAST” label is retained as an attribution caveat rather than silently
equated with FLASH.
