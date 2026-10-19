# Prior-work overlap and novelty gate

This is a targeted overlap check, not a systematic 2012–2026 survey. The conclusion is deliberately conservative: request-grouped completion of P2D KV is a direct application of classic coflow/flow scheduling, and the broader Serving-stage/request urgency space overlaps with Nuska/MFS.

| Work | Verified source/status | Overlap with this candidate | Consequence |
|---|---|---|---|
| Nuska: Stage-Aware Communication Scheduling for Disaggregated LLM Serving (earlier MFS version) | [arXiv v2 full text](https://arxiv.org/html/2603.17456v2); formal proceedings status not verified in the local audit | Multi-stage P/D and KV communication, request/batch urgency, intra-/inter-request contention, LLF approximation, dependency-aware flow promotion, finite DSCP classes, TTFT-SLO objective | A generic request/slack-aware network scheduler is not novel. Recurrent Decode/TBT may be a scope distinction, but this experiment does not exercise concurrent Decode EP and has no policy headroom. |
| Varys | [SIGCOMM 2014 program/paper](https://conferences.sigcomm.org/sigcomm/2014/program.php) | Coflow completion-time scheduling | Grouping all required KV shards by request is directly within coflow reasoning; cannot claim the abstraction itself. |
| Aalo | [SIGCOMM 2015 paper](https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p393.pdf) | Non-clairvoyant coflows, finite priority queues, starvation handling | Finite queues and coflow ordering are established; the simple FIFO/coflow baseline has no distinctive algorithmic novelty here. |
| STORM | [SIGCOMM 2026 program](https://conferences.sigcomm.org/sigcomm/2026/program/papers/) | NIC-level scheduling with RDMA request sizes, QP backlog, near-completion/dependency prioritization, finite priority resources | Very close contemporary baseline for fine-grained RDMA scheduling. A new claim must show a Serving-specific decision that does not reduce to request/coflow completion or dependency priority. |
| Libra | [USENIX NSDI 2026](https://www.usenix.org/conference/nsdi26/presentation/ruan-libra) | Disaggregated serving request partitioning, scheduling, chunked KV transfer | Relevant system context, but not evidence that the particular shared-link arbitration question is solved or novel by itself. |
| MegaScale-Infer | [SIGCOMM 2025 paper PDF](https://chaojin0310.github.io/files/papers/SIGCOMM25-MegaScale-Infer.pdf) | Disaggregated expert parallelism and communication/compute overlap | Relevant MoE serving and communication baseline; not a new KV request-coflow scheduler. |
| DeepEP | [Official implementation](https://github.com/deepseek-ai/DeepEP) | MoE dispatch/combine communication library and kernels | Defines practical EP communication behavior; does not make generic priority/coflow scheduling novel. |

## Candidate-specific conclusion

The experiment establishes only that a later full-request handoff can inherit shared-link service delay and that a two-request grouping oracle can improve one request at the expense of its peer. With actual releases the maximum does not move, and the grouped/FIFO/SRPT/coflow variants coincide. The request-level completion objective is not a technical distinction from coflow scheduling. No algorithm should be implemented based on this evidence.

The related-work claim is therefore **NO-GO** for a new scheduler on this mechanism. This does not prove all Serving-aware network scheduling is solved; it says this specific measured gap does not distinguish itself from classic request/coflow scheduling or Nuska/STORM.
