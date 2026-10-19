# 09 — Failure analysis and novelty de-duplication

## Mission failure modes

| ID | Status | Evidence / interpretation |
|---|---|---|
| F1 TP-rank skew | Resolved for selected setup | The earlier TP2/EP1 51.216-ms release skew was compute/rank mapping, not congestion. Corrected TP2/EP2 source ranks are symmetric; see 01. |
| F2 four shards on common cut | Initial theory assumption superseded | Final topology puts one target shard per request on `12->13`; the companion shard stays within a leaf. Corrected actual bound is in 03 and 03_COMPLETION_BOUNDS.csv. |
| F3 release skew | Not a blocker | Both 2048-token target requests release P2D at 70.877817 ms. |
| F4 independent Decode groups | Passed narrowly | Two independent TP2/EP2 Decode instances with `max_num_seqs=1` are separately scheduled and paired. |
| F5 distinct next opportunities | Passed in the primary controlled case | D0 frees at 75.585681 ms; D1 at 315.531153 ms. Neighbor checks show the benefit disappears when D0 remains busy past both handoff completions. |
| F6 handoff changes Decode batch attribution | Not observed | Request 3 uses batch id 11 under FAIR and the offline opportunity control; start time changes, batch identity does not. |
| F7 network gain fails to serve | Partially falsified, but limited | The modeled second-token/request-completion event moves 3.381 ms earlier for request 3; pair mean improves 0.85%, global makespan ~0.014%. The simulator's reported TTST moves the opposite way and is semantically ambiguous for this architecture. |
| F8 earlier Decode causes EP feedback | Weakly observed | Earlier admission adds ~0.173 MB EP bytes in the target telemetry window; other target KV FCT rises only ~9.4 μs. Not a material feedback result. |
| F9 another request suffers | Small network cost; large capacity asymmetry dominates | Request 2's KV FCT under the opportunity control is +9.382 μs versus FAIR, but its completion is dominated by D1's long seed. Strict KV_FIRST delays one EP collective in each active Decode group and delays the selected target despite earlier KV readiness. |
| F10 classic FIFO/SRPT/Coflow/EDF | Novelty not established | Exact FIFO/SRPT/coflow size tie defaults to request 2 and misses the early D0 slot. A deadline/opportunity-aware baseline could choose request 3; no full EDF/LLF/coflow implementation was run. The oracle advantage over these methods is therefore unproven. |
| F11 metric comparability | Material limitation | Reported TTST and sampler-to-second diagnostic diverge; see 02/08. No target TBT distribution or SLO result. |
| F12 deployment/generalization | Not passed | Controlled 4-request, 2P/2D, TP2/EP2, 200-Gbps FluidSim case; target outputs are 2 tokens; seed phase is narrow; EP is AG/RS rather than sparse high-degree A2A. |
| F13 previous work overlap | High | Per-request coflow completion is classic; Nuska/MFS explicitly schedules multi-stage TTFT flows, cross-request urgency and limited priority queues; STORM schedules RDMA requests using QP backlog/dependency cues; this repo already has Progressive Push and KV handoff work. |

## Existing-work boundary

The latest arXiv v2 (19 Sep 2026) is titled **Nuska: Stage-Aware Communication Scheduling for Disaggregated LLM Serving**; it is the renamed/revised MFS work, not a separate paper. Its formulation includes remote KV reuse, EP/model-parallel collectives and P2D as dependent prefill stages; it explicitly handles intra-request and inter-request contention, request/batch urgency, request-level deadline ordering, finite priority queues, host arbitration plus DSCP, and just-in-time P2D promotion. The paper reports TTFT/SLO evaluation and uses output length one in its testbed so that Decode does not affect TTFT. It does not establish in the reviewed text a dedicated post-P2D Decode-slot opportunity objective or a validated TBT algorithm, but its multi-stage request-urgency machinery is close enough that the present simple “choose request whose Decode lane opens sooner” control cannot be claimed novel without a direct, fair baseline comparison. See the [full arXiv v2](https://arxiv.org/html/2603.17456v2).

Varys and coflow scheduling already group the parallel flows of an application job and optimize coflow completion/deadline objectives; selecting a KV request's required shards as one group is not itself new. See [Varys at SIGCOMM 2014](https://conferences.sigcomm.org/sigcomm/2014/program.php) and the [paper](https://istc-cc.cmu.edu/publications/papers/2014/varys-sigcomm14.pdf).

STORM is a SIGCOMM 2026 NIC-level RDMA scheduler using known request size and per-QP backlog, mapping decisions into a small number of priorities and considering near-complete requests/dependent work. It does not require application dependency hints, so its relation is not identical; nevertheless, “use request/barrier urgency and few queues” is not a clean novelty claim. See the [SIGCOMM 2026 proceedings record](https://doi.org/10.1145/3789240.3829117) and [publication description](https://re.public.polimi.it/handle/11311/1326226).

The repository's [Progressive Push research](../../experiments/pd_kv_ep/PROGRESSIVE_PUSH_RESEARCH.md), [KV handoff history](../kv_handoff/08_FINAL_GO_NO_GO.md), and [group urgency results](../group_urgency/10_FINAL_MOTIVATION_DECISION.md) are also prior art for this project and must not be renamed as new contributions.

## First unmet condition

The first unmet condition for a paper algorithm is **additional headroom beyond established request/deadline/coflow scheduling**. The offline controller is clairvoyant about downstream Decode opportunity, only one local timing regime has a material second-token movement, target TTST is not validated, and no completed classic baseline demonstrates that the gain survives. The right conclusion is not “the opportunity is false”; it is “the mechanism exists in this simulator, but a novel, deployable scheduling contribution is not demonstrated.”
