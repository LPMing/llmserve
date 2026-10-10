# Minimal 1P2D / EP16 topology audit

Status: topology and endpoint semantics audited; this is not a performance result.

## Intended physical cluster

| Server | GPUs | Scale-out NICs | GPU-to-NIC mapping |
|---|---:|---:|---|
| P0 | 8 | 2 × 200 Gbps | G0–G3 → NIC0; G4–G7 → NIC1 |
| D0 | 8 | 2 × 200 Gbps | G0–G3 → NIC0; G4–G7 → NIC1 |
| D1 | 8 | 2 × 200 Gbps | G0–G3 → NIC0; G4–G7 → NIC1 |

The 50 Gbps/GPU value is only the server aggregate divided by eight; GPUs do
not own independent 50-Gbps scale-out links. Each NIC uplink remains a separate
200-Gbps resource. GPU↔NIC and the two local NIC rails are represented as
7200-Gbps intra-server links to keep those local paths out of the ToR fabric;
this is an explicit fast-local approximation, not a claim about a particular
NVSwitch SKU.

## Serving-rank and physical-endpoint correspondence

The authoritative test mode is `--pd-kv-receiver-mode ACTUAL`:

| Serving instance IDs | Role/server | ASTRA GPU-rank IDs | TP |
|---|---|---|---:|
| 0–7 | Prefill / P0 | 0–7 | 1 |
| 8–11 | Decode / D0 | 8–15, two contiguous ranks per instance | 2 |
| 12–15 | Decode / D1 | 16–23, two contiguous ranks per instance | 2 |

`serving/__main__.py` sets `use_pd_companion_ranks` from the receiver mode.
The default builder argument is SHADOW-compatible, so an audit that invokes
`build_cluster_config()` without `use_pd_companion_ranks=False` incorrectly
reports 32 ranks. The ACTUAL runtime build has 24 ranks and network dimensions
`[2, 12]`; `start_npu_ids` and `end_npu_ids` are consistent with those real
instance ranges. The physical topology therefore has exactly 24 GPU endpoints
(0–23), six NIC nodes (24–29), and one ToR node (30).

The eight Decode instances form one `decode_ep` DP group. Each instance has
TP=2 and local EP=2; the group EP degree is 16. The exact EP rank ledger is
ASTRA ranks 8–23, ordered D0 ranks 8–15 then D1 ranks 16–23. Logical EP ranks
0–7 map to D0 and 8–15 to D1. This mapping is generated from the ACTUAL build,
not inferred from the JSON instance order alone.

## P/D pairing and model-derived P2D shards

The pairing file maps each Prefill instance 0–7 to Decode instance 8–15.
`serving/__main__.py` validates that all Prefill IDs and only Decode IDs appear.
The Chakra converter's `_pd_kv_destinations()` intersects the source and
destination TP partitions. With Prefill TP=1 and Decode TP=2, one Prefill
rank's layer KV is divided equally over the paired Decode instance's two real
ranks; the byte total is conserved.

For Qwen3-30B-A3B-Instruct-2507, the checked-in model config gives 48 layers,
4 KV heads, head dimension 128, 128 experts and top-k 8. With BF16 KV, one
8192-token request produces per layer:

`2 (K,V) × 4 KV heads × 128 dimensions × 8192 tokens × 2 bytes = 16,777,216 B`.

TP1→TP2 sends 8,388,608 B to each paired Decode TP rank per layer. Across 48
layers this is 805,306,368 B/request, before any protocol headers. No KV byte
override is present in the experiment config.

## Physical network and shared directed resources

`configs/large_scale/ns3/minimal_1p2d_ep16_2x200g_single_tor.txt` declares 31
nodes, one switch (node 30), and 33 physical links:

- 24 GPU-to-NIC attachments at 7200 Gbps;
- three local NIC0↔NIC1 links (one per server) at 7200 Gbps;
- six independent NIC-to-ToR uplinks at 200 Gbps each.

The topology file lists each physical link once. Native ns-3 creates both
directions with independent directed link IDs. FlowSim materializes reverse
directions and keeps each 200-Gbps NIC uplink as its own directed resource;
there is no parallel-link capacity aggregation in this single-ToR topology.

Example critical geometry:

```text
P2D: P0-G0(0) -> P0-NIC0(24) -> ToR(30) -> D0-NIC0(26) -> D0-G0(8)
EP:  D1-G0(16) -> D1-NIC0(28) -> ToR(30) -> D0-NIC0(26) -> D0-G0(8)
```

The paths share the directed `ToR 30 -> D0 NIC0 26` 200-Gbps link and the
`D0 NIC0 26 -> D0-G0 8` local endpoint attachment. This proves a shared path
exists; it does not prove sustained queueing or a barrier penalty. Local EP
paths whose two endpoints are within a Decode server bypass the ToR.

The FlowSim test uses one model-sized layer KV shard and one equal-sized
topology-probe flow solely to verify routing and max-min sharing. Both complete
at 1,352,378 ns in that unit probe. The probe's second flow is not a model EP
workload and its result is not research evidence.

## Backend scope

- FlowSim takes ASTRA rank IDs as endpoints and parses the explicit topology
  file. It reports analytical fluid rates/backlog, not packet queues, ECN,
  PFC, loss, or DCQCN.
- Native ns-3 receives the same file through `TOPOLOGY_FILE`; `common.h::SetupNetwork`
  instantiates each listed physical link and its reverse direction. Its
  logical-topology JSON is a separate ASTRA rank-coordinate description with
  24-rank capacity, not a substitute for the physical topology.
- In the present ACTUAL FlowSim path, the P2D sender's endpoint is the paired
  real Decode rank and the sender graph waits for the FlowSim transfer before
  the Decode request becomes ready. ns-3 remains necessary if the candidate
  depends on packet queueing/ECN/PFC; it is not used to infer integrated serving
  latency unless its completions feed back into the serving scheduler.

## Reproducible audit checks

1. Run `python3 experiments/pd_kv_ep/configs/generate_minimal_1p2d.py`.
2. From `astra-sim/`, call `build_cluster_config(...,
   use_pd_companion_ranks=False)` for this ACTUAL setup.
3. Assert 24 ranks; Prefill instances 0–7; Decode instances 8–15; Decode EP
   ranks 8–23; dimensions `[2, 12]`.
4. Check the two example routes above and their shared directed 200-Gbps link.
5. Check TP1→TP2 P2D shard destinations `(8, 9)` for P0 instance 0 and that
   the two byte shares sum to the model-derived source-layer payload.

