# FlowSim backend

`--network-backend flowsim` runs the native LLMServingSim serving frontend
with a directed, event-driven fluid flow model.  The frontend still generates
the Chakra graphs from the selected model/profile, so P2D bytes, MoE routing,
EP dispatch, and EP combine bytes are not synthetic inputs.

The backend uses max-min sharing on the directed topology in
`configs/ns3/`.  `FAIR`, `EP_FIRST`, and `KV_FIRST` are class-level rate
policies in the flow allocator.  FlowSim does not simulate packets, switch
buffer cells, ECN, PFC, or drops; its `queue_bytes` field is residual fluid
in the active flows and must not be reported as a packet queue.

Parallel physical links in the ns-3 topology are represented as one aggregate
fluid resource with the summed capacity.  This is appropriate for a bundle
fed by many 200-Gbps GPU endpoint links: an individual end-to-end flow is
still limited by its endpoint access link, while concurrent flows can share
the aggregate leaf--spine capacity.  The backend does not choose an ECMP hash
for an individual physical link and must not be used to claim per-link packet
queue, ECN, or PFC behavior.

For the native `NATIVE_AG_RS` EP realization, the adapter preserves the
collective-size contract before applying its direct-peer fluid approximation:
AllGather sends the per-rank local chunk to each remote peer, while
ReduceScatter sends a per-destination `comm_size/N` shard.  `A2A_P2P` remains
the preferred mode when exact GateRouter peer bytes and routes are required.

## Fast correctness gate

Use the writable protobuf environment created for this checkout:

```bash
conda run --no-capture-output -p /home/dell/lpm/conda-envs/llmsim-flowsim-pb320 \
  python -m serving \
  --cluster-config experiments/pd_kv_ep/configs/small_two_prefill_pd_moe_ep4.json \
  --dataset experiments/pd_kv_ep/workloads/moe_i8_o4_n1.jsonl \
  --num-reqs 1 \
  --network-backend flowsim \
  --ep-collective-semantics A2A_P2P \
  --pd-kv-transfer-mode POST_PREFILL \
  --pd-kv-receiver-mode ACTUAL \
  --no-enable-prefix-caching \
  --no-enable-chunked-prefill \
  --max-num-seqs 8 \
  --max-num-batched-tokens 64 \
  --log-interval 1000 \
  --output experiments/pd_kv_ep/results/flowsim-one-request/requests.csv
```

The run writes per-request serving metrics to the requested CSV and streams
flow telemetry to the run's `flowsim/flow_telemetry.jsonl`.  Telemetry rows are
bounded by `FLOWSIM_MAX_TELEMETRY_ROWS` (default 4096); detailed per-flow
records remain streamed to disk rather than retained in memory.  Omit
`--keep-inputs` for production runs so generated ET graphs are cleaned up.

FlowSim uses a strict group-wide Decode completion barrier.  It does not
pipeline duplicate scheduler rounds while a peer rank is still completing the
current EP group.  Stale worker wake events are discarded when a rank already
has a newly installed graph; this is required for TTFT/TPOT/TBT correctness.

## P2D transfer granularity

The serving frontend and the standalone model-derived FlowSim ledger expose
the same two modes:

| mode | behavior |
|---|---|
| `POST_PREFILL` | one model-derived K+V cache transfer after all prefill layers |
| `LAYERWISE` | one independent K+V transfer after each transformer layer |

`LAYERWISE` preserves the total model-derived KV bytes; it changes only the
transfer granularity and the profile-backed start anchor of each layer. For the
Qwen3 primary model this produces 48 layer events per Prefill-to-Decode shard.
The default of the standalone motivation builder remains `POST_PREFILL` so old
results are reproducible. Generate the layerwise ledger with:

```bash
python3 experiments/pd_kv_ep/scripts/build_flowsim_motivation.py \
  --trace experiments/pd_kv_ep/workloads/motivation_large_kv_4.jsonl \
  --count 4 \
  --pd-kv-transfer-mode LAYERWISE \
  --output-dir /tmp/flowsim-layerwise-large
```

The replay manifest and request CSV record `pd_kv_transfer_mode`,
`p2d_event_count`, and per-event `layer_id`. KV FCT for this mode is the
first layer-event start to the final required shard completion, not the
maximum FCT of one individual layer flow.

## Trace replay and memory-bounded discovery

`experiments/pd_kv_ep/scripts/run_flowsim_replay.py` replays a complete
model-derived event ledger in one FlowSim event queue, which is the path used
for cross-request P2D/EP overlap.  For large ledgers,
`--coalesce-ep-window-us` streams the CSV and aggregates EP rows by time
bucket, directed pair, and subtype instead of materializing every peer flow.
KV rows remain request-level.  This mode is a capacity-envelope experiment;
with a coarse bucket it cannot produce per-request EP CCT or integrated
scheduler TTFT/TPOT/TBT/SLO.

The replay runner also builds a request-to-collective index in one pass.  It
must not scan all events for every request and collective: that quadratic
analysis path caused an avoidable multi-GB RSS spike on S64 before it was
removed.  `FLOWSIM_MAX_TELEMETRY_ROWS` bounds retained residual-fluid
telemetry independently of the flow completion output.

The integrated serving-metric audit, including TTFT/TPOT/TBT/SLO definitions,
matched low-load baselines, policy comparisons, and the packet-level
observability boundary, is recorded in
[`FLOWSIM_INTEGRATED_VALIDATION.md`](FLOWSIM_INTEGRATED_VALIDATION.md).
