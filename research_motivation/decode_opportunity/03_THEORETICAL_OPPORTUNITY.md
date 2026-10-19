# 03 — Theoretical completion bounds before multi-request experiments

Status: `OPPORTUNITY_CONDITIONAL`; the one-request correctness topology is not the multi-request contention topology.

## Model-derived workload size

For Qwen3-30B-A3B-Instruct-2507 BF16, per token K+V bytes are:

`48 layers × 2 (K,V) × 4 KV heads × 128 head_dim × 2 bytes = 98,304 B/token`.

For 2,048 tokens this is `201,326,592 B = 192 MiB`. TP2 divides this exactly into two required shards of `100,663,296 B` each. The POST_PREFILL G0 emitted precisely those two shards.

## Measured link/path anchor

The correctness topology uses 200-Gbps physical links and 0.5 μs/link. One 100,663,296-B shard takes `4.02653184 ms` of serialization at 25 GB/s. The observed three-hop route adds 1.5 μs, producing `4.02803184 ms`, matching the measured `4.028032 ms` to timestamp resolution.

The G0's two TP shards take different directed paths (`0→6→7→4`, `1→7→6→5`); they do not both traverse one common directed link. Thus the G0 validates the byte/rank/path model but cannot validate the single-cut request-order hypothesis.

## Necessary shared-cut case

For a legal two-request coflow comparison, each request has two model-derived TP shards, both shard paths must traverse the same 200-Gbps directed cut, and the four physical flow sizes total 402,653,184 B. Under fluid max-min sharing with simultaneous release and equal 100,663,296-B shards:

- FAIR has four equal active flows at the shared cut. Each receives 6.25 GB/s; both request barriers finish at `16.10612736 ms + common path propagation`.
- Request-group-first gives the selected request's two shards 12.5 GB/s each concurrently; its barrier finishes at `8.05306368 ms + propagation`. The other request then finishes at `16.10612736 ms + propagation`.
- Mean request handoff falls from `16.10612736 ms` to `12.07959552 ms` before the common propagation term (25%); makespan and the second request's completion do not improve.
- Reversing the group order swaps which request receives the early completion; total bytes and makespan remain identical.

These are fluid lower-bound calculations, not an experiment result. They assume all four shard flows are independently representable, simultaneous, and share one directed 200-Gbps cut; routing, release slack, collective scheduling, and compute are deliberately excluded.

For Decode-opportunity sensitivity, one independent Decode lane must have a naturally measured next batch opportunity strictly between the early and FAIR completion bounds, while the other lane's opportunity is no earlier than the FAIR bound. If the actual measured opportunities do not satisfy this ordering with margin, the hypothesized serving effect has no theoretical support and we must not phase-scan to manufacture one.

## Predicted serving upper bound

At most one of the two equal requests can cross the early batch boundary under either group-first order. The other completes by the same final makespan as FAIR in this idealization. Therefore a 25% mean handoff bound does **not** imply a 25% TTST, request-completion, or SLO gain. The serving gain may be zero if the earlier request's batch opportunity is absent, hidden by Prefill/Decode compute, or followed by EP work that cancels the advantage.

## Topology condition for the next stage

The initial four-shard/same-cut bound above was a deliberately conservative **candidate topology**, not the topology finally built. It is superseded for the integrated study: under the final valid placement, exactly one shard per target crosses `12->13`; the other shard stays within a leaf. This distinction must not be elided.

## Corrected bound for the final topology

Each target still emits two model-derived 100,663,296-byte shards (201,326,592 B/request total), but only the cross-leaf shard per request competes on `12->13`. At 200 Gbps, one such shard has 4.026532 ms serialization time. With three 0.5-μs hops, the isolated cross-cut FCT is 4.028032 ms, matching the network-only control. Two simultaneous equal cross-cut shards under FAIR each receive 12.5 GB/s and finish at 8.054564 ms. Request-group-first makes the selected request's cross-cut shard finish at 4.028032 ms and the other at 8.054564 ms. Request readiness is the max over both required shards; the local companion shards are included in the request barrier and ledger.

For per-request readiness, this idealized cut-only example changes the pair mean from 8.054564 ms to 6.041298 ms (25%), with unchanged second-request completion/makespan. It is a network-level coflow bound only. In integrated runs, per-request handoff is 8.088567 ms under FAIR and about 4.05 ms for the selected first request, because actual event releases, EP competition and other path work are included.

The revised necessary serving condition was met in one controlled configuration: D0's seed frees its `max_num_seqs=1` Decode slot at 75.585681 ms, while D1 remains occupied until 315.531153 ms. Target P2D starts at 70.877817 ms. When request 3 is selected first, its handoff finishes at 74.927908 ms, before D0's naturally generated next admission opportunity; under FAIR it finishes at 78.966384 ms, after that opportunity. Request 2 maps to D1 and cannot enter until the much later D1 completion. These times came from event logs, not a hardcoded scheduler timestamp.

This creates a conditional opportunity but not a broad theory result: if target KV becomes ready after its Decode lane is free, earlier handoff can translate nearly directly to a second-token timing change; if the lane remains occupied past both policies' readiness, the network gain is absorbed by Decode capacity wait. Output-length neighbor checks in `04_DECODE_OPPORTUNITY_CALIBRATION.md` demonstrate both sides of this boundary.
