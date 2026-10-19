# Network capacity and model-derived demand

## Model and topology

Model config: `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json`; 48 layers, 4 KV heads, head dimension 128, BF16 (2 bytes), 128 experts/top-k 8. KV bytes per prompt token are `48 × 2(K,V) × 4 × 128 × 2 = 98,304 B`. TP=1 in this reduced workload, so there is one layer shard per request.

Physical testbed: one Prefill server and two Decode servers, eight GPUs/server, two 200-Gbps NIC rails/server, four GPU endpoints mapped to each NIC rail; one ToR. The active Prefill sources 0–3 share rail endpoint 24 (200 Gbps); target Decode rank 8 is attached through rail 26. Candidate KV path is `0 -> 24 -> 30 -> 26 -> 8`. Decode EP paths from the other server share the directed ToR-to-D0 segment `30 -> 26` (and then the rank-facing access segment where applicable). The shared 200-Gbps directed cut is real in the configured FlowSim graph. Server aggregate is 400 Gbps; **50 Gbps/GPU is only the arithmetic average of four GPUs sharing one 200G rail**, not a per-GPU rate cap. The JSON `link_bw=50` is an ASTRA fallback and is not the FlowSim path capacity.

FlowSim performs directed fluid max-min sharing. Its `fluid_outstanding_bytes` is analytical residual work, not a packet switch queue, ECN, PFC, or drop counter.

## KV size and isolated serialization floor

| Prompt tokens | Total KV/request | Per-layer KV | 200G solo per-layer serialization |
|---:|---:|---:|---:|
| 128 | 12,582,912 B (12 MiB) | 262,144 B | 10.486 µs |
| 512 | 50,331,648 B (48 MiB) | 1,048,576 B | 41.943 µs |
| 1,024 | 100,663,296 B (96 MiB) | 2,097,152 B | 83.886 µs |
| 2,048 | 201,326,592 B (192 MiB) | 4,194,304 B | 167.772 µs |
| 4,096 | 402,653,184 B (384 MiB) | 8,388,608 B | 335.544 µs |

The full-request total is not one simultaneous P2D message in LAYERWISE mode. There are 48 per-layer releases; in the 2,048-token workload, each layer emits 4 MiB/request.

## Synchronized same-size flows on one shared 200G cut

For N equal flows of size B released together on one cut of capacity C, ideal max-min sharing gives completion `N·B/C`; relative to one isolated flow the additional target FCT is `(N−1)·B/C`. At 4 MiB/layer this is 167.772 µs per flow-equivalent.

| Concurrent same-layer requests N | Aggregate bytes/layer | Group completion | Target extra vs solo |
|---:|---:|---:|---:|
| 1 | 4 MiB | 0.167772ms | 0 |
| 2 | 8 MiB | 0.335544ms | 0.167772ms |
| 3 | 12 MiB | 0.503316ms | 0.335544ms |
| 4 | 16 MiB | 0.671089ms | 0.503316ms |
| 7 | 28 MiB | 1.174405ms | 1.006632ms |
| 8 | 32 MiB | 1.342177ms | 1.174405ms |
| 9 | 36 MiB | 1.509949ms | 1.342177ms |
| 11 | 44 MiB | 1.845493ms | 1.677722ms |
| 18 | 72 MiB | 3.019898ms | 2.852126ms |
| 19 | 76 MiB | 3.187670ms | 3.019898ms |

These are synchronized one-layer lower-bound calculations, not end-to-end predictions. The planned test population is capped at one target plus three interferers (N=4); higher N rows show the theoretical scale only and were not run. Crucially, to compare against the measured E3a N=4 state, an additional `1.165711ms` beyond N=4 is required just to expose `P2D_READY`, so ideal N=11 is first to do so. The observed next batch decision is `2.422703ms` after the E3a last KV finish; ideal N=19 is first to cross it. In this configuration N=19 is outside the physically active one-graph-per-rank envelope: only four Prefill ranks can concurrently generate these full 2,048-token layer streams, and the 2,048-token batch budget lets each carry one such request per graph. It is a threshold calculation, not a recommended or executed workload.

## Measured temporal demand

For four 2,048-token KV requests, measured `qkv_proj` layer-completion/release interval is exactly1.542ms for all47 adjacent intervals. The first-to-last release span is72.474ms. Four-request average KV demand over this span is about11.11GB/s (44.4% of a25GB/s rail), while individual synchronized layer bursts saturate the shared cut. The four requests deliver805,306,368 B total. R1 input2048 takes74.468ms from Prefill graph start54.349ms to graph finish128.817ms (effective27.5k input tokens/s on that instance); this is an observed profile-driven execution interval, not a universal hardware throughput claim. R1's critical last KV finishes127.654649ms in the shared run.

The measured Decode batch-8 interval at the target lane is about 8.431ms while the six-sequence R0 batch runs. The first batch containing R1 is longer: Batch 9 executes for 9.382712ms in the isolated run and 9.382712ms in the four-KV FAIR run (the FAIR execution start is later by 154.519µs). This distinction matters: the user-facing first-token-to-second-token interval includes the wait to the first eligible Decode decision as well as the selected batch execution.

The actual EP4 AG/RS path generated18,432 peer flows /97,320,960 B in the four-KV FAIR run. There are1,536 collective completions; each collective expands to12 peer flows and63,360 total peer-flow bytes. The16 old-request Decode iterations account for96 collectives and6,082,560 EP bytes each. This is the current model/profile-derived simulator realization, not strict GateRouter A2A routing. Summed over the iteration interval it averages about0.72GB/s; its relevant effect is burst/barrier timing, not rail-saturating mean bandwidth.
