# Barrier-critical congestion attribution (native ns-3)

Date: 2026-10-08
Scope: 16-request Azure window 16812; Qwen3-30B-A3B; EP32; 8-server 1:1 P:D; 200-Gbps physical links; q0 control, q1 policy-data, q3 ordinary-data. Fixed issue-time replay only.

## Collective and KV completion rules

- An EP collective CCT is `last peer-flow completion - collective start`; a P2P flow's FCT is not called collective CCT.
- Request KV handoff is `last required KV shard completion - first required KV issue`; it is not the sum of shard FCTs.
- A last-peer or last-shard path is called *barrier-critical* only for that observed collective/request in that replay. It is not assumed to be known online.

## Results by policy

There are 5,280 EP collectives. Against EP_ONLY, the absolute marginal EP CCT P99 is +0.525% for FAIR, +0.006% for EP_FIRST, and 9.58x for KV_FIRST. For FULL/FAIR, 550 of 6,126 tied-last-peer rows (8.98%) overlap active KV on at least one same directed link. For EP_FIRST this is 541/6,135 (8.82%); for KV_FIRST 653/6,124 (10.66%). Most collectives are not last-peer direct-overlap events.

In the KV_FIRST worst dispatch examples, the last peer `50→62` traverses `50→76→83→79→62`; it directly overlaps several KV flows on directed links 125 and 175. For example, collective 70005602 has CCT 1,657.817 µs versus 21.899 µs in EP_ONLY, with the final 4-KiB peer flow delayed by 1,635.918 µs and 10 contemporaneous KV flows on shared directed links. This is concrete evidence that policy-selected KV can delay an EP barrier-critical peer on a shared path.

However, some of the largest combine outliers (including collectives 70005643 and 70005763) have no observed contemporaneous KV flow on the final peer's same directed path. Their delay may reflect earlier collective/queue state, cross-direction/shared switch behavior, retransmission/transport effects, or a telemetry blind spot; current data does not disambiguate these causes. Therefore the entire KV_FIRST P99 cannot be attributed to direct same-directed-link P2D overlap yet.

## Interpretation and limitations

The route-overlap evidence supports a mechanism for selected critical peers, but the tail attribution is incomplete. A next packet-level diagnostic should inspect all peers and switch queue/service timeline for the identified combine outliers, including queue occupancy at each hop, ACK/CNP events, retransmissions, and earlier flows sharing the relevant egress. Do not label unexplained events as P2D-induced.

There is no ns-3 serving feedback in this replay, so the evidence stops at collective CCT. Any TBT or TTFT claim must come from a separate integrated simulator that consumes packet completion events, not from multiplying CCT deltas by token count.

Compact data: [`ep_collective_policy_attribution.csv`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_analysis/ep_policy_attribution/ep_collective_policy_attribution.csv), [`ep_collective_policy_summary.json`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_analysis/ep_policy_attribution/ep_collective_policy_summary.json), and [`matched_control_summary.json`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_analysis/matched_controls/matched_control_summary.json).
