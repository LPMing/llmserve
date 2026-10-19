# Handoff capacity model and workload provenance

## Workload and model-derived bytes

Model: Qwen/Qwen3-30B-A3B-Instruct-2507, BF16, 48 layers, 4 KV heads, head_dim=128, TP=2. For an input of N tokens:

`B_KV(N) = 2(K,V) × 4 KV heads × 128 × 2 bytes × 48 layers × N`.

At N=2,048, B=201,326,592 bytes (192 MiB), with two TP shards of 100,663,296 bytes (96 MiB) each. These are architecture-derived bytes, not overrides.

## Physical topology and request-to-rail mapping

The saved cluster config has four Prefill TP2 instances and Decode instances on D0/D1. The FlowSim topology gives each server two shared 200-Gbps NIC rails; GPU ranks attach to the NIC at high local capacity. It is not modeled as one independent 200-Gbps NIC per GPU. For the requests in the saved run:

| Requests | Prefill physical GPU ranks | P-side NIC | Decode server/ranks | D-side NIC | Shared directed scale-out bottleneck |
|---|---|---:|---|---:|---|
| 0, 1 | 0–3 | 24 | D0, ranks 8–11 | 26 | 24→30→26, 200 Gbps per directed link |
| 2, 3 | 4–7 | 25 | D0, ranks 12–15 | 27 | 25→30→27, 200 Gbps per directed link |

Each request's two TP shards use the same rail pair; the shards are released at different times in this trace. The four-request placement therefore has two independent 200-Gbps request groups, with two requests per group. The topology is a single ToR; no spine/ECMP claim is involved. The path has 10.2 us modeled propagation in the replay (two 5-us scale-out hops plus two 0.1-us access hops).

## Service lower bounds

At C=200 Gbps=25,000,000,000 B/s:

- One full request on an otherwise idle resource: B/C = 8.05306368 ms; plus modeled path propagation, 8.06326368 ms.
- One TP shard alone: 4.02653184 ms serialization; plus propagation, 4.03673184 ms.
- Two requests simultaneously active on one rail, with one 96-MiB shard from each: max-min FAIR gives each 100 Gbps, so shard completion takes 8.05306368 ms + 10.2 us = 8.06326368 ms.

If two complete equal requests were released simultaneously onto one resource, FAIR completes both at 2B/C + propagation = 16.11632736 ms. A request-grouped work-conserving order completes them at 8.06326368 ms and 16.11632736 ms, mean 12.08979552 ms versus FAIR mean 16.11632736 ms: 24.984% ideal mean handoff reduction after including the fixed propagation term. With four requests across the actual two rails, this two-request result repeats independently on each rail; it is not a four-request single-bottleneck result. Four requests artificially collapsed onto one rail would be a different topology and are not used.

This is only a simultaneous-release network bound. It is not a prediction of TTFT/TTST/TBT. The actual Prefill graph releases the two source-rank shards 51.216 ms apart; therefore the bound must not be substituted for the actual-anchor replay or Serving result.

## Actual-anchor outcome

The corrected integrated flow ledgers show per-request releases at 13.497 ms and 64.713 ms. For the 1-request run, the last shard completes at 68.749732 ms (4.036732 ms after its release). Under four-request FAIR, two same-rail shards are active at each release wave; the last wave completes at 72.776264 ms (8.063264 ms after its release). The long request handoff span includes the 51.216-ms source-rank compute skew; it is not a 59-ms network FCT.

Actual-anchor offline request grouping reduces mean request handoff span from 59.279264 ms to 57.265998 ms (3.396%, n=2 per rail), or mean absolute ready time by 2.013266 ms (2.766% of FAIR mean ready time, n=4). The maximum ready time remains 72.776264 ms. The network replay uses real bytes, route, and release anchors but contains no Serving scheduler, so this reduction is not called TTFT gain.

## Reproduction

The calculator is `calculate_handoff_bounds.py`. Example:

    /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_motivation/kv_handoff/calculate_handoff_bounds.py --output /tmp/handoff_bounds.csv

The committed/working CSV `02_EXPECTED_NETWORK_GAIN.csv` is separately reproduced from `analyze_handoff_replay.py`; that script verifies replay path equality against the integrated ledger. Current environment replay reproduction compared byte-for-byte successfully.
