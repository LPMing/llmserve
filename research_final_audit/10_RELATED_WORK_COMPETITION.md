# 10 — Related-work competition (status checked 2026-10-13)

This is a focused overlap audit, not an exhaustive bibliography. “Formal” below
means the cited venue/source was directly checked; arXiv-only work is labeled a
preprint and is not represented as peer-reviewed publication.

| Work | Status / source | Scheduling or systems unit | Direct overlap and implication |
|---|---|---|---|
| **Nuska: Stage-Aware Communication Scheduling for Disaggregated LLM Serving** (MFS lineage) | arXiv preprint, v2 title/version at [arXiv:2603.17456](https://arxiv.org/abs/2603.17456) | Multi-stage serving communication; inter-/intra-request contention; laxity-inspired defer/promote and multi-level queue scheduling; TTFT-SLO focus | Strong direct overlap with KV/EP stage/class priority. It is one paper lineage, not separate MFS and Nuska publications. Complete implementation was not reproduced here. |
| **FAST: Fast and Efficient All-to-All Communication for MoE Models** | NSDI 2026, official [paper PDF](https://www.usenix.org/system/files/nsdi26-lei-yiran.pdf) and [presentation page](https://www.usenix.org/conference/nsdi26/presentation/lei-yiran) | Skewed All-to-All-v collective execution, imbalance/incast and collective completion; scale-up rebalancing and scale-out transfer scheduling | Strong overlap with generic sparse-A2A geometry/straggler claims. The full paper was checked; it does not present itself as PD serving or Decode/TBT scheduling. A new claim must be specifically serving-barrier/PD coupled, not just “route geometry changes CCT.” |
| **SwiftEP** | NSDI 2026, official [USENIX presentation page](https://www.usenix.org/conference/nsdi26/presentation/li-xingyi) | MoE inference All-to-All communication execution and buffer/data movement optimization | Strong MoE inference collective incumbent. A network-level proposal must isolate a gap beyond faster/less-overhead A2A execution. |
| **Expert-Locality-Aware Decode Routing for PD-Disaggregated MoE Serving (ELDR)** | arXiv preprint [arXiv:2607.00466](https://arxiv.org/abs/2607.00466) | Decode request routing using expert-locality/signature information | Overlaps Decode placement/locality and TPOT motivation. It does not by itself establish per-link barrier scheduling, but makes generic “expert-aware placement helps” insufficient novelty. |
| **Incast-Free MoE Rate-Based Scheduling** | arXiv preprint [arXiv:2607.26340](https://arxiv.org/abs/2607.26340) | Rate-based MoE communication scheduling to control incast/CCT | Directly overlaps generic MoE incast-rate scheduling; must compare before claiming a new A2A flow control mechanism. |
| **Cluster Topology-Driven Placement of Experts Reduces Network Traffic in MoE Inference** | arXiv preprint [arXiv:2508.09229](https://arxiv.org/abs/2508.09229) | Topology-aware expert placement | Overlaps a generic route/placement claim. |
| **pFabric / PIAS / PDQ / Varys / Aalo and deadline/coflow scheduling** | Established systems/algorithms; this audit did not rerun or exhaustively bibliographically validate each venue/DOI | Flow priority, size/deadline signals, coflow completion or multi-level arbitration | Any proposal based only on per-flow slack, SJF/EDF/LLF, priority queues, or coflow completion has substantial prior-art overlap. Matched performance comparison was not run. |
| **DistServe / Splitwise / Mooncake** | Established serving/PD/KV systems; not a packet-priority baseline in this audit | Resource disaggregation, prefill/decode placement, KV transfer/reuse and serving architecture | Important semantic/context systems, but not evidence that a new network priority algorithm is novel. |

## Audit limits and review consequence

- FAST is the closest checked formal publication for collective route skew and
  A2A tail; its full paper was inspected, not just its abstract.
- Nuska/MFS is treated as an arXiv preprint lineage as of the audit date. Do not
  call it formally published without a separately verified venue record.
- This audit did not verify a DOI for every classic work and did not implement
  every scheduler. It therefore supports a conservative novelty warning, not a
  claim that any named baseline loses.
- The new candidate has no valid matched serving result. Novelty is moot until
  the routing/collective semantics are repaired and a serving-level opportunity
  exists.

