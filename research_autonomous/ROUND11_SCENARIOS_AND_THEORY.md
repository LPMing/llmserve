# Round 11: deployment scenarios and theory gates (2026-10-15)

The new research brief requires theory and a small causal experiment before a
full production-trace replay. `RESEARCH_LOG.md` records the sequential decision.
The SwissAI file was downloaded before that instruction arrived and is archived
with a verified local digest. It is **not** mined or replayed in this round.

## Evidence and deployment anchors

- **MEASURED:** local RTX PRO 6000 Blackwell Server Edition, Qwen3-32B BF16
  TP1/TP2 profile; per-category CSVs and the model config are checked in.
  GPU kernel timings are single-GPU TP-shape emulation, not multi-GPU transport
  measurements.
- **SOURCE:** [NVIDIA's RTX PRO reference architecture](https://docs.nvidia.com/enterprise-reference-architectures/white-paper/latest/reference-architectures-deep-dive.html)
  includes 8-GPU/5-adapter and smaller 4-GPU/3-adapter or 2-GPU/3-adapter
  designs. [DGX H100](https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/nvidia-dgx-h100-datasheet.pdf)
  instead has eight 400-Gbps compute adapters for eight GPUs. A universal
  8-GPU/one-NIC assumption would be incorrect.
- **SOURCE:** [Dynamo's disaggregated serving guide](https://docs.dynamo.nvidia.com/dynamo/user-guides/disaggregated-serving)
  distinguishes local NVLink KV transfers from multi-node RDMA. Its
  [architecture guide](https://docs.dynamo.nvidia.com/dynamo/dev/knowledge-base/concepts/system-architecture/disaggregated-serving)
  describes KV-aware routing and nonblocking NIXL transfer. These are strong
  baseline capabilities, not contributions of this study.
- **SOURCE:** [UBELIX GPU-node inventory](https://hpc-unibe-ch.github.io/hardware/gpu/)
  lists eight RTX 4090 GPUs per node and one 100-Gbps InfiniBand interface.
  This is a real GPU:NIC hardware ratio, but the inventory does not assert
  that its nodes run P/D LLM serving.
- **ASSUMED:** 200-Gbps directed rails and rank mapping in the repository's
  `4p1d_unique_spines` fixture; a 2,048-token prompt and 600-token output
  represent a controlled text-generation request. The 3-token output is a
  short-output diagnostic only. No actual deployment or workload frequency is
  inferred from those assumptions.

## Scenario bank

`P/D` are GPU instances, each with the stated TP/PP layout. The matrix is a
set of falsifiable deployment cases, not 15 observed production clusters.
Unspecified links are local to a node; all cross-node rails are 200 Gbps
unless a row says otherwise. `I/O` are prompt/output tokens. The topology
and request shape in each row are explicit assumptions unless cited above.

| ID | Model, GPU/node, physical cut | P:D and parallelism | I/O and question | Gate |
|---|---|---|---|---|
| S01 | Qwen3-32B, RTX PRO 6000, 2 GPU/node, two receiver rails | 1:1, TP2/PP1 | 2048/600; does one cold KV transfer expose network wait? | Theory + small experiment |
| S02 | Same hardware, four source nodes and one destination node | 4:1, TP2/PP1 | 2048/3 simultaneous; shared-receiver layerwise cut | Theory + small experiment; diagnostic burst |
| S03 | Same, two Decode nodes with two rails each | 4:2, TP2/PP1 | 2048/3; incremental receiver placement over load-updating greedy | Prior 3:2 gate NO-GO; no new gate without headroom |
| S04 | Same, one P node and one D node | 1:1, TP2/PP1 | 2048/600 at sustained arrivals; Decode slot and KV backpressure | Theory; simulator unsupported at KV exhaustion |
| S05 | Same, one P node and two D nodes | 1:2, TP2/PP1 | 2048/600; properly provisioned control for S04 | Strong-provisioning comparator |
| S06 | Qwen3-32B, RTX PRO 6000, 1 P GPU and 2 D GPUs on separate nodes | 1:1, TP1→TP2 | 2048/600; KV re-shard over source NIC | Theory screen |
| S07 | Same, 2 P GPUs and 1 D GPU | 1:1, TP2→TP1 | 2048/600; destination memory and batch-size penalty | Theory screen |
| S08 | Qwen3-30B-A3B, RTX PRO 6000, two rails/node | 4:1, TP2/PP2/EP1 | 2048/3; PP-stage KV coflow | Matched prior experiment NO-GO |
| S09 | Same MoE model and NICs | 3:2, TP2/PP1/EP1 | 2048/3; receiver choice over greedy | Matched prior experiment NO-GO |
| S10 | Same MoE, 4 GPU/node and shared NICs | 2:2, TP2/EP4 | 1024/600; P2D versus Decode A2A | Needs genuine expert routes and profiled EP range |
| S11 | Same MoE, four branches from one agent parent | 1:4, TP2 | 2048/64 per child; prefix replica degree | Symmetric strong-envelope bound NO-GO |
| S12 | Same MoE, GPU plus CXL tier | 1:1, TP2 | 4096/64 multi-turn; remote prefix prefetch | Missing timed lower-tier load and observed misses |
| S13 | Qwen3-32B, RTX PRO 6000, two nodes with one TP rank each | Decode TP2 cross-node | 2048/600, batch 128; TP AllReduce shares P2D cut | Theory; local TP placement is stronger baseline |
| S14 | Qwen3-32B, RTX PRO 6000, 8 GPU/5 adapters per node | 4:4, TP2 | 2048/600; aggregate NIC pressure under a reference GPU:NIC ratio | Theory; physical GPU→NIC map required |
| S15 | Llama-3.1-8B, RTX 4090, 8 GPU/one 100-Gbps NIC per node | 2 P GPUs on one node, 8 D GPUs on another, TP1; remaining source GPUs unspecified | 2048/64; 1984-token source-prefix hit with a conditional cold Decode | Theory ready; Decode miss, GPU allocation and placement evidence needed |

The DGX H100 8-GPU/8-compute-adapter design above is a counterexample to
blanket shared-NIC claims. S10/S12/S15 cannot be promoted with the current
simulator evidence.

## Quantitative gates

The executable calculations for S01/S02/S04/S06/S07/S13 are in
`theory/round11_qwen32b.py` and its JSON output. S15 is screened in
`theory/round11_rtx4090_100g.py` and its JSON. S08/S09/S11 are backed by
earlier round artifacts in `RESEARCH_LOG.md`.

### Gate A: layerwise receiver cut, S01/S02/S06

Qwen3-32B has 64 layers, 8 KV heads, head dimension 128 and BF16 KV:

`KV/request = 2048 × 64 × 2 × 8 × 128 × 2 = 536,870,912 B`.

TP2 sends `4,194,304 B/layer/rail`. At 200 Gbps, one layer takes at least
`167.772 µs/rail` to serialize. The measured TP2 Prefill block takes
`2,875.951 µs` excluding TP collectives. Under the synchronized ideal-fluid
cut model, at least `floor(2875.951/167.772)+1 = 18` simultaneous identical
source streams must share *one receiver rail* before one layer's service
exceeds the computation interval. Four streams require `671.089 µs`; the
per-layer residual serialization lower bound is zero. This is a **threshold
screen**, not a proof that all network overhead vanishes. The falsifiable
prediction is that 1P1D and 4P1D have equal P2D-ready time while individual
FCT grows.

TP1→TP2 (S06) doubles source rail payload per layer, but measured TP1 block
compute also rises to `5,696.479 µs`: the corresponding threshold is again
about 17–18 sources per source rail. An unequal TP layout is not, by itself,
a network-critical-path proof. Any re-shard study must additionally validate
the exact rank-to-rank byte map.

### Gate B: Decode memory/backpressure, S04/S05/S07

The simulator's TP2 Qwen3-32B weight is `30.513 GiB/rank`; at 96 GiB/rank
and 0.9 memory utilization it allocates `457,824` KV tokens/rank. The
128-sequence slot cap at `2048+600` tokens uses `338,944` of those tokens,
leaving room for about 58 waiting handoffs of 2048 tokens. At 128 active
sequences, the KV pool becomes limiting once output length exceeds about
`1,529` tokens, before accounting for activation and CUDA memory. A TP1
replica has only `103,936` KV-token capacity and holds at most 39 such
2048+600-token sequences; TP2's capacity permits 172 but the configured
sequence cap is 128.

At batch 128 and KV length 2048, the profiled TP2 Decode step is `53.524 ms`
*excluding TP collectives*, an optimistic `2,391` tokens/s or `3.986`
600-token requests/s. One Prefill TP2 instance's compute-only 2048-token
floor is `184.647 ms`, an optimistic `5.416` requests/s. A sustained 1P1D
layout may therefore accumulate a Decode queue; a 1P2D layout can absorb
that assumed rate. This comparison shows why a tuned P:D ratio is mandatory.
It does **not** prove a novel network scheduling opportunity.

`Scheduler.add_decode` currently allocates received KV immediately, even
for a request waiting on the sequence cap, and raises when the Decode KV pool
is full. `Scheduler.add_done` has already freed the Prefill copy. Thus the
simulator cannot represent source retention, receiver rejection or bounded
staging under S04 exhaustion. This candidate is `SIMULATOR_UNSUPPORTED` for
an end-to-end backpressure claim. [Dynamo's request rejection design](https://docs.dynamo.nvidia.com/dynamo/dev/knowledge-base/concepts/fault-tolerance/request-rejection-architecture)
already tracks Decode blocks and can reject overload; the recent
[dual-memory scheduling paper](https://arxiv.org/abs/2610.15579) directly
studies P/D memory admission. A new paper needs a distinct network-dependent
mechanism and a demonstrated increment over these.

### Gate C: cross-node Decode TP, S13

For batch 128, two allreduces per layer and hidden size 5120 give one rank
`2 × 64 × 128 × 5120 × 2 = 167,772,160 B` of TP payload per Decode step.
At 200 Gbps its one-rank serialization floor is `6.711 ms`; the measured
compute-only Decode step is `53.524 ms`. In a strictly serial compute-plus-cut
toy model, ideal removal is `6.711/(53.524+6.711)=11.14%`. This is a
**conditional analytical bound**, not a simulated or deployable improvement:
intra-node TP avoids that NIC cut, overlap can reduce exposure, and an
algorithm cannot delete mathematically required collectives. The scenario
needs evidence that cross-node TP is unavoidable under a strong local-placement
baseline before any motivation experiment is justified.

### Gate D: multi-Decode prefix replicas, S11

The prior exact symmetric four-child enumeration found at most 1.18% gain
over the stronger all-one/equal-four envelope with full Prefill, or 3.45%
under a prefix-hit proxy. The theoretical 18.66% against all-one alone was
a weak-baseline artifact. This remains `NO_GO` absent a model-matched,
heterogeneous fork trace that changes the bound.

### Gate E: 8×4090/one-100-Gbps NIC with prefix hits, S15

With the measured RTX 4090/Llama-3.1-8B BF16 TP1 profile, a 2048-token
prompt creates `268,435,456 B` of KV, or `8,388,608 B/layer`. One 100-Gbps
NIC serializes a layer in `671.089 µs`. A cold 2048-token Prefill block takes
`5995.177 µs`; even eight fully cold, synchronous source GPUs need less
per-layer NIC service than their block-compute interval. This hardware ratio
alone therefore does **not** establish a bottleneck.

If 1984 prompt tokens are cached at Prefill and only 64 are computed, the
profiled block becomes `614.049 µs`; a *full* P/D layer payload now takes
longer than the block even for one sender. Two senders sharing the same NIC
have `1342.177 µs` of layer serialization, or `728.128 µs` beyond one block
in a synchronized fluid model. Repeating that residual over 32 layers gives
a **conditional 23.300-ms toy estimate**, not a measured or achievable
Serving gain. It is falsified if the paired Decode already holds that prefix,
if local P/D placement avoids the NIC, if sends do not overlap in time, or if
the effective NIC cut differs from the inventory. The current default
simulator sends the full KV even when Decode is hot; a fair strong baseline
must first query and pin destination blocks, suppressing resident-prefix
bytes. There is also a resource-ratio confound: one RTX 4090 Decode at
batch 16 and 2048-token KV has an optimistic profiled rate of about 714
tokens/s, or 11.2 requests/s for 64-token outputs. Two high-hit Prefill GPUs
could offer far more than that, so the 2P:1D toy cut is not a balanced
steady-state serving system. A matched study must provision enough Decode
GPUs and compare local P/D pairing before calling the NIC delay avoidable.
The 2P:8D row is only a candidate capacity shape, not a documented UBELIX
serving deployment; the six other source-node GPUs and their NIC usage are
unobserved. It is not an experimental motivation until the role placement
and cache states are evidenced.
The earlier Qwen MoE prefix-hit/DELTA study showed a real barrier
in one controlled cohort but only 2.59% full-session gain in its final
comparison. S15 is `THEORY_READY / NEED_CACHE_AND_PLACEMENT_EVIDENCE`; no
new paper mechanism is claimed merely from the 100-Gbps threshold.

## Small causal result and next decision

S01/S02 used only 1 or 4 simultaneous requests. Full per-request CSVs,
flow telemetry, logs, config and hashes are under
`experiments/qwen32b_layerwise_gate/`. The 4P1D case conserves exactly
`536,870,912 B/request`; 512 P2D flows total 2,147,483,648 B, split evenly
between the two receiver rails. Maximum flow FCT rises from 0.188 ms to
0.691 ms, but the last flow finishes at 182.454 ms and the P2D-ready barrier
is 184.907 ms in both cases. Modeled token 2 shifts from 210.039 to 210.545
ms as the Decode batch grows. Thus the prediction survives the small test;
the 0.506-ms token-2 difference is not a network-exposure result.

**Decision:** `NO_GO` for layerwise KV receiver-cut scheduling in the tested
Qwen3-32B/200-Gbps 1–4-source envelope. Do not force 18 sources onto one
Decode to manufacture a positive result. S04 remains `SIMULATOR_UNSUPPORTED`
and faces strong prior work. S13 is `NEED_DEPLOYMENT_EVIDENCE`. No direction
is promoted to `MOTIVATION_VALIDATED` in Round 11.
