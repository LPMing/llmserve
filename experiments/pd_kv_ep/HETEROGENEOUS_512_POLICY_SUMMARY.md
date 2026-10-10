HETEROGENEOUS 512 POLICY SUMMARY
===============================

Scope
-----

This is a completed FlowSim network-only replay on S16/EP64/8P8D/200-Gbps
with 512 requests: 256 active Decode requests and 256 new P2D requests. The
P2D destination geometry is spread; the policy runs are FAIR, EP_FIRST and
KV_FIRST. P2D and EP bytes are model-derived for Qwen3-30B-A3B; there is no
synthetic byte override. FlowSim queue values are residual analytical fluid
backlog, not packet-buffer occupancy. These files do not provide integrated
scheduler TTFT/TBT.

Workload accounting
--------------------

| profile | small P2D | large P2D | small input | large input | small KV/request | large KV/request |
|---|---:|---:|---:|---:|---:|---:|
| small-majority | 205 | 51 | 2048 | 8192 | 201,326,592 B | 805,306,368 B |
| mixed | 128 | 128 | 2048 | 8192 | 201,326,592 B | 805,306,368 B |
| large-majority | 51 | 205 | 2048 | 8192 | 201,326,592 B | 805,306,368 B |

The 256 Decode requests have input length 128, output length 64 and do not
emit P2D. All 256 P2D requests arrive in the same 20-ms-offset workload used
by the existing replay. The request-level KV metric is the handoff barrier:
last required KV flow completion minus first requested KV flow start; it is not
the sum of individual flow delays. EP metrics below are collective-level CCT:
last EP flow completion minus collective requested start.

Spread policy results
---------------------

All values are milliseconds. KV all is over the 256 P2D requests. KV small and
KV large are class-conditioned request-level distributions. EP is over 49
Decode EP collectives, not per-flow latency.

| profile / policy | KV all mean | KV all P99 | KV small mean | KV small P99 | KV large mean | KV large P99 | EP mean | EP P99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| small-majority / FAIR | 42.840 | 144.465 | 31.620 | 72.062 | 144.262 | 144.465 | 1.313 | 3.683 |
| small-majority / EP_FIRST | 43.042 | 144.465 | 31.844 | 72.075 | 144.262 | 144.465 | 0.677 | 1.027 |
| small-majority / KV_FIRST | 39.368 | 144.465 | 27.764 | 62.652 | 144.262 | 144.465 | 25.413 | 106.340 |
| mixed / FAIR | 62.853 | 183.276 | 22.712 | 68.137 | 183.276 | 183.276 | 1.699 | 2.852 |
| mixed / EP_FIRST | 62.855 | 183.276 | 22.715 | 68.145 | 183.276 | 183.276 | 0.677 | 1.027 |
| mixed / KV_FIRST | 55.302 | 159.620 | 20.529 | 61.588 | 159.620 | 159.620 | 66.823 | 176.159 |
| large-majority / FAIR | 106.760 | 258.345 | 11.381 | 68.761 | 249.595 | 258.345 | 3.174 | 4.978 |
| large-majority / EP_FIRST | 106.526 | 258.422 | 11.387 | 68.881 | 249.001 | 258.422 | 0.677 | 1.027 |
| large-majority / KV_FIRST | 93.991 | 228.617 | 10.351 | 62.546 | 219.248 | 228.617 | 132.734 | 252.511 |

Interpretation
--------------

1. The prior identical KV mean/P99 problem came from homogeneous request
   populations. The three profiles now produce a genuine request-level KV
   distribution. The large class is the P99 driver because its model-derived
   KV is exactly 4x the small class.
2. EP_FIRST reduces EP P99 to the no-contention floor in all three profiles,
   while changing all-KV mean by -0.22% to +0.47% and all-KV P99 by at most
   +0.03% relative to FAIR. In this spread/aggregate FlowSim operating point,
   there is no evidence that EP_FIRST materially harms the KV handoff.
3. KV_FIRST improves all-KV mean by about 8.1% (small-majority), 12.0%
   (mixed), and 12.0% (large-majority), but makes EP P99 approximately
   28.9x, 61.8x and 50.7x the corresponding FAIR value. The KV benefit does
   not compensate for the EP collective-tail cost under this workload.
4. This is a real heterogeneity result, but it does not establish a
   policy-crossover or a serving-level CCF-A motivation. No TTFT/TBT/SLO
   conclusion may be inferred until an integrated serving replay with the
   same heterogeneous request set completes.
5. The natural next mechanism question is not “make one KV larger”. It is
   whether the large-KV tail can be reduced by request-level P2D admission or
   coflow shaping while preserving EP barriers. That is a new candidate only
   after an integrated TTFT validation; no scheduler is implemented here.

Provenance
----------

- Workloads: experiments/pd_kv_ep/workloads/autonomous/ep64_512_heterogeneous_*.jsonl
- Manifests: corresponding *.manifest.json files in the same directory
- Results: experiments/pd_kv_ep/results/heterogeneous_kv_s16_512/{small_majority,mixed,large_majority}/{fair,ep_first,kv_first}/
- Existing fan-in16 files are separate concentration controls and are not
  mixed into the spread table above.
