# ns-3 Validation Status

Status: `NOT_RUN`.

This study's serving and cache results come from integrated FlowSim only. No native ns-3 packet replay was run for the A0/A1/A2 or B1/B2 event sets. Consequently this report makes no claim about packet serialization, ECMP hash selection, physical packet queues, ECN marks, CNP, DCQCN rate evolution, PFC, ACK completion, or packet-level last-shard completion.

The existing packet-result folders under `research_prefix_exposure/packet_results/` are historical network replay artifacts from a separate study. They are not reused as the packet validation for the current cache-handoff or 3P2D configurations.

No `PACKET_NETWORK_CONFIRMED` or `NS3_INTEGRATED_TTFT_CONFIRMED` status is assigned. The latter would in any case require a demonstrated packet-completion callback into the Serving scheduler; fixed issue-time packet replay alone cannot validate integrated TTFT.

The correct next condition for packet validation would be a serving-level mechanism that first clears the project's preregistered threshold and has a well-defined same-request event export. Neither A nor B did so here, so spending packet-simulation cost would not answer the current GO/NO-GO question.
